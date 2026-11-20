"""Check the system-specific parts of the bot against a real window on this computer.

    python tools/desktop_probe.py

It opens a small test window showing the demo picture and checks, with the same code the bot
uses, that it can find the window, bring it to the front, capture it, detect the (synthetic)
splash in it, press a key and right-click on the splash. Run it when the bot does not react on
your system: the first check that fails says which part is the problem. It briefly takes over
the keyboard and mouse.

The GitHub workflow runs this on Windows and macOS as a report; it never fails the build.
"""
import os
import sys
import threading
import time
import tkinter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from fishbot import platforms  # noqa: E402
from fishbot.detector import SplashDetector  # noqa: E402
from fishbot.engine import FishingBot  # noqa: E402
from fishbot.platforms import demo  # noqa: E402
from fishbot.settings import Settings  # noqa: E402
from fishbot.vision import Vision, looks_blank  # noqa: E402

TITLE = 'Fishbot desktop probe'
WIDTH, HEIGHT = demo.REGION['width'], demo.REGION['height']
SPLASH = (345, 236)  # where the synthetic splash is in the picture
NEAR = 12
ON_GITHUB = os.environ.get('GITHUB_ACTIONS') == 'true'

results = []


def report(name, passed, detail):
    results.append(passed)
    print(f'{"PASS" if passed else "FAIL"}  {name}: {detail}', flush=True)
    if ON_GITHUB:
        level = 'notice' if passed else 'warning'
        print(f'::{level} title=Desktop probe ({sys.platform})::{"PASS" if passed else "FAIL"} {name}: {detail}', flush=True)


def check(name):
    """Run one check; an exception is a failure with the error as its detail."""
    def wrap(function):
        try:
            passed, detail = function()
        except Exception as error:
            passed, detail = False, f'{type(error).__name__}: {error}'
        report(name, passed, detail)
        return passed
    return wrap


def main():
    platform = platforms.load()
    print(f'Probing {platform.LABEL} with Python {sys.version.split()[0]}', flush=True)

    root = tkinter.Tk()
    root.title(TITLE)
    root.geometry(f'{WIDTH}x{HEIGHT}+160+160')
    root.resizable(False, False)
    canvas = tkinter.Canvas(root, width=WIDTH, height=HEIGHT, highlightthickness=0, borderwidth=0)
    canvas.pack()
    picture = tkinter.PhotoImage(file=str(demo.ASSETS / 'demo_splash.png'))
    canvas.create_image(0, 0, anchor='nw', image=picture)
    canvas.focus_set()

    events = []
    root.bind('<KeyPress>', lambda event: events.append(('key', event.keysym.lower())))
    canvas.bind('<ButtonPress>', lambda event: events.append(('button', event.num, event.x, event.y)))

    def pump(seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            root.update()
            time.sleep(0.02)

    pump(1.0)
    inside = (root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height())
    state = {}

    @check('find the window')
    def _():
        # Point the bot's own window search at this test window instead of the game.
        if platform.SYSTEM == 'windows':
            import psutil
            platform.WINDOW_TITLE = TITLE
            platform.PROCESS_NAME_PREFIX = psutil.Process().name().lower()
        else:
            mine = [w for w in platform._window_list(onscreen_only=True) if w.get('kCGWindowOwnerPID') == os.getpid()]
            platform.OWNER_NAME_PREFIX = str(mine[0]['kCGWindowOwnerName']) if mine else 'no window owned by this process'
        state['window'] = platform.find_game_window()
        return state['window'].exists(), f'found, exists() = {state["window"].exists()}'

    if 'window' not in state:
        print('The window was not found, so the remaining checks cannot run.')
        return finish(root)
    window = state['window']

    @check('bring it to the front')
    def _():
        window.focus()
        pump(1.0)
        return window.is_foreground(), f'is_foreground() = {window.is_foreground()}'

    @check('locate its drawing area')
    def _():
        region = window.capture_region()
        state['region'] = region
        extra = (inside[1] - region['top']) if region else None
        good = (region is not None and abs(region['left'] - inside[0]) <= 2 and abs(region['width'] - inside[2]) <= 2
                and 0 <= extra <= 60 and abs(region['height'] - extra - inside[3]) <= 2)
        return good, f'bot says {region}; the window says x={inside[0]} y={inside[1]} w={inside[2]} h={inside[3]} (title bar included: {extra} px)'

    region = state.get('region')
    if region is None:
        print('The drawing area is unknown, so the remaining checks cannot run.')
        return finish(root)
    grabber = platform.create_grabber()
    offset = (inside[0] - region['left'], inside[1] - region['top'])  # where the picture starts inside the region

    @check('capture the screen')
    def _():
        frame = grabber.grab(region)
        scale = frame.shape[1] / region['width']
        expected = cv2.imread(str(demo.ASSETS / 'demo_splash.png'))
        left, top = int(offset[0] * scale), int(offset[1] * scale)
        seen = frame[top:top + int(HEIGHT * scale), left:left + int(WIDTH * scale)]
        if seen.shape[:2] != expected.shape[:2] and seen.size:
            seen = cv2.resize(seen, (WIDTH, HEIGHT), interpolation=cv2.INTER_AREA)
        difference = float(np.abs(seen.astype(int) - expected.astype(int)).mean()) if seen.shape == expected.shape else 255.0
        return (not looks_blank(frame) and difference < 12,
                f'{frame.shape[1]}x{frame.shape[0]} pixels for a {region["width"]}x{region["height"]} region, '
                f'blank = {looks_blank(frame)}, average difference from the picture shown = {difference:.1f} of 255')

    detector = SplashDetector()
    vision = Vision(detector, grabber, 0.8, 'full')
    target = (inside[0] + SPLASH[0], inside[1] + SPLASH[1])

    @check('detect the splash and place it on the screen')
    def _():
        position = vision.find_splash(region)
        near = position is not None and abs(position[0] - target[0]) <= NEAR and abs(position[1] - target[1]) <= NEAR
        return near, (f'found at {position}, expected about {target}, score {vision.last.detection.score:.3f}, '
                      f'{detector.last_inference_ms:.0f} ms')

    controls = platform.create_controls()
    controls.FAILSAFE = False  # a build machine may park its mouse in a corner; this is only for the probe

    @check('press a key')
    def _():
        events.clear()
        controls.press('f')
        pump(0.8)
        return ('key', 'f') in events, f'the window received {events}'

    @check('stay in front while keys are pressed')
    def _():
        # The fishing loop asks "is the game in front?" from its own thread, right after pressing keys.
        samples, not_front, no_region, seen_in_front = [], [], [], []
        done = threading.Event()

        def watch():
            while not done.is_set():
                front = window.is_foreground()
                samples.append(front)
                if not front:
                    not_front.append(time.monotonic())
                    if platform.SYSTEM == 'macos' and len(seen_in_front) < 3:
                        seen_in_front.append([(str(w.get('kCGWindowOwnerName')), w.get('kCGWindowLayer'),
                                               int(w['kCGWindowBounds'].get('Width', 0)), int(w['kCGWindowBounds'].get('Height', 0)))
                                              for w in platform._window_list(onscreen_only=True)[:6]])
                if window.capture_region() is None:
                    no_region.append(time.monotonic())
                time.sleep(0.03)

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        pump(0.5)
        for _ in range(3):
            controls.press('f')
            pump(0.7)
        done.set()
        watcher.join(5)
        return (not not_front and not no_region,
                f'{len(samples)} samples: not in front {len(not_front)} times, no drawing area {len(no_region)} times; '
                f'windows in front when it was not: {seen_in_front}')

    @check('move the mouse and right-click')
    def _():
        events.clear()
        controls.moveTo(target[0], target[1], 0.2)
        pump(0.3)
        controls.click(button='right')
        pump(0.8)
        clicks = [event for event in events if event[0] == 'button']
        good = any(event[1] in (2, 3) and abs(event[2] - SPLASH[0]) <= NEAR and abs(event[3] - SPLASH[1]) <= NEAR
                   for event in clicks)
        return good, f'the window received {clicks}, expected a right button near {SPLASH}'

    @check('read a hotkey')
    def _():
        before = platform.key_is_down('f8')
        controls.keyDown('f8')
        pump(0.3)
        held = platform.key_is_down('f8')
        controls.keyUp('f8')
        pump(0.3)
        after = platform.key_is_down('f8')
        return (not before) and held and (not after), f'F8 read as {before} before, {held} while held, {after} after'

    @check('one whole cast with the real fishing loop')
    def _():
        events.clear()
        messages = []
        bot = FishingBot(Settings(fishing_key='f', stop_after_misses=0), window, vision, controls, log=messages.append)
        thread = threading.Thread(target=bot.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 40
        while bot.stats.looted < 1 and thread.is_alive() and time.monotonic() < deadline:
            pump(0.1)
        bot.stop()
        pump(0.5)
        thread.join(5)
        clicks = [event for event in events if event[0] == 'button' and event[1] in (2, 3)]
        on_target = any(abs(event[2] - SPLASH[0]) <= NEAR and abs(event[3] - SPLASH[1]) <= NEAR for event in clicks)
        return (bot.stats.looted >= 1 and ('key', 'f') in events and on_target,
                f'casts {bot.stats.casts}, looted {bot.stats.looted}, final state {bot.state}; '
                f'window received key f: {("key", "f") in events}, right-clicks: {clicks}; log: {messages[-2:]}')

    return finish(root)


def finish(root):
    root.destroy()
    passed, total = sum(results), len(results)
    print(f'\n{passed} of {total} checks passed.')
    if ON_GITHUB:
        print(f'::notice title=Desktop probe ({sys.platform})::{passed} of {total} checks passed')
    return 0 if ON_GITHUB or passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
