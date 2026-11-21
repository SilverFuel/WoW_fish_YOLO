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
SETUP_NOTES = ['Demo mode: no keys or clicks are sent and the screen is not captured.']

ASSETS = Path(__file__).resolve().parent.parent / 'assets'
REGION = {'left': 0, 'top': 0, 'width': 640, 'height': 360}


SPLASH_AT = (344, 248)  # where the synthetic splash sits in the unshifted picture
# How far the view moves between casts, in pixels. Upwards only, so the splash stays inside the smallest scan area.
SHIFT_X, SHIFT_Y = (-48, 48), (-40, 0)
MIN_STEP = 16           # a new cast never lands this close to the last few
SPLASH_LASTS_SEC = 2.5
PLAYER_CASTS_AFTER_SEC = 5.0  # with nobody casting, the simulated player does (for practice mode)


class DemoGame:
    """Shared state: when the fishing key is pressed, a fish bites a few seconds later.

    Like the real game, every cast lands the bobber somewhere slightly different: the whole
    picture is shifted by a new amount for each cast.
    """

    def __init__(self, bite_after=(3.0, 7.0), clock=time.monotonic, player_casts=False):
        self.player_casts = player_casts
        self._idle_since = clock()
        self._calm = cv2.imread(str(ASSETS / 'demo_calm.jpg'))
        self._splash = cv2.imread(str(ASSETS / 'demo_splash.png'))
        self.bite_after = bite_after
        self.clock = clock
        self.bite_at = None
        self.events = []
        self.pointer = (10, 10)
        self._shifts = [(0, 0)]
        self.landings = []  # where the splash was for each cast, in order
        self._move_view(0, 0)

    def _move_view(self, shift_x, shift_y):
        move = np.float32([[1, 0, shift_x], [0, 1, shift_y]])
        size = (REGION['width'], REGION['height'])
        self.calm = cv2.warpAffine(self._calm, move, size, borderMode=cv2.BORDER_REPLICATE)
        self.splash = cv2.warpAffine(self._splash, move, size, borderMode=cv2.BORDER_REPLICATE)
        self.splash_position = (SPLASH_AT[0] + shift_x, SPLASH_AT[1] + shift_y)

    def cast(self):
        while True:
            shift = (random.randint(*SHIFT_X), random.randint(*SHIFT_Y))
            if all(abs(shift[0] - old[0]) >= MIN_STEP for old in self._shifts[-3:]):
                break
        self._shifts.append(shift)
        self._move_view(*shift)
        self.landings.append(self.splash_position)
        self.bite_at = self.clock() + random.uniform(*self.bite_after)

    def loot(self):
        self.bite_at = None
        self._idle_since = self.clock()

    def frame(self):
        now = self.clock()
        if self.bite_at is not None and now >= self.bite_at + SPLASH_LASTS_SEC:
            self.loot()  # nobody took it and the splash is over
        if self.bite_at is None and self.player_casts and now - self._idle_since >= PLAYER_CASTS_AFTER_SEC:
            self.cast()
        biting = self.bite_at is not None and now >= self.bite_at
        return self.splash if biting else self.calm


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


def key_is_down(name):
    return False


def permission_problems():
    return []


def create_controls():
    return DemoControls(GAME)


def create_grabber():
    return DemoGrabber(GAME)
