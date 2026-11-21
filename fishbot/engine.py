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
# Before the first cast, and after a wait or a pause, the mouse has to be left alone for this long.
STILL_BEFORE_START_SEC = 0.7
# If that takes longer than this, say what the bot is waiting for.
MENTION_MOUSE_AFTER_SEC = 2.0
# The pointer moving further than this, when the bot did not move it, means the user took the mouse.
POINTER_MOVED_PX = 8
# After the bot pauses itself, a press of the pause key within this time means "pause", not "resume".
KEEP_OWN_PAUSE_SEC = 5.0
# A bite this soon after casting, this many times running, is not fishing: something on screen
# keeps looking like a splash.
TOO_FAST_SEC = 2.0
TOO_FAST_STREAK = 3
# The bobber lands somewhere new on every cast, while something that does not move is seen on the
# same pixels again and again. This many of the last few catches on one spot stop the bot. The
# spot is as wide as a detection wobbles: a share of the window, with a floor for small windows.
SAME_SPOT_COUNT = 4
CATCHES_REMEMBERED = 8
SAME_SPOT_SHARE = 0.004
SAME_SPOT_MIN_PX = 6
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


def _far_apart(a, b, distance):
    return abs(a[0] - b[0]) > distance or abs(a[1] - b[1]) > distance


class FishingBot:
    """Runs the fishing loop until stopped.

    Keys and clicks are only sent while the game window is in the foreground, so switching to
    another application makes the bot wait instead of typing into it. ``stop``, ``set_paused``
    and ``toggle_pause`` may be called from other threads (the hotkeys and the interface).

    ``on_click(x, y, practice)`` is called right after each right-click (or, in practice mode,
    instead of it), so the caller can keep a record of what was clicked.
    """

    def __init__(self, settings, window, vision, controls, clock=time.monotonic, idle=time.sleep, log=print,
                 on_click=None, practice=False):
        self._settings = settings
        self._practice = practice  # watch only: nothing is pressed or clicked
        self._window = window
        self._vision = vision
        self._controls = controls
        self._clock = clock
        self._idle = idle
        self._log = log
        self._on_click = on_click
        self._stop = threading.Event()
        self._stop_lock = threading.Lock()
        self._paused = threading.Event()
        self._paused_itself_at = None
        self._last_lure = None
        self._started = None
        self._pointer = None            # where the pointer has to be: where the bot left it
        self._mouse_must_settle = True  # before the first cast, and again after every wait or pause
        self._settling_at = None
        self._settling_since = None
        self._cast_times = collections.deque()
        self._fast_in_a_row = 0
        self._spots = collections.deque(maxlen=CATCHES_REMEMBERED)
        self.stats = Stats()
        self.state = WAITING
        self.waiting_for = 'game'  # while WAITING: 'game' (not the window in front) or 'mouse' (not still yet)
        self.stop_reason = ''
        self.stopped_by_safeguard = False

    # ----- control from outside -----

    def stop(self, reason='Stopped.', safeguard=False):
        """Stop for good. The first reason given is the one that is kept."""
        with self._stop_lock:
            if not self._stop.is_set():
                self.stop_reason = reason
                self.stopped_by_safeguard = safeguard
                self._stop.set()

    def set_paused(self, paused, message=None):
        if paused == self._paused.is_set():
            return
        # Whichever way this goes, the next cast waits for the mouse to be left alone again.
        self._require_still_mouse()
        if paused:
            self._paused.set()
            self._log(message or 'Paused.')
        else:
            self._paused_itself_at = None
            self._paused.clear()
            self._log('Resumed.')

    def toggle_pause(self):
        """The pause key. Right after the bot paused itself, a press means "pause", so it stays paused."""
        paused_itself = self._paused_itself_at
        if (self._paused.is_set() and paused_itself is not None
                and self._clock() - paused_itself < KEEP_OWN_PAUSE_SEC):
            self._paused_itself_at = None
            self._log('Still paused. Press the pause key again to resume.')
            return
        self.set_paused(not self._paused.is_set())

    @property
    def paused(self):
        return self._paused.is_set()

    def elapsed_seconds(self):
        return 0 if self._started is None else self._clock() - self._started

    # ----- the loops -----

    def run(self):
        self._started = self._clock()

        try:
            if self._practice:
                # Nothing at all is sent in practice, not even the request to bring the game forward.
                self._watch_only()
            else:
                if not self._stop.is_set():
                    self._window.focus()
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
                self._fast_in_a_row = 0
                self._log('No bite on that cast.')

            self._sleep(random.randrange(0, 3))

    def _watch_only(self):
        """Practice mode: look for the splash and say what would be clicked, without any input."""
        self._log('Practice: watching only. Cast in the game yourself. Nothing is pressed or clicked.')
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
                self._log(f'Practice: it would have clicked the bobber now ({self.stats.practice_clicks} so far).')
                self._sleep(PRACTICE_PAUSE_SEC)

            self._sleep(frame_interval - (self._clock() - frame_started))

    # ----- safeguards -----

    def _trip(self, reason):
        """Stop because something does not look right. The bot never tries to fix it with more input."""
        self.stop(reason, safeguard=True)

    def _limit_reached(self):
        minutes = self._settings.stop_after_minutes
        if minutes and self.elapsed_seconds() >= minutes * 60:
            self.stop(f'Stopped: your {minutes} minute limit is up.')
            return True

        catches = self._settings.stop_after_catches
        if catches and self.stats.looted >= catches:
            self.stop(f'Stopped: you reached your limit of {catches} catch{"" if catches == 1 else "es"}.')
            return True

        misses = self._settings.stop_after_misses
        if misses and self.stats.misses_in_a_row >= misses:
            what = 'no bite on the last cast' if misses == 1 else f'no bite in {misses} casts in a row'
            self._trip(f'Stopped: {what}. Check that the fishing key is right, '
                       'and that the game is zoomed all the way in with the buttons and bars hidden.')
            return True

        return False

    def _recasting_too_often(self):
        """Checked before the key is pressed: would this cast be one too many in a short time?"""
        now = self._clock()
        while self._cast_times and now - self._cast_times[0] > CAST_BURST_SEC:
            self._cast_times.popleft()

        if len(self._cast_times) >= CAST_BURST_COUNT:
            self._trip('Stopped: casting kept getting interrupted, so it stopped pressing the key. '
                       'Check that nothing in the game is in the way.')
            return True
        return False

    def _screen_is_blank(self):
        if getattr(self._vision, 'blank_streak', 0) >= BLANK_LOOKS:
            self._trip('Stopped: the game screen went black. That is usually a loading screen or a disconnect.')
            return True
        return False

    def _not_a_plausible_catch(self, seconds_since_cast, spot, window_width):
        """Judge a sighting against the recent ones before clicking it. Trips the bot if they look wrong."""
        self._fast_in_a_row = self._fast_in_a_row + 1 if seconds_since_cast < TOO_FAST_SEC else 0
        if self._fast_in_a_row >= TOO_FAST_STREAK:
            self._trip('Stopped: it kept seeing a bite the moment it cast, which a real fish never does. '
                       'Something else on screen is fooling it. "What it clicked" shows what.')
            return True

        # Real catches in between do not hide a spot that keeps coming back, so this looks at the
        # last few catches together rather than at an unbroken run.
        tolerance = max(SAME_SPOT_MIN_PX, SAME_SPOT_SHARE * window_width)
        self._spots.append(spot)
        here = sum(1 for earlier in self._spots if not _far_apart(earlier, spot, tolerance))
        if here >= SAME_SPOT_COUNT:
            self._trip('Stopped: it kept clicking the very same spot, and a bobber never lands twice in the same place. '
                       'Something else on screen is fooling it. "What it clicked" shows what.')
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
        if now is None or self._pointer is None or not _far_apart(now, self._pointer, POINTER_MOVED_PX):
            return False

        self._paused_itself_at = self._clock()
        self.set_paused(True, 'Paused because you moved the mouse. Press Resume when you are ready.')
        return True

    def _require_still_mouse(self):
        self._mouse_must_settle = True
        self._settling_since = None

    def _mouse_has_settled(self):
        """True once the mouse has been left alone for a moment. Always true if the check is off."""
        now = self._pointer_now()
        if now is None or not self._mouse_must_settle:
            return True

        if self._settling_since is None or _far_apart(now, self._settling_at, POINTER_MOVED_PX):
            self._settling_at = now
            self._settling_since = self._clock()
            return False
        if self._clock() - self._settling_since < STILL_BEFORE_START_SEC:
            return False

        self._pointer = now
        self._mouse_must_settle = False
        return True

    def _window_moved(self, region):
        """Whether the game window is no longer where it was when the splash was seen there."""
        if self._window.capture_region() == region:
            return False
        self._log('The game window moved, so that click was skipped.')
        return True

    def _record_click(self, x, y, practice):
        if self._on_click is None:
            return
        try:
            self._on_click(x, y, practice)
        except Exception as error:  # keeping a record must never get in the way of fishing or stopping
            self._log(f'Could not save a picture of that click ({error}).')

    # ----- waiting and acting -----

    def _wait_until_ready(self):
        """Block until input may be sent. Returns False once the bot should shut down."""
        announced = False
        practice = self._practice
        waiting_for_mouse_since = None

        while not self._stop.is_set():
            if not self._window.exists():
                self.stop('Stopped: the game was closed.')
                return False

            if self._paused.is_set():
                self.state = PAUSED
                waiting_for_mouse_since = None
            elif self._window.is_foreground() and self._window.capture_region() is not None:
                # In practice mode the user is playing, so the mouse is theirs throughout.
                if practice or self._mouse_has_settled():
                    self.state = PRACTICE if practice else FISHING
                    return True
                self.state, self.waiting_for = WAITING, 'mouse'
                if waiting_for_mouse_since is None:
                    waiting_for_mouse_since = self._clock()
                elif waiting_for_mouse_since is not False and self._clock() - waiting_for_mouse_since >= MENTION_MOUSE_AFTER_SEC:
                    self._log('Waiting for you to let go of the mouse.')
                    waiting_for_mouse_since = False  # said once
            else:
                self.state, self.waiting_for = WAITING, 'game'
                self._require_still_mouse()
                waiting_for_mouse_since = None
                if not announced:
                    self._log('Waiting for the game to be the window in front. Nothing is pressed until it is.')
                    announced = True

            self._idle(POLL_INTERVAL_SEC)

        return False

    def _can_act(self):
        # The slow question first and the flags last: a stop or pause that arrives while the system
        # is being asked about the window is then still seen.
        in_front = self._window.is_foreground()
        return in_front and not self._stop.is_set() and not self._paused.is_set()

    def _press(self, key):
        if self._user_took_the_mouse() or not self._can_act():
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
            self._log(f'Put on a lure. The next one is due in {settings.lure_minutes} minutes.')
            self._sleep(LURE_APPLY_WAIT_SEC)

    def _cast(self):
        if self._recasting_too_often() or not self._press(self._settings.fishing_key):
            return CastResult.INTERRUPTED

        cast_started = self._clock()
        self._cast_times.append(cast_started)
        self.stats.casts += 1
        self._log(f'Cast {self.stats.casts}. Waiting for a bite...')

        frame_interval = 1 / self._settings.checks_per_second
        deadline = cast_started + self._settings.cast_seconds
        mentioned_ignored = False
        self._sleep(SETTLE_AFTER_CAST_SEC)

        while self._clock() < deadline:
            frame_started = self._clock()
            if self._user_took_the_mouse() or not self._can_act():
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
                self._log(f'Ignored something that looked like a bite ({ignored}).')
                mentioned_ignored = True

            if position is not None:
                spot = (position[0] - region['left'], position[1] - region['top'])
                if self._not_a_plausible_catch(self._clock() - cast_started, spot, region['width']):
                    return CastResult.INTERRUPTED
                return CastResult.LOOTED if self._loot(position[0], position[1], region) else CastResult.INTERRUPTED

            # Looking a few times a second is enough to catch the splash and leaves the CPU mostly idle.
            self._sleep(frame_interval - (self._clock() - frame_started))

        return CastResult.MISSED

    # Right click on the bobber to loot the fish, player must enable automatic looting
    def _loot(self, x, y, region):
        self._sleep(random.random())
        if self._window_moved(region) or self._user_took_the_mouse() or not self._can_act():
            return False
        self._controls.moveTo(x, y, random.uniform(0.1, 0.3))
        self._expect_pointer_at(x, y)

        self._sleep(random.random())
        # The last look before the click, slowest question first: is the window still where the
        # splash was seen, is the mouse still where the bot left it, and has nobody stopped or paused.
        if self._window_moved(region) or self._user_took_the_mouse() or not self._can_act():
            return False
        # Click at the splash itself rather than wherever the pointer is.
        self._controls.click(x=x, y=y, button='right')
        self._expect_pointer_at(x, y)

        self.stats.looted += 1
        self.stats.misses_in_a_row = 0
        self._log(f'Got a bite and clicked the bobber ({self.stats.looted} so far).')
        self._record_click(x, y, practice=False)
        return True
