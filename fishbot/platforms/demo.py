"""A simulated game, for trying the interface and for tests: python bot.py --demo

Nothing here touches the real keyboard, mouse or screen. The "game" is two pictures: a calm
bobber, and a synthetic image made to trigger the detector (it is not a real screenshot). The
real detector runs on them, so everything except the operating-system calls is exercised.
"""
import random
import time
from pathlib import Path

import cv2

SYSTEM = 'demo'
LABEL = 'Demo (simulated game)'
SETUP_NOTES = ['Demo mode: no keys or clicks are sent and the screen is not captured.']

ASSETS = Path(__file__).resolve().parent.parent / 'assets'
REGION = {'left': 0, 'top': 0, 'width': 640, 'height': 360}


class DemoGame:
    """Shared state: when the fishing key is pressed, a fish bites a few seconds later."""

    def __init__(self, bite_after=(3.0, 7.0), clock=time.monotonic):
        self.calm = cv2.imread(str(ASSETS / 'demo_calm.jpg'))
        self.splash = cv2.imread(str(ASSETS / 'demo_splash.png'))
        self.bite_after = bite_after
        self.clock = clock
        self.bite_at = None
        self.events = []

    def cast(self):
        self.bite_at = self.clock() + random.uniform(*self.bite_after)

    def loot(self):
        self.bite_at = None

    def frame(self):
        biting = self.bite_at is not None and self.clock() >= self.bite_at
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

    def click(self, x=None, y=None, button='left'):
        self._game.events.append(('click', button, x, y))
        self._game.loot()


class DemoGrabber:
    def __init__(self, game):
        self._game = game

    def grab(self, region):
        frame = self._game.frame()
        return frame[region['top']:region['top'] + region['height'],
                     region['left']:region['left'] + region['width']].copy()


GAME = DemoGame()


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
