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
SPLASH = (344, 248)  # where the synthetic splash is in the picture
NEAR = 12
ON_GITHUB = os.environ.get('GITHUB_ACTIONS') == 'true'

results = []


def report(name, passed, detail):
    results.append((name, passed, detail))
    print(f'{"PASS" if passed else "FAIL"}  {name}: {detail}', flush=True)


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

    def in_front_report():
        """How each way of asking "who is in front" answers right now (macOS has several)."""
        if platform.SYSTEM != 'macos':
            return f'is_foreground={window.is_foreground()}'
        from AppKit import NSWorkspace
        listed = platform._window_list(onscreen_only=True)
        top = [(w.get('kCGWindowOwnerName'), w.get('kCGWindowLayer'), int(w['kCGWindowBounds'].get('Width', 0)),
                int(w['kCGWindowBounds'].get('Height', 0))) for w in listed[:5]]
        workspace = NSWorkspace.sharedWorkspace().frontmostApplication()
        return (f'me={os.getpid()} window-order={platform.frontmost_pid(listed)} keyboard-focus={platform.focused_pid()} '
                f'workspace={workspace.processIdentifier() if workspace is not None else None} top={top}')

    @check('permissions and focus as the system reports them')
    def _():
        if platform.SYSTEM != 'macos':
            return True, f'no permissions needed; {in_front_report()}'
        return True, (f'screen recording allowed={platform.screen_recording_allowed()}, '
                      f'accessibility allowed={platform.accessibility_allowed()}, problems={platform.permission_problems()}; '
                      f'{in_front_report()}')

    def from_a_thread(action):
        """Run ``action`` on another thread while this one keeps the window alive; return what it returned."""
        box = {}

        def run():
            try:
                box['result'] = action()
            except Exception as error:
                box['result'] = f'{type(error).__name__}: {error}'

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        while thread.is_alive():
            pump(0.05)
        return box.get('result')

    def watch(seconds):
        """Sample is_foreground for a while from a thread; return (samples, times it was False, a report)."""
        def sample():
            taken, lost, report_text = 0, 0, ''
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                taken += 1
                if not window.is_foreground():
                    lost += 1
                    report_text = report_text or in_front_report()
                time.sleep(0.03)
            return taken, lost, report_text
        return from_a_thread(sample)

    # The fishing loop does three things from its own thread. Each is tried alone, to see which
    # one (if any) makes the window stop counting as "in front".
    for name, action in (('focus() from another thread', lambda: window.focus()),
                         ('press a key from another thread', lambda: controls.press('f')),
                         ('capture the screen from another thread', lambda: grabber.grab(region).shape)):
        @check(f'still in front after: {name}')
        def _(action=action):
            outcome = from_a_thread(action)
            taken, lost, report_text = watch(1.5)
            return lost == 0, f'returned {outcome}; {taken} samples, not in front {lost} times; {report_text}'

    if platform.SYSTEM == 'macos':
        @check('what macOS says about the window around a key press')
        def _():
            # Earlier runs showed the window missing from the on-screen list for about half a
            # second after a key press made from another thread. This records what is reported then.
            def describe():
                mine = [(w.get('kCGWindowNumber'), w.get('kCGWindowName'), w.get('kCGWindowLayer'), w.get('kCGWindowAlpha'),
                         int(w['kCGWindowBounds'].get('Width', 0)), int(w['kCGWindowBounds'].get('Height', 0)))
                        for w in platform._window_list(onscreen_only=True) if w.get('kCGWindowOwnerPID') == os.getpid()]
                direct = platform._window_info(window.window_number) or {}
                return (f'on-screen windows of this process {mine}; asked directly: onscreen={direct.get("kCGWindowIsOnscreen")} '
                        f'layer={direct.get("kCGWindowLayer")} alpha={direct.get("kCGWindowAlpha")}; '
                        f'capture_region={"found" if window.capture_region() else None}')

            def press_and_look():
                notes = [f'the window is number {window.window_number}', f'before: {describe()}']
                controls.press('f')
                for delay in (0.0, 0.25, 0.6):
                    time.sleep(delay)
                    notes.append(f'after +{delay}s: {describe()}')
                return notes

            notes = from_a_thread(press_and_look)
            return True, ' || '.join(notes) if isinstance(notes, list) else str(notes)

    @check('come to the front from behind another program')
    def _():
        # The usual case: Start is pressed in the browser, so another program is in front
        # and the bot has to bring the game forward from the background.
        import subprocess
        if platform.SYSTEM == 'windows':
            other = subprocess.Popen(['notepad.exe'])
            close = other.kill
        else:
            subprocess.run(['open', '-a', 'TextEdit'], check=False)
            close = lambda: subprocess.run(['pkill', '-x', 'TextEdit'], check=False)
        try:
            deadline = time.monotonic() + 8
            while window.is_foreground() and time.monotonic() < deadline:
                pump(0.2)
            behind = not window.is_foreground()
            before = in_front_report()
            window.focus()
            pump(1.5)
            return window.is_foreground(), (f'another program took the front: {behind} ({before}); '
                                            f'after focus(): {in_front_report()}')
        finally:
            close()
            pump(1.0)
            window.focus()
            pump(1.0)

    @check('one whole cast with the real fishing loop')
    def _():
        events.clear()
        messages, trace = [], []
        began = time.monotonic()

        class Traced:
            """Passes every call through, noting what the loop was told."""
            def __init__(self, target, label):
                self._target, self._label = target, label

            def __getattr__(self, name):
                method = getattr(self._target, name)

                def call(*arguments, **keywords):
                    result = method(*arguments, **keywords)
                    if len(trace) < 28:
                        shown = result if not isinstance(result, dict) else 'region'
                        extra = ''
                        if name == 'is_foreground' and not result:
                            extra = ' ' + in_front_report()
                        if name == 'find_splash':
                            extra = f' score={vision.last.detection.score:.2f}'
                        trace.append(f'{time.monotonic() - began:.2f}s {self._label}.{name}={shown}{extra}')
                    return result
                return call

        bot = FishingBot(Settings(fishing_key='f', stop_after_misses=0), Traced(window, 'window'),
                         Traced(vision, 'vision'), Traced(controls, 'controls'), log=messages.append)
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
        passed = bot.stats.looted >= 1 and ('key', 'f') in events and on_target
        return passed, (f'casts {bot.stats.casts}, looted {bot.stats.looted}; window received key f: {("key", "f") in events}, '
                        f'right-clicks: {clicks}' + ('' if passed else f'; first calls: {trace}'))

    if platform.SYSTEM == 'macos':
        @check('whether a function key pressed by a program disturbs later keys (information)')
        def _():
            # This is why function keys are not offered for fishing or the lure on macOS.
            def bounds():
                return (platform._window_info(window.window_number) or {}).get('kCGWindowBounds')

            start_bounds = bounds()
            controls.press('f')
            pump(1.5)
            after_plain = bounds()
            controls.press('f5')
            pump(0.4)
            controls.press('f')
            pump(1.8)
            after_function_key = bounds()
            if after_function_key != start_bounds:
                controls.press('f')  # undo the full-screen switch
                pump(1.8)
            verdict = ('the letter after a function key was taken as fn+F and switched the window to full screen'
                       if after_function_key != start_bounds else 'no effect on this system')
            return True, (f'{verdict}; window at start {start_bounds}, after "f" alone {after_plain}, '
                          f'after F5 then "f" {after_function_key}')

    # Last, because on macOS pressing a function key from a program changes how later keys are read.
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

    return finish(root)


def annotation(level, title, text):
    """Print a GitHub workflow annotation. Only ten per step are kept, so the report is sent in few."""
    escaped = text.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
    print(f'::{level} title={title}::{escaped}', flush=True)


def finish(root):
    root.destroy()
    passed, total = sum(1 for _, ok, _ in results if ok), len(results)
    print(f'\n{passed} of {total} checks passed.')
    if ON_GITHUB:
        title = f'Desktop probe ({sys.platform})'
        annotation('notice', title, f'{passed} of {total} checks passed\n' + '\n'.join(
            f'{"PASS" if ok else "FAIL"} {name}: {detail}' for name, ok, detail in results))
        for name, ok, detail in results:
            if not ok:
                annotation('warning', title, f'FAIL {name}: {detail}')
    return 0 if ON_GITHUB or passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
