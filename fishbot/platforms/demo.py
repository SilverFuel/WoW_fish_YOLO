"""A simulated game, for trying the interface and for tests: python bot.py --demo

Nothing here touches the real keyboard, mouse or screen. The "game" is two pictures: a calm
bobber, and a synthetic image made to trigger the detector (it is not a real screenshot). The
real detector runs on them, so everything except the operating-system calls is exercised.
"""
import random
import time
from pathlib import Path

import cv2
import numpy as np

SYSTEM = 'demo'
LABEL = 'Demo (simulated game)'
SETUP_NOTES = []

ASSETS = Path(__file__).resolve().parent.parent / 'assets'
REGION = {'left': 0, 'top': 0, 'width': 640, 'height': 360}


SPLASH_AT = (344, 248)  # where the synthetic splash sits in the shipped picture
# How far from there a cast may land, in pixels. Upwards only, so it stays inside the smallest scan area.
SHIFT_X, SHIFT_Y = (-48, 48), (-40, 0)
MIN_STEP = 16           # a new cast never lands this close to the last few
LANDS_AFTER_SEC = 1.2   # the bobber is in the air until then
CAST_LASTS_SEC = 8.0    # with no fish coming, the bobber is pulled in after this long
SPLASH_LASTS_SEC = 2.5
SPLASH_HALF = 40        # the synthetic splash is cut out as a square this far each way
PLAYER_CASTS_AFTER_SEC = 5.0  # with nobody casting, the simulated player does (for practice mode)


class DemoGame:
    """Shared state: when the fishing key is pressed, a bobber lands and a fish bites a few seconds later.

    Like the real game, every cast lands the bobber somewhere slightly different, and the view
    itself stays put. While the fish bites, the synthetic splash is shown at the bobber and
    shivers a little, so both ways of spotting a bite have something to see: its look and its movement.
    """

    def __init__(self, bite_after=(3.0, 7.0), clock=time.monotonic, player_casts=False):
        self.player_casts = player_casts
        self._idle_since = clock()
        self.calm = cv2.imread(str(ASSETS / 'demo_calm.jpg'))
        splash = cv2.imread(str(ASSETS / 'demo_splash.png'))
        x, y = SPLASH_AT
        self._splash = splash[y - SPLASH_HALF:y + SPLASH_HALF, x - SPLASH_HALF:x + SPLASH_HALF].copy()
        self.bite_after = bite_after
        self.clock = clock
        self.cast_at = None
        self.bite_at = None
        self.events = []
        self.pointer = (10, 10)
        self._shifts = [(0, 0)]
        self.splash_position = SPLASH_AT
        self.landings = []  # where the bobber landed for each cast, in order
        self._shiver = 0

    def cast(self):
        while True:
            shift = (random.randint(*SHIFT_X), random.randint(*SHIFT_Y))
            if all(abs(shift[0] - old[0]) >= MIN_STEP for old in self._shifts[-3:]):
                break
        self._shifts.append(shift)
        self.splash_position = (SPLASH_AT[0] + shift[0], SPLASH_AT[1] + shift[1])
        self.landings.append(self.splash_position)
        self.cast_at = self.clock()
        self.bite_at = self.cast_at + random.uniform(*self.bite_after)

    def loot(self):
        self.cast_at = None
        self.bite_at = None
        self._idle_since = self.clock()

    def frame(self):
        now = self.clock()
        if self.bite_at is not None and now >= self.bite_at + SPLASH_LASTS_SEC:
            self.loot()  # nobody took it and the splash is over
        if self.cast_at is not None and now >= self.cast_at + CAST_LASTS_SEC and now < self.bite_at:
            self.loot()  # no fish came, and the cast is over
        if self.cast_at is None and self.player_casts and now - self._idle_since >= PLAYER_CASTS_AFTER_SEC:
            self.cast()
        if self.cast_at is None or now - self.cast_at < LANDS_AFTER_SEC:
            return self.calm

        picture = self.calm.copy()
        x, y = self.splash_position
        if now >= self.bite_at:
            self._shiver = (self._shiver + 1) % 3
            x, y = x + (0, 2, -2)[self._shiver], y + (0, 1, -1)[self._shiver]
            picture[y - SPLASH_HALF:y + SPLASH_HALF, x - SPLASH_HALF:x + SPLASH_HALF] = self._splash
        else:
            # A plain little bobber: a red feather over a cork.
            cv2.ellipse(picture, (x - 4, y - 3), (8, 3), -20, 0, 360, (40, 50, 190), -1, cv2.LINE_AA)
            cv2.ellipse(picture, (x + 2, y + 3), (5, 4), 0, 0, 360, (150, 190, 215), -1, cv2.LINE_AA)
        return picture


class DemoWindow:
    def exists(self):
        return True

    def is_foreground(self):
        return True

    def focus(self):
        pass

    def capture_region(self):
        return dict(REGION)


class DemoControls:
    def __init__(self, game):
        self._game = game

    def press(self, key):
        self._game.events.append(('press', key))
        self._game.cast()

    def moveTo(self, x, y, duration=0):
        self._game.events.append(('move', x, y))
        self._game.pointer = (x, y)

    def click(self, x=None, y=None, button='left'):
        if x is not None and y is not None:
            self._game.pointer = (x, y)
        self._game.events.append(('click', button, x, y))
        self._game.loot()

    def position(self):
        return self._game.pointer


class DemoGrabber:
    def __init__(self, game):
        self._game = game

    def grab(self, region):
        frame = self._game.frame()
        return frame[region['top']:region['top'] + region['height'],
                     region['left']:region['left'] + region['width']].copy()


GAME = DemoGame(player_casts=True)


def find_game_window():
    return DemoWindow()


def facts():
    return ['Pretend game: no real screen or game window is used.']


def front_window():
    return None  # the pretend game never takes the front, so there is nothing to hand back


def bring_to_front(window):
    pass


def key_is_down(name):
    return False


def permission_problems():
    return []


def create_controls():
    return DemoControls(GAME)


def create_grabber():
    return DemoGrabber(GAME)
