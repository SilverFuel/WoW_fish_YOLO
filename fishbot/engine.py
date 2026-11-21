"""The fishing loop: cast, watch for the splash, loot, repeat.

Safeguards live here too. They work in layers: only act when it is safe (the game is in front,
the user is not using the mouse), only click what plausibly is a bite, notice when the pattern
of catches stops looking like fishing, and when in doubt stop and say why rather than try to
fix anything by pressing more keys.
"""
from __future__ import annotations

import collections
import enum
import random
import threading
import time
from dataclasses import dataclass

LURE_APPLY_WAIT_SEC = 5
POLL_INTERVAL_SEC = 0.1

# The bobber is still in the air this soon after casting, so nothing seen yet can be a bite.
SETTLE_AFTER_CAST_SEC = 1.0
# Before the first cast, and after a pause, the mouse has to be left alone for this long.
STILL_BEFORE_START_SEC = 0.7
# The pointer moving further than this, when the bot did not move it, means the user took the mouse.
POINTER_MOVED_PX = 8
# A bite this soon after casting, this many times running, is not fishing: something on screen
# keeps looking like a splash.
TOO_FAST_SEC = 2.0
TOO_FAST_STREAK = 3
# The bobber lands somewhere new on every cast. This many "catches" running on the same spot
# means the bot is clicking something that does not move.
SAME_SPOT_PX = 10
SAME_SPOT_STREAK = 4
# Recasting this often within this many seconds means every cast is being cut short.
CAST_BURST_COUNT = 8
CAST_BURST_SEC = 20.0
# This many black pictures in a row: a loading screen, a disconnect, or the display is off.
BLANK_LOOKS = 15
# In practice mode, how long to wait after a sighting before looking again.
PRACTICE_PAUSE_SEC = 3.0

# What the loop is doing right now, for the interface.
WAITING = 'waiting'  # the game window is not in front
PAUSED = 'paused'
FISHING = 'fishing'
PRACTICE = 'practice'  # watching only; nothing is pressed or clicked
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
    practice_clicks: int = 0


class FishingBot:
    """Runs the fishing loop until stopped.

    Keys and clicks are only sent while the game window is in the foreground, so switching to
    another application makes the bot wait instead of typing into it. ``stop``, ``set_paused``
    and ``toggle_pause`` may be called from other threads (the hotkeys and the interface).

    ``on_click(x, y, practice)`` is called just before each right-click (or, in practice mode,
    instead of it), so the caller can keep a record of what was clicked.
    """

    def __init__(self, settings, window, vision, controls, clock=time.monotonic, idle=time.sleep, log=print,
                 on_click=None):
        self._settings = settings
        self._window = window
        self._vision = vision
        self._controls = controls
        self._clock = clock
        self._idle = idle
        self._log = log
        self._on_click = on_click
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._last_lure = None
        self._started = None
        self._pointer = None            # where the bot last left the pointer
        self._pointer_still_since = None
        self._mouse_must_settle = True  # before the first cast, and again after every wait or pause
        self._cast_times = collections.deque()
        self._catches = collections.deque(maxlen=max(TOO_FAST_STREAK, SAME_SPOT_STREAK))
        self.stats = Stats()
        self.state = WAITING
        self.stop_reason = ''
        self.stopped_by_safeguard = False

    # ----- control from outside -----

    def stop(self, reason='Stopped.'):
        if not self._stop.is_set():
            self.stop_reason = reason
            self._stop.set()

    def set_paused(self, paused, message=None):
        if paused == self._paused.is_set():
            return
        if paused:
            self._paused.set()
            self._log(message or 'Paused.')
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

    # ----- the loops -----

    def run(self):
        self._started = self._clock()
        self._window.focus()

        try:
            if self._settings.practice_mode:
                self._watch_only()
            else:
                self._fish()
        finally:
            self.state = STOPPED

    def _fish(self):
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
                self._catches.clear()
                self._log('No fish caught. Check that you are in first-person view, the interface is '
                          'hidden and the bobber is inside the scanned area.')

            self._sleep(random.randrange(0, 3))

    def _watch_only(self):
        """Practice mode: look for the splash and say what would be clicked, without any input."""
        self._log('Practice mode: watching only. Cast in the game yourself; the bot reports what it would '
                  'click and sends nothing.')
        frame_interval = 1 / self._settings.checks_per_second

        while self._wait_until_ready():
            if self._limit_reached():
                break

            frame_started = self._clock()
            region = self._window.capture_region()
            if region is None:
                self._sleep(frame_interval)
                continue

            position = self._vision.find_splash(region)
            if self._screen_is_blank():
                break
            if position is not None:
                self.stats.practice_clicks += 1
                self._record_click(*position, practice=True)
                self._log(f'Practice: would right-click at x: {position[0]}, y: {position[1]} '
                          f'({self.stats.practice_clicks} so far).')
                self._sleep(PRACTICE_PAUSE_SEC)

            self._sleep(frame_interval - (self._clock() - frame_started))

    # ----- safeguards -----

    def _trip(self, reason):
        """Stop because something does not look right. The bot never tries to fix it with more input."""
        self.stopped_by_safeguard = True
        self.stop(reason)

    def _limit_reached(self):
        minutes = self._settings.stop_after_minutes
        if minutes and self.elapsed_seconds() >= minutes * 60:
            self.stop(f'Stopped: the {minutes} minute limit was reached.')
            return True

        misses = self._settings.stop_after_misses
        if misses and self.stats.misses_in_a_row >= misses:
            self._trip(f'Stopped: {misses} cast{"" if misses == 1 else "s"} in a row caught nothing. '
                       'Check the bag space, the fishing key and what the bot sees.')
            return True

        return False

    def _recasting_too_often(self):
        """Checked before the key is pressed: would this cast be one too many in a short time?"""
        now = self._clock()
        while self._cast_times and now - self._cast_times[0] > CAST_BURST_SEC:
            self._cast_times.popleft()

        if len(self._cast_times) >= CAST_BURST_COUNT:
            self._trip(f'Stopped: the bot recast {CAST_BURST_COUNT} times in {CAST_BURST_SEC:g} seconds. '
                       'Something keeps cutting the cast short, so it stopped rather than keep pressing the key.')
            return True
        return False

    def _screen_is_blank(self):
        if getattr(self._vision, 'blank_streak', 0) >= BLANK_LOOKS:
            self._trip('Stopped: the game has shown a black screen for several seconds. That is a loading screen, '
                       'a disconnect, or a display that is off.')
            return True
        return False

    def _not_a_plausible_catch(self, seconds_since_cast, spot):
        """Judge a sighting against the last few before clicking it. Trips the bot if they look wrong."""
        self._catches.append((seconds_since_cast, spot))
        catches = list(self._catches)

        fast = catches[-TOO_FAST_STREAK:]
        if len(fast) == TOO_FAST_STREAK and all(seconds < TOO_FAST_SEC for seconds, _ in fast):
            self._trip(f'Stopped: {TOO_FAST_STREAK} times in a row the bot saw a splash within {TOO_FAST_SEC:g} seconds '
                       'of casting. A real bite takes longer, so it is probably looking at something else. '
                       'Recent clicks shows what it clicked.')
            return True

        same = [place for _, place in catches[-SAME_SPOT_STREAK:]]
        if len(same) == SAME_SPOT_STREAK and all(
                abs(a[0] - b[0]) <= SAME_SPOT_PX and abs(a[1] - b[1]) <= SAME_SPOT_PX for a in same for b in same):
            self._trip(f'Stopped: {SAME_SPOT_STREAK} catches in a row were on exactly the same spot. The bobber lands '
                       'somewhere new on every cast, so the bot is probably clicking something that is not the '
                       'bobber. Recent clicks shows what it clicked.')
            return True

        return False

    def _pointer_now(self):
        position = getattr(self._controls, 'position', None)
        if position is None or not self._settings.pause_on_mouse_move:
            return None
        x, y = position()
        return int(x), int(y)

    def _expect_pointer_at(self, x, y):
        """After the bot moves the pointer, this is where it must be. Anywhere else means the user
        interfered, even if that happened while the bot was moving it."""
        self._pointer = (int(x), int(y)) if self._pointer_now() is not None else None

    def _user_took_the_mouse(self):
        """Whether the pointer is somewhere the bot did not leave it. If so, pause and hand over."""
        now = self._pointer_now()
        if now is None or self._pointer is None:
            return False
        if abs(now[0] - self._pointer[0]) <= POINTER_MOVED_PX and abs(now[1] - self._pointer[1]) <= POINTER_MOVED_PX:
            return False

        self.set_paused(True, 'Paused: you moved the mouse, so the bot let go. Resume when you want it to continue.')
        return True

    def _mouse_has_settled(self):
        """True once the mouse has been left alone for a moment. Always true if the check is off."""
        now = self._pointer_now()
        if now is None or not self._mouse_must_settle:
            return True

        if now != self._pointer:
            self._pointer = now
            self._pointer_still_since = self._clock()
            return False
        if self._clock() - self._pointer_still_since < STILL_BEFORE_START_SEC:
            return False

        self._mouse_must_settle = False
        return True

    def _record_click(self, x, y, practice):
        if self._on_click is not None:
            self._on_click(x, y, practice)

    # ----- waiting and acting -----

    def _wait_until_ready(self):
        """Block until input may be sent. Returns False once the bot should shut down."""
        announced = False
        practice = self._settings.practice_mode

        while not self._stop.is_set():
            if not self._window.exists():
                self.stop('Stopped: the game window was closed.')
                return False

            if self._paused.is_set():
                self.state = PAUSED
                self._mouse_must_settle = True
            elif self._window.is_foreground() and self._window.capture_region() is not None:
                # In practice mode the user is playing, so the mouse is theirs throughout.
                if practice or self._mouse_has_settled():
                    self.state = PRACTICE if practice else FISHING
                    return True
            else:
                self.state = WAITING
                self._mouse_must_settle = True
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
        # Where the pointer is now is where the bot expects it to stay until it moves it itself.
        self._pointer = self._pointer_now()
        if self._recasting_too_often() or not self._press(self._settings.fishing_key):
            return CastResult.INTERRUPTED

        cast_started = self._clock()
        self._cast_times.append(cast_started)
        self.stats.casts += 1
        self._log(f'Cast {self.stats.casts}: waiting for a fish...')

        frame_interval = 1 / self._settings.checks_per_second
        deadline = cast_started + self._settings.cast_seconds
        mentioned_ignored = False
        self._sleep(SETTLE_AFTER_CAST_SEC)

        while self._clock() < deadline:
            frame_started = self._clock()
            if not self._can_act() or self._user_took_the_mouse():
                return CastResult.INTERRUPTED

            # Read on every frame, so the window can be moved or resized while fishing.
            region = self._window.capture_region()
            if region is None:
                # The system could not say where the window is. That can last a moment while the game
                # is still in front, so skip this look rather than give up the cast. Nothing is sent
                # without a successful look.
                self._sleep(frame_interval)
                continue

            position = self._vision.find_splash(region)
            if self._screen_is_blank():
                return CastResult.INTERRUPTED

            ignored = getattr(getattr(self._vision, 'last', None), 'note', '')
            if ignored and not mentioned_ignored:
                self._log(f'Ignored something that looked like a splash: it was {ignored}.')
                mentioned_ignored = True

            if position is not None:
                spot = (position[0] - region['left'], position[1] - region['top'])
                if self._not_a_plausible_catch(self._clock() - cast_started, spot):
                    return CastResult.INTERRUPTED
                return CastResult.LOOTED if self._loot(*position) else CastResult.INTERRUPTED

            # Looking a few times a second is enough to catch the splash and leaves the CPU mostly idle.
            self._sleep(frame_interval - (self._clock() - frame_started))

        return CastResult.MISSED

    # Right click on the bobber to loot the fish, player must enable automatic looting
    def _loot(self, x, y):
        self._sleep(random.random())
        if not self._can_act() or self._user_took_the_mouse():
            return False
        self._controls.moveTo(x, y, random.uniform(0.1, 0.3))
        self._expect_pointer_at(x, y)

        self._sleep(random.random())
        if not self._can_act() or self._user_took_the_mouse():
            return False
        self._record_click(x, y, practice=False)
        # Click at the splash itself rather than wherever the pointer is.
        self._controls.click(x=x, y=y, button='right')
        self._expect_pointer_at(x, y)

        self.stats.looted += 1
        self.stats.misses_in_a_row = 0
        self._log(f'Splash at x: {x}, y: {y} - looted ({self.stats.looted} this session).')
        return True
