"""Spot a bite by movement, without knowing what a splash looks like.

Just after a cast, the bobber is the one thing in the picture that was not there just before.
``BobberWatcher`` finds it that way: what differs from the pictures taken before the cast, and keeps
differing. From then on it watches that one spot. Floating, the bobber hardly moves. When a fish
bites it dips and water sprays, which shows as a short, strong burst of change there and nowhere
else. That burst is the bite.

Nothing here has learnt the look of a bobber, a splash or the water, so it does not depend on the
version of the game the way the trained model does. It has been built against a simulation made
from one real screenshot (tests/lake.py), not against the game.
"""
from __future__ import annotations

import collections
from dataclasses import dataclass

import cv2
import numpy as np

WORK_WIDTH = 400              # pictures are shrunk to this width: a bobber is still ~20 wide, and fine noise is gone
REFERENCE_PICTURES = 4        # how many pictures from before the cast are averaged into "the water without a bobber"
LOOK_FOR_BOBBER_FROM_SEC = 1.0
GIVE_UP_LOOKING_SEC = 7.0
PERSISTS_OVER = 3             # a difference has to be there in this many pictures in a row to count as a thing
BOBBER_SPAN = 0.0325          # roughly a bobber's width, as a share of the picture's width
EDGE_MARGIN = 0.05            # the bobber does not land at the very edge
MIN_DIFFERENCE = 8.0          # levels (of 255): fainter than this is not a bobber
STANDS_OUT_BY = 1.8           # times the strongest lasting difference anywhere else (ripples, the fishing line)
THING_STANDS_OUT = 4.0        # levels by which a spot has to differ from the water around it to be a thing
THING_SHARE_OF_BEFORE = 0.35  # and this share of how much it stood out before the cast, if something was there then
WATCH_SPAN = 0.07             # half the side of the watched square around the bobber, as a share of the width
CALM_LOOKS = 4                # looks at the floating bobber before a burst can be judged
# A bite is a burst of movement at the bobber. Against how much the spot moves while the bobber floats:
BURST_RISE = 6.0              # it rises by at least this much (levels, mean of the busiest fifth of the spot),
BURST_RISE_SPREADS = 5.0      # and by this many times the usual variation of the floating movement,
BURST_TIMES_CALM = 2.0        # to at least this many times the floating movement,
BURST_OVER_ELSEWHERE = 2.0    # and this many times what the rest of the picture did in the same instant.
BURST_LOOKS = 2               # A bite lasts: this many looks in a row,
STRONG_BURST = 2.5            # or one look this many times over what is needed.
STILL_OUT_SHARE = 0.4         # the bobber is still there while the spot differs from "no bobber" by this share of what it did
CLEARLY_THERE_SHARE = 0.8     # for a bite called on a single look, it must be this much: a bobber being pulled in fades
GONE_LOOKS = 2                # looks in a row without it, and the cast is over


@dataclass(frozen=True)
class Movement:
    """What the watcher makes of one look."""
    phase: str               # 'early', 'looking' (for the bobber), 'watching' (it), 'gone' (it was pulled in: the cast
                             # is over), or 'lost' (never found it)
    bobber: tuple | None     # (x, y) of the bobber in the picture's own pixels, once found
    box: tuple | None        # the watched square (x1, y1, x2, y2) in the picture's own pixels
    strength: float          # the movement at the bobber as a share of what counts as a bite: 1.0 is just enough
    bite: bool               # the burst that means a fish is on
    still_out: bool          # the bobber is still where it was found


NOTHING_YET = Movement('early', None, None, 0.0, False, False)


def _small(frame):
    """The picture shrunk and split into brightness and colour (red minus blue), as one two-layer array.

    Ripples and glints change the water's brightness and hardly its colour. A bobber is a red and
    tan thing on blue water, so it shows in both. Using both keeps it apart from rough water.
    """
    height, width = frame.shape[:2]
    scale = min(1.0, WORK_WIDTH / width)
    if scale < 1.0:
        frame = cv2.resize(frame, (WORK_WIDTH, max(1, round(height * scale))), interpolation=cv2.INTER_AREA)
    blurred = cv2.GaussianBlur(frame, (3, 3), 0).astype(np.float32)
    brightness = blurred @ np.array([0.114, 0.587, 0.299], dtype=np.float32)
    colour = blurred[:, :, 2] - blurred[:, :, 0]
    return np.stack([brightness, colour]), scale


def _difference(a, b):
    """How much two shrunk pictures differ at each point: in brightness plus in colour."""
    return np.abs(a - b).sum(axis=0)


def _busiest(values):
    """How much the busiest part of an area changed: the mean of its top fifth."""
    flat = np.sort(values, axis=None)
    return float(flat[-max(1, flat.size // 5):].mean())


class BobberWatcher:
    def __init__(self):
        self._before = collections.deque(maxlen=REFERENCE_PICTURES)
        self._reset()

    def _reset(self):
        self._empty = None          # the water without a bobber
        self._recent = collections.deque(maxlen=PERSISTS_OVER)
        self._candidate = None
        self._bobber = None         # (x, y) in the small picture
        self._found_strength = 0.0
        self._previous = None
        self._calm = []
        self._bursts = 0
        self._missing = 0
        self._gone = False
        self._gave_up = False
        self._unconfirmed = 0.0
        self.peak_strength = 0.0    # the strongest movement seen at the bobber this cast, while it was still there

    # ----- the cast -----

    def before_cast(self, frame):
        """A picture from just before the cast. Several are averaged, which evens out the ripples."""
        small, _ = _small(frame)
        if self._before and self._before[-1].shape != small.shape:
            self._before.clear()   # the game window changed size
        self._before.append(small)

    def cast_started(self):
        self._reset()
        if self._before:
            self._empty = np.mean(np.stack(list(self._before)), axis=0)
        self._before.clear()

    @property
    def ready(self):
        """Whether there were pictures from before the cast to compare with."""
        return self._empty is not None

    @property
    def found(self):
        return self._bobber is not None

    @property
    def pulled_in(self):
        """Whether the bobber that was being watched has disappeared: the cast ended without a fish."""
        return self._gone or self._missing > 0

    # ----- each look -----

    def look(self, frame, seconds_since_cast):
        small, scale = _small(frame)
        if self._empty is None or small.shape != self._empty.shape:
            return NOTHING_YET
        if self._bobber is None:
            return self._look_for_bobber(small, scale, seconds_since_cast)
        return self._watch(small, scale)

    def _span(self, share, width):
        return max(3, int(round(share * width)))

    def _look_for_bobber(self, small, scale, seconds):
        if seconds < LOOK_FOR_BOBBER_FROM_SEC:
            return NOTHING_YET
        if self._gave_up or seconds > GIVE_UP_LOOKING_SEC:
            self._gave_up = True
            return Movement('lost', None, None, 0.0, False, False)

        self._recent.append(_difference(small, self._empty))
        self._previous = small
        if len(self._recent) < PERSISTS_OVER:
            return Movement('looking', None, None, 0.0, False, False)

        # Ripples differ from the empty water too, but not in the same place picture after picture.
        lasting = np.minimum.reduce(list(self._recent))
        height, width = lasting.shape
        span = self._span(BOBBER_SPAN, width) | 1  # odd, so the blur is centred
        blobs = cv2.blur(lasting, (span, span))
        margin_x, margin_y = int(EDGE_MARGIN * width), int(EDGE_MARGIN * height)
        inside = blobs[margin_y:height - margin_y, margin_x:width - margin_x]
        spot = self._strongest(inside, span, small, (margin_x, margin_y))
        if spot is None:
            self._candidate = None
            return Movement('looking', None, None, 0.0, False, False)
        spot = (spot[0] + margin_x, spot[1] + margin_y, spot[2])

        # It has to be in the same place twice running: the bobber is still flying when it first shows.
        settled = self._candidate is not None and abs(spot[0] - self._candidate[0]) <= span and abs(spot[1] - self._candidate[1]) <= span
        self._candidate = spot
        if not settled:
            return Movement('looking', None, None, 0.0, False, False)

        self._bobber = self._centre_on_thing(small, spot[0], spot[1], span)
        self._found_strength = self._unlike_empty_water(small)
        self._recent.clear()
        return self._result('watching', scale, small.shape, 0.0, False, True)

    def _strongest(self, blobs, span, small, margins):
        """The lasting difference that stands out from all the others, as (x, y, strength), or None.

        Something that vanished is a lasting difference as well: the previous cast's bobber, if it was
        still floating when this cast was made. So a spot only counts if there is a thing there now.
        """
        found = []
        work = blobs.copy()
        for _ in range(2):
            _, strength, _, (x, y) = cv2.minMaxLoc(work)
            found.append((x, y, float(strength)))
            cv2.circle(work, (x, y), span * 2, 0.0, -1)
        # What is left is ripples and the fishing line. A bobber is clearly more than any of it.
        needed = max(MIN_DIFFERENCE, STANDS_OUT_BY * float(np.percentile(work, 99.5)))
        for x, y, strength in found:
            if strength >= needed and self._appeared(small, x + margins[0], y + margins[1], span):
                return x, y, strength
        return None

    def _appeared(self, small, x, y, span):
        """Whether the difference at a spot is something that is there now, rather than something gone.

        Where a bobber vanished there is only water now. A new bobber that landed almost where the
        old one floated still counts: there is a thing there, even if a little to one side.
        """
        def stands_out(picture):
            spot = picture[:, max(0, y - span // 2):y + span // 2 + 1, max(0, x - span // 2):x + span // 2 + 1]
            around = picture[:, max(0, y - span * 2):y + span * 2 + 1, max(0, x - span * 2):x + span * 2 + 1]
            return float(np.abs(spot.mean(axis=(1, 2)) - np.median(around, axis=(1, 2))).sum())

        return stands_out(small) >= max(THING_STANDS_OUT, THING_SHARE_OF_BEFORE * stands_out(self._empty))

    def _centre_on_thing(self, small, x, y, span):
        """Move a found spot onto the middle of the thing that is there now."""
        height, width = small.shape[1:]
        x1, y1 = max(0, x - span * 2), max(0, y - span * 2)
        area = small[:, y1:min(height, y + span * 2 + 1), x1:min(width, x + span * 2 + 1)]
        unlike_water = np.abs(area - np.median(area, axis=(1, 2), keepdims=True)).sum(axis=0)
        _, _, _, (best_x, best_y) = cv2.minMaxLoc(cv2.blur(unlike_water, (span, span)))
        return x1 + best_x, y1 + best_y

    def _watched(self, shape):
        height, width = shape[-2:]
        half = self._span(WATCH_SPAN, width)
        x, y = self._bobber
        return max(0, x - half), max(0, y - half), min(width, x + half + 1), min(height, y + half + 1)

    def _unlike_empty_water(self, small):
        """How much the watched square differs from the water as it was before the cast.

        The whole square, not only the bobber's middle: during a bite the bobber dips out of sight
        and spray covers it, and the square is then more unlike empty water, not less. Only when
        the bobber has been pulled in does the square go back to looking like water.
        """
        x1, y1, x2, y2 = self._watched(small.shape)
        return _busiest(_difference(small, self._empty)[y1:y2, x1:x2])

    def _watch(self, small, scale):
        x1, y1, x2, y2 = self._watched(small.shape)
        change = _difference(small, self._previous)
        self._previous = small

        here = _busiest(change[y1:y2, x1:x2])
        elsewhere = change.copy()
        elsewhere[y1:y2, x1:x2] = 0.0
        around = _busiest(elsewhere[::2, ::2])

        # Is the bobber still where it was found? Compared with the water as it was without one.
        # At the end of a cast with no fish the bobber is pulled in. That is a sudden change at the
        # spot as well, and the difference from a bite is that afterwards nothing is there.
        presence = self._unlike_empty_water(small) / max(self._found_strength, 0.01)
        still_out = presence >= STILL_OUT_SHARE
        self._missing = 0 if still_out else self._missing + 1
        if self._gone or self._missing >= GONE_LOOKS:
            self._gone = True
            return self._result('gone', scale, small.shape, 0.0, False, False)

        if len(self._calm) < CALM_LOOKS:
            self._calm.append(here)
            return self._result('watching', scale, small.shape, 0.0, False, still_out)

        calm = float(np.median(self._calm))
        spread = float(np.median(np.abs(np.array(self._calm) - calm))) * 1.4826
        needed = max(BURST_RISE, BURST_RISE_SPREADS * spread, (BURST_TIMES_CALM - 1) * calm)
        # 1.0 is exactly enough to count as a burst; the page and the report show this number.
        strength = max(0.0, here - calm) / needed
        if here < BURST_OVER_ELSEWHERE * around:
            strength = min(strength, 0.99)   # the whole picture moved, not the bobber
        # A bobber being pulled in moves the spot a lot too. A look only counts towards the strongest
        # movement once the next look shows the bobber still clearly there.
        if presence >= CLEARLY_THERE_SHARE:
            self.peak_strength = max(self.peak_strength, self._unconfirmed)
            self._unconfirmed = strength
        else:
            self._unconfirmed = 0.0
        burst = strength >= 1.0 and still_out
        if burst:
            self._bursts += 1
        else:
            self._bursts = 0
            # Only calm looks teach it what calm is, so a bite does not raise the bar for itself.
            if strength < 0.5:
                self._calm.append(here)
                del self._calm[:-20]
        bite = self._bursts >= BURST_LOOKS or (burst and strength >= STRONG_BURST and presence >= CLEARLY_THERE_SHARE)
        if bite:
            self.peak_strength = max(self.peak_strength, strength)
        return self._result('watching', scale, small.shape, strength, bite, still_out)

    def _result(self, phase, scale, shape, strength, bite, still_out):
        x1, y1, x2, y2 = self._watched(shape)
        x, y = self._bobber
        return Movement(phase, (x / scale, y / scale), (x1 / scale, y1 / scale, x2 / scale, y2 / scale),
                        strength, bite, still_out)
