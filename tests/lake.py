"""A moving fishing scene made from the one real game screenshot, for testing bite detection by movement.

``Lake`` gives the picture of the game at any moment: rippling water, a bobber that lands a little
after the cast, floats with a slight bob and its fishing line, and dips with a spray of water when
a fish bites. It can add things that must not be taken for a bite: another angler's bobber and
splash elsewhere, something walking by, a flash that brightens the whole picture, and the bobber
of the previous cast still floating when the new cast is made.

The bobber and the water are cut from ``example.png``. The movement is made up: nobody has
measured the real game's. It is here so that the detector's mechanics can be tested and its
margins seen, not as proof that it works in the game.
"""
import math

import cv2
import numpy as np

from tests.conftest import ROOT

# Where things are in example.png (1918 x 1080).
BOBBER_BOX = (1058, 606, 1170, 690)     # left, top, right, bottom
LINE_TOP = (1032, 0)                    # the fishing line runs from here to the bobber
LINE_END = (1127, 640)
HORIZON = 486                           # water is below this row
LANDS_AFTER_SEC = 1.3
SPLASH_LASTS_SEC = 0.9


def _smooth_noise(random, height, width, grain):
    noise = random.standard_normal((height // grain + 2, width // grain + 2)).astype(np.float32)
    noise = cv2.resize(noise, (width, height), interpolation=cv2.INTER_CUBIC)
    return noise / (np.abs(noise).max() or 1.0)


class Lake:
    def __init__(self, seed=1, size=(1918, 1080), ripple=5.0):
        self.random = np.random.default_rng(seed)
        picture = cv2.imread(str(ROOT / 'example.png'))
        left, top, right, bottom = BOBBER_BOX

        # The scene without a bobber or a line: paint both out.
        mask = np.zeros(picture.shape[:2], dtype=np.uint8)
        mask[top:bottom, left:right] = 255
        cv2.line(mask, LINE_TOP, LINE_END, 255, 7)
        empty = cv2.inpaint(picture, mask, 5, cv2.INPAINT_TELEA)

        # The bobber as a cut-out: opaque where it differs from the water painted in behind it.
        cut = picture[top:bottom, left:right].astype(np.float32)
        behind = empty[top:bottom, left:right].astype(np.float32)
        alpha = np.clip(np.abs(cut - behind).max(axis=2) / 28.0, 0, 1)
        self._alpha = cv2.GaussianBlur(alpha, (3, 3), 0)[:, :, None]
        self._bobber = cut
        self._home = ((left + right) // 2, (top + bottom) // 2)

        self.native = (picture.shape[1], picture.shape[0])
        self.size = size
        self._empty = empty.astype(np.float32)
        self._ripple = ripple
        height, width = picture.shape[:2]
        self._swell = [_smooth_noise(self.random, height, width * 2, 40) for _ in range(2)]
        self._glint = _smooth_noise(self.random, height, width * 2, 6)
        water = np.zeros((height, width), dtype=np.float32)
        water[HORIZON:] = 1.0
        self._water = cv2.GaussianBlur(water, (1, 31), 0)[:, :, None]   # ripples fade in below the horizon

        self.cast_at = None
        self.spot = self._home
        self.bite_at = None
        self.dips_under = False         # during a bite the bobber goes right under, out of sight
        self.pulled_in_at = None        # the time the bobber is pulled in with no fish
        self.fades_over = 0.0           # how long it takes to disappear then (0 is at once)
        self.old_bobber = None          # (x, y) of the last cast's bobber, gone at the new cast
        self.other_angler = None        # (x, y, lands at, splashes at), in seconds on the clock
        self.walker_from = None         # the time something starts crossing the shore
        self.flash_at = None            # the time the whole picture brightens for a moment

    # ----- the story -----

    def cast(self, now, spot=None, bite_after=9.0):
        """Cast at ``now``. The bobber lands at ``spot`` (native pixels) and a fish bites ``bite_after`` later."""
        self.cast_at = now
        self.spot = spot or self._home
        self.bite_at = None if bite_after is None else now + bite_after
        self.pulled_in_at = None

    def random_spot(self):
        return (int(self.random.integers(700, 1500)), int(self.random.integers(600, 880)))

    # ----- the picture -----

    def _draw_bobber(self, frame, spot, lift=0, with_line=True):
        height, width = self._bobber.shape[:2]
        x, y = spot[0] - width // 2, spot[1] - height // 2 + lift
        if x < 0 or y < 0 or x + width > frame.shape[1] or y + height > frame.shape[0]:
            return
        if with_line:
            end = (spot[0] + LINE_END[0] - self._home[0], spot[1] + LINE_END[1] - self._home[1] + lift)
            top = (spot[0] + LINE_TOP[0] - self._home[0], 0)
            cv2.line(frame, top, end, (232, 232, 236), 2, cv2.LINE_AA)
        area = frame[y:y + height, x:x + width]
        area[:] = area * (1 - self._alpha) + self._bobber * self._alpha

    def _draw_splash(self, frame, spot, progress):
        """Spray around the bobber: bright drops flying out and falling, different in every picture."""
        strength = math.sin(math.pi * min(1.0, progress)) ** 0.5
        # Only the area around the bobber is touched, so this stays quick.
        left, top = max(0, spot[0] - 130), max(0, spot[1] - 110)
        area = frame[top:spot[1] + 80, left:spot[0] + 130]
        x, y = spot[0] - left, spot[1] - top
        for _ in range(26):
            angle = self.random.uniform(-math.pi, 0)                  # upwards and sideways
            reach = self.random.uniform(18, 70) * (0.5 + progress)
            center = (int(x + math.cos(angle) * reach), int(y + 6 + math.sin(angle) * reach * 0.7))
            drop = area.copy()
            cv2.ellipse(drop, center, (int(self.random.integers(3, 9)), int(self.random.integers(3, 8))), 0, 0, 360,
                        (238, 236, 232), -1, cv2.LINE_AA)
            cv2.addWeighted(drop, 0.55 * strength, area, 1 - 0.55 * strength, 0, dst=area)
        ring = area.copy()
        cv2.ellipse(ring, (x, y + 22), (int(30 + 55 * progress), int(9 + 14 * progress)), 0, 0, 360,
                    (226, 226, 224), 3, cv2.LINE_AA)
        cv2.addWeighted(ring, 0.5 * strength, area, 1 - 0.5 * strength, 0, dst=area)

    def frame(self, now):
        """The picture of the game at ``now`` seconds, as BGR bytes at ``size``."""
        height, width = self._empty.shape[:2]
        shift = int(now * 37) % width
        swell = self._swell[0][:, shift:shift + width] + self._swell[1][:, (width - shift // 2) % width:][:, :width]
        glint = self._glint[:, (shift * 3) % width:][:, :width]
        ripple = (swell * 0.7 + glint * 0.5) * self._ripple
        frame = self._empty + ripple[:, :, None] * self._water

        if self.flash_at is not None and 0 <= now - self.flash_at < 0.35:
            frame = frame + 22.0

        if self.walker_from is not None and 0 <= now - self.walker_from < 6:
            x = int(80 + (now - self.walker_from) * 150)
            cv2.rectangle(frame, (x, 380), (x + 26, 440), (40, 46, 60), -1)

        if self.old_bobber is not None and (self.cast_at is None or now < self.cast_at):
            self._draw_bobber(frame, self.old_bobber, lift=round(2 * math.sin(now * 3.9)))

        if self.other_angler is not None:
            x, y, lands, splashes = self.other_angler
            if now >= lands:
                biting = 0 <= now - splashes < SPLASH_LASTS_SEC
                self._draw_bobber(frame, (x, y), lift=9 if biting else round(2 * math.sin(now * 4.1 + 1)))
                if biting:
                    self._draw_splash(frame, (x, y), (now - splashes) / SPLASH_LASTS_SEC)

        if self.cast_at is not None and now - self.cast_at >= LANDS_AFTER_SEC:
            biting = self.bite_at is not None and 0 <= now - self.bite_at < SPLASH_LASTS_SEC
            fading = 0.0 if self.pulled_in_at is None or now < self.pulled_in_at else (
                1.0 if self.fades_over <= 0 else min(1.0, (now - self.pulled_in_at) / self.fades_over))
            if fading < 1.0 and not (biting and self.dips_under):
                without = frame.copy() if fading > 0 else None
                self._draw_bobber(frame, self.spot, lift=10 if biting else round(2 * math.sin(now * 3.9)))
                if without is not None:
                    frame[:] = without * fading + frame * (1 - fading)
            if biting:
                self._draw_splash(frame, self.spot, (now - self.bite_at) / SPLASH_LASTS_SEC)

        frame = np.clip(frame, 0, 255).astype(np.uint8)
        if self.size != self.native:
            frame = cv2.resize(frame, self.size, interpolation=cv2.INTER_AREA)
        return frame

    def on_screen(self, spot):
        """A native position as it appears at ``size``."""
        return (spot[0] * self.size[0] / self.native[0], spot[1] * self.size[1] / self.native[1])
