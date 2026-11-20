"""World of Warcraft fishing bot: cast, watch for the bobber splash, loot, repeat."""
from __future__ import annotations

import enum
import random
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pyfiglet
from colorama import Fore, init as init_color

CAST_DURATION_SEC = 20
LURE_APPLY_WAIT_SEC = 5
POLL_INTERVAL_SEC = 0.1
PAUSE_HOTKEY = 'f8'
QUIT_HOTKEY = 'f9'
MODEL_PATH = Path(__file__).with_name('best.pt')
DEVICE = 'cpu'  # e.g. 'cuda:0' if you installed a CUDA build of torch


class CastResult(enum.Enum):
    LOOTED = 'looted'
    MISSED = 'missed'
    INTERRUPTED = 'interrupted'


@dataclass(frozen=True)
class Config:
    fishing_key: str
    lure_key: str | None = None
    lure_duration_sec: float = 0


class FishingBot:
    """Runs the fishing loop until stopped.

    Keys and clicks are only sent while the game window is in the foreground,
    so switching to another application pauses the bot instead of typing into it.
    ``stop`` and ``toggle_pause`` may be called from another thread (the hotkeys).
    """

    def __init__(self, config, window, detector, controls, clock=time.monotonic, idle=time.sleep):
        self._config = config
        self._window = window
        self._detector = detector
        self._controls = controls
        self._clock = clock
        self._idle = idle
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._last_lure = None
        self.loot_attempts = 0

    def stop(self):
        self._stop.set()

    def toggle_pause(self):
        if self._paused.is_set():
            self._paused.clear()
            print(Fore.CYAN + 'Resumed.' + Fore.RESET)
        else:
            self._paused.set()
            print(Fore.CYAN + f'Paused. Press {PAUSE_HOTKEY.upper()} to resume.' + Fore.RESET)

    def run(self):
        self._window.focus()

        while self._wait_until_ready():
            self._apply_lure_if_due()
            result = self._cast()

            if result is CastResult.INTERRUPTED:
                continue
            if result is CastResult.MISSED:
                print(
                    Fore.MAGENTA + "No fish caught :( Sometimes the bot can miss. Be sure you are in first person view, have hidden your UI and the bobber is visible on screen" + Fore.RESET)

            self._sleep(random.randrange(0, 3))

    def _wait_until_ready(self):
        """Block until input may be sent. Returns False once the bot should shut down."""
        announced = False

        while not self._stop.is_set():
            if not self._window.exists():
                print(Fore.RED + 'The game window was closed.' + Fore.RESET)
                return False

            if not self._paused.is_set():
                if self._window.is_foreground() and self._window.capture_region() is not None:
                    return True
                if not announced:
                    print(Fore.CYAN + 'Waiting for the game window to be in front. Nothing is sent to other windows.' + Fore.RESET)
                    announced = True

            self._idle(POLL_INTERVAL_SEC)

        return False

    def _can_act(self):
        return not self._stop.is_set() and not self._paused.is_set() and self._window.is_foreground()

    def _press(self, key):
        if not self._can_act():
            return False
        self._controls.press(key)
        return True

    def _sleep(self, seconds):
        """Sleep in short slices so the quit hotkey and CTRL+C take effect quickly."""
        deadline = self._clock() + seconds

        while not self._stop.is_set():
            remaining = deadline - self._clock()
            if remaining <= 0:
                break
            self._idle(min(remaining, POLL_INTERVAL_SEC))

    def _apply_lure_if_due(self):
        if not self._config.lure_key:
            return

        now = self._clock()
        if self._last_lure is not None and now - self._last_lure <= self._config.lure_duration_sec:
            return

        if self._press(self._config.lure_key):
            self._last_lure = now
            print(f'Attach new lure ({self._config.lure_key} key) for {self._config.lure_duration_sec / 60:g} minutes.')
            print(f'Waiting {LURE_APPLY_WAIT_SEC} seconds before continue...')
            self._sleep(LURE_APPLY_WAIT_SEC)

    def _cast(self):
        if not self._press(self._config.fishing_key):
            return CastResult.INTERRUPTED

        print(Fore.CYAN + '\nStart fishing.' + Fore.RESET)
        print(Fore.CYAN + 'Waiting for a fish...' + Fore.RESET)

        deadline = self._clock() + CAST_DURATION_SEC
        while self._clock() < deadline:
            if not self._can_act():
                return CastResult.INTERRUPTED

            # Read on every frame, so the window can be moved or resized while fishing.
            region = self._window.capture_region()
            if region is None:
                return CastResult.INTERRUPTED

            position = self._detector.find_splash(region)
            if position is not None:
                return CastResult.LOOTED if self._loot(*position) else CastResult.INTERRUPTED

        return CastResult.MISSED

    # Right click on the bobber to loot the fish, player must enable automatic looting
    def _loot(self, x, y):
        self._sleep(random.random())
        if not self._can_act():
            return False
        self._controls.moveTo(x, y, random.uniform(0.1, 0.3))

        self._sleep(random.random())
        if not self._can_act():
            return False
        self._controls.click(button='right')

        self.loot_attempts += 1
        print(Fore.GREEN + f'Splash at position x: {x}, y: {y} - looted!' + Fore.RESET)
        print(f'Loot attempts this session: {self.loot_attempts}.')
        return True


def validate_key(raw, valid_keys):
    """Return the normalised key name, or raise ValueError if the bot could not press it."""
    key = raw.strip().lower()

    if key in (PAUSE_HOTKEY, QUIT_HOTKEY):
        raise ValueError(f"'{key}' is reserved for pausing/stopping the bot.")
    # pyautogui silently ignores names it does not know, which would look like a bot that never casts.
    if key not in valid_keys:
        raise ValueError(f"'{key}' is not a key name the bot can press. Use names like f, 1, f5, space, num1.")

    return key


def ask_key(prompt, valid_keys, ask=input):
    while True:
        try:
            return validate_key(ask(prompt), valid_keys)
        except ValueError as error:
            print(Fore.RED + str(error) + Fore.RESET)


def ask_minutes(prompt, ask=input):
    while True:
        try:
            minutes = int(ask(prompt).strip())
        except ValueError:
            minutes = 0

        if minutes > 0:
            return minutes
        print(Fore.RED + 'Enter a whole number of minutes greater than 0, e.g. 10.' + Fore.RESET)


def configure(valid_keys, ask=input):
    fishing_key = ask_key('Provide the key for the fishing spell: ', valid_keys, ask)

    if ask('Do you want to use lure ? (y/n) ').strip().lower() != 'y':
        return Config(fishing_key)

    lure_key = ask_key('Provide the key to use lure: ', valid_keys, ask)
    lure_minutes = ask_minutes('Provide the lure duration (in minutes): ', ask)
    return Config(fishing_key, lure_key, 60 * lure_minutes)


def show_start_text():
    ascii_text = pyfiglet.figlet_format('WoW_Fish_YOLO')
    print(Fore.CYAN + ascii_text + Fore.RESET)
    print(Fore.RED + 'Make sure you have enabled the auto-loot feature in the game settings.' + Fore.RESET)
    print(
        Fore.RED + 'Additionally, for best results, zoom into the first person view and hide the UI by pressing ALT+W (or ALT+Z on QWERTY).' + Fore.RESET)
    print(f'{PAUSE_HOTKEY.upper()} pauses/resumes the bot, {QUIT_HOTKEY.upper()} stops it (CTRL+C in this console also works).')
    print('The bot only sends keys and clicks while the game window is in front.')


def main():
    init_color()
    show_start_text()

    if sys.platform != 'win32':
        print(Fore.RED + 'This bot only runs on Windows.' + Fore.RESET)
        return 1

    # Imported here rather than at the top: these need Windows, and keeping them out of
    # module scope lets the fishing loop above be imported and tested on any machine.
    import keyboard
    import pyautogui
    from detector import SplashDetector
    from game_window import GameWindowNotFound, find_game_window

    try:
        window = find_game_window()
    except GameWindowNotFound as error:
        print(Fore.RED + str(error) + Fore.RESET)
        return 1

    bot = None
    try:
        config = configure(pyautogui.KEYBOARD_KEYS)

        print('Loading model...')
        detector = SplashDetector(MODEL_PATH, DEVICE)
        print(f'Model loaded! Predictions run on: {DEVICE}.')

        bot = FishingBot(config, window, detector, pyautogui)
        # On release, so holding the key down does not toggle pause over and over.
        keyboard.add_hotkey(PAUSE_HOTKEY, bot.toggle_pause, trigger_on_release=True)
        keyboard.add_hotkey(QUIT_HOTKEY, bot.stop)
        bot.run()
    except KeyboardInterrupt:
        print(Fore.RED + 'Keyboard interrupt received. Exiting...' + Fore.RESET)
    except pyautogui.FailSafeException:
        print(Fore.RED + 'Mouse moved to a screen corner (pyautogui fail-safe). Exiting...' + Fore.RESET)
    finally:
        keyboard.unhook_all_hotkeys()

    if bot is not None:
        print(f'Loot attempts this session: {bot.loot_attempts}.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
