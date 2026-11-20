"""The fishing loop: cast, watch for the splash, loot, repeat."""
from __future__ import annotations

import enum
import random
import threading
import time
from dataclasses import dataclass

LURE_APPLY_WAIT_SEC = 5
POLL_INTERVAL_SEC = 0.1

# What the loop is doing right now, for the interface.
WAITING = 'waiting'  # the game window is not in front
PAUSED = 'paused'
FISHING = 'fishing'
STOPPED = 'stopped'


class CastResult(enum.Enum):
    LOOTED = 'looted'
    MISSED = 'missed'
    INTERRUPTED = 'interrupted'


@dataclass
class Stats:
    casts: int = 0
    looted: int = 0
    missed: int = 0
    misses_in_a_row: int = 0


class FishingBot:
    """Runs the fishing loop until stopped.

    Keys and clicks are only sent while the game window is in the foreground, so switching to
    another application makes the bot wait instead of typing into it. ``stop``, ``set_paused``
    and ``toggle_pause`` may be called from other threads (the hotkeys and the interface).
    """

    def __init__(self, settings, window, vision, controls, clock=time.monotonic, idle=time.sleep, log=print):
        self._settings = settings
        self._window = window
        self._vision = vision
        self._controls = controls
        self._clock = clock
        self._idle = idle
        self._log = log
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._last_lure = None
        self._started = None
        self.stats = Stats()
        self.state = WAITING
        self.stop_reason = ''

    def stop(self, reason='Stopped.'):
        if not self._stop.is_set():
            self.stop_reason = reason
            self._stop.set()

    def set_paused(self, paused):
        if paused == self._paused.is_set():
            return
        if paused:
            self._paused.set()
            self._log('Paused.')
        else:
            self._paused.clear()
            self._log('Resumed.')

    def toggle_pause(self):
        self.set_paused(not self._paused.is_set())

    @property
    def paused(self):
        return self._paused.is_set()

    def elapsed_seconds(self):
        return 0 if self._started is None else self._clock() - self._started

    def run(self):
        self._started = self._clock()
        self._window.focus()

        try:
            while self._wait_until_ready():
                if self._limit_reached():
                    break

                self._apply_lure_if_due()
                result = self._cast()

                if result is CastResult.INTERRUPTED:
                    continue
                if result is CastResult.MISSED:
                    self.stats.missed += 1
                    self.stats.misses_in_a_row += 1
                    self._log('No fish caught. Check that you are in first-person view, the interface is '
                              'hidden and the bobber is inside the scanned area.')

                self._sleep(random.randrange(0, 3))
        finally:
            self.state = STOPPED

    def _limit_reached(self):
        minutes = self._settings.stop_after_minutes
        if minutes and self.elapsed_seconds() >= minutes * 60:
            self.stop(f'Stopped: the {minutes} minute limit was reached.')
            return True

        misses = self._settings.stop_after_misses
        if misses and self.stats.misses_in_a_row >= misses:
            self.stop(f'Stopped: {misses} casts in a row caught nothing. '
                      'Check the bag space, the fishing key and what the bot sees.')
            return True

        return False

    def _wait_until_ready(self):
        """Block until input may be sent. Returns False once the bot should shut down."""
        announced = False

        while not self._stop.is_set():
            if not self._window.exists():
                self.stop('Stopped: the game window was closed.')
                return False

            if self._paused.is_set():
                self.state = PAUSED
            elif self._window.is_foreground() and self._window.capture_region() is not None:
                self.state = FISHING
                return True
            else:
                self.state = WAITING
                if not announced:
                    self._log('Waiting for the game window to be in front. Nothing is sent to other windows.')
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
        """Sleep in short slices so stopping takes effect quickly."""
        deadline = self._clock() + seconds

        while not self._stop.is_set():
            remaining = deadline - self._clock()
            if remaining <= 0:
                break
            self._idle(min(remaining, POLL_INTERVAL_SEC))

    def _apply_lure_if_due(self):
        settings = self._settings
        if not (settings.lure_enabled and settings.lure_key):
            return

        now = self._clock()
        if self._last_lure is not None and now - self._last_lure <= settings.lure_minutes * 60:
            return

        if self._press(settings.lure_key):
            self._last_lure = now
            self._log(f'Applied the lure ({settings.lure_key} key) for {settings.lure_minutes} minutes.')
            self._sleep(LURE_APPLY_WAIT_SEC)

    def _cast(self):
        if not self._press(self._settings.fishing_key):
            return CastResult.INTERRUPTED

        self.stats.casts += 1
        self._log(f'Cast {self.stats.casts}: waiting for a fish...')

        frame_interval = 1 / self._settings.checks_per_second
        deadline = self._clock() + self._settings.cast_seconds
        while self._clock() < deadline:
            frame_started = self._clock()
            if not self._can_act():
                return CastResult.INTERRUPTED

            # Read on every frame, so the window can be moved or resized while fishing.
            region = self._window.capture_region()
            if region is None:
                return CastResult.INTERRUPTED

            position = self._vision.find_splash(region)
            if position is not None:
                return CastResult.LOOTED if self._loot(*position) else CastResult.INTERRUPTED

            # Looking a few times a second is enough to catch the splash and leaves the CPU mostly idle.
            self._sleep(frame_interval - (self._clock() - frame_started))

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
        # Click at the splash itself: the pointer may have been moved since the line above.
        self._controls.click(x=x, y=y, button='right')

        self.stats.looted += 1
        self.stats.misses_in_a_row = 0
        self._log(f'Splash at x: {x}, y: {y} - looted ({self.stats.looted} this session).')
        return True
