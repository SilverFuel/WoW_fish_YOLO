"""Screen capture plus detection: where on the screen is the splash, if anywhere."""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass

import cv2
import numpy as np

from fishbot.detector import STRIDE
from fishbot.settings import SCAN_AREAS

PREVIEW_WIDTH = 720
CANDIDATE_SCORE = 0.05  # below this the best box is noise and is not drawn
# A bobber does not land at the very edge of the window, where the game's interface sits.
EDGE_MARGIN = 0.05
TRAINED_SHAPE = 16 / 9  # width to height of the pictures the model learnt from
# A splash is a small part of the picture: its box is between these shares of the window's width and height.
SMALLEST_BOX, LARGEST_BOX = 0.005, 0.35


class ScreenGrabber:
    """Grabs screen regions as BGR arrays. mss handles are per thread, so one is kept for each."""

    def __init__(self):
        self._local = threading.local()

    def grab(self, region):
        screen = getattr(self._local, 'screen', None)
        if screen is None:
            import mss
            # mss.MSS is the current name; older releases only have mss.mss.
            screen = self._local.screen = (getattr(mss, 'MSS', None) or mss.mss)()
        return np.ascontiguousarray(np.asarray(screen.grab(region))[:, :, :3])  # BGRA -> BGR

    def close(self):
        """Let go of this thread's capture handles. Every session and every check runs on its own
        thread, and a handle that is never closed keeps a screen-sized picture in memory."""
        screen = getattr(self._local, 'screen', None)
        if screen is not None:
            self._local.screen = None
            try:
                screen.close()
            except Exception:
                pass


def scan_region(region, fraction):
    """The centred part of ``region`` that is ``fraction`` of its width and height."""
    width = max(1, int(round(region['width'] * fraction)))
    height = max(1, int(round(region['height'] * fraction)))
    return {'left': region['left'] + (region['width'] - width) // 2,
            'top': region['top'] + (region['height'] - height) // 2,
            'width': width, 'height': height}


@dataclass(frozen=True)
class Sighting:
    """One look at the game: the pixels, the best candidate and whether it clears the threshold."""
    frame: np.ndarray
    detection: object
    confident: bool
    offset: tuple = (0, 0)  # where the scanned area starts inside ``frame``, in pixels
    scan_size: tuple | None = None  # (width, height) of the scanned area in pixels, if it is a part
    note: str = ''  # why a confident candidate was not accepted, in words


class Vision:
    def __init__(self, detector, grabber, confidence, scan_area):
        self._detector = detector
        self._grabber = grabber
        self._confidence = confidence
        self._fraction, self._size = SCAN_AREAS[scan_area]
        self.last = None
        self.looks = 0  # how many pictures have been taken; lets the page tell a new one from the last
        self.blank_streak = 0  # how many pictures in a row were black

    def _input_size(self, width, height):
        """The detector's input size for an area of this shape.

        The model learnt the bobber at the size it has in a 16:9 picture shrunk to 640 wide. A wider
        area shrunk to that same width would make the bobber smaller than anything it learnt, so a
        wider area gets a proportionally wider input and the bobber keeps its size.
        """
        widest = TRAINED_SHAPE * height
        if width <= widest * 1.02:
            return self._size
        return int(math.ceil(self._size * width / widest / STRIDE)) * STRIDE

    def _choose(self, candidates, origin, to_screen, region):
        """Pick what to act on: the surest candidate that is sure enough and passes the position and size
        rules. A surer one that fails them does not hide it.

        Returns (candidate, its screen position, whether to act on it, why the surest one was held back).
        """
        def on_screen(candidate):
            return (int(origin[0] + candidate.center[0] * to_screen[0]),
                    int(origin[1] + candidate.center[1] * to_screen[1]))

        held_back = ''
        for candidate in candidates:
            if candidate.score < self._confidence:
                break
            box = ((candidate.x2 - candidate.x1) * to_screen[0], (candidate.y2 - candidate.y1) * to_screen[1])
            note = implausible(on_screen(candidate), box, region)
            if not note:
                return candidate, on_screen(candidate), True, ''
            held_back = held_back or note
        return candidates[0], on_screen(candidates[0]), False, held_back

    def find_splash(self, region):
        """Return the screen position of the splash inside the window ``region``, or None."""
        scan = scan_region(region, self._fraction)
        frame = self._grabber.grab(scan)
        candidates = self._detector.detect_all(frame, self._input_size(frame.shape[1], frame.shape[0]), self._confidence)
        self.looks += 1
        self.blank_streak = self.blank_streak + 1 if looks_blank(frame) else 0

        # Frame pixels are not always screen units (scaled displays), so convert explicitly.
        to_screen = scan['width'] / frame.shape[1], scan['height'] / frame.shape[0]
        detection, position, confident, note = self._choose(candidates, (scan['left'], scan['top']), to_screen, region)
        self.last = Sighting(frame, detection, confident, note=note)

        return position if confident else None

    def survey(self, region):
        """Look at the whole window once, for the setup check: scans the same area the bot would."""
        frame = self._grabber.grab(region)
        height, width = frame.shape[:2]
        scan_width, scan_height = max(1, int(round(width * self._fraction))), max(1, int(round(height * self._fraction)))
        left, top = (width - scan_width) // 2, (height - scan_height) // 2

        candidates = self._detector.detect_all(frame[top:top + scan_height, left:left + scan_width],
                                               self._input_size(scan_width, scan_height), self._confidence)

        # The same choice as a real look, so a green box means "it would click this".
        to_screen = region['width'] / width, region['height'] / height
        origin = (region['left'] + left * to_screen[0], region['top'] + top * to_screen[1])
        detection, _, confident, note = self._choose(candidates, origin, to_screen, region)
        self.last = Sighting(frame, detection, confident,
                             offset=(left, top), scan_size=(scan_width, scan_height), note=note)
        self.looks += 1
        return self.last


def implausible(position, box, region):
    """Why a confident sighting should still not be clicked, in words; '' if it looks like a bite.

    ``position`` and ``box`` (width, height) are in screen units; ``region`` is the game window.
    """
    x, y = position[0] - region['left'], position[1] - region['top']
    width, height = region['width'], region['height']

    if not (EDGE_MARGIN * width <= x <= (1 - EDGE_MARGIN) * width
            and EDGE_MARGIN * height <= y <= (1 - EDGE_MARGIN) * height):
        return 'too close to the edge of the game window'
    if not (SMALLEST_BOX * width <= box[0] <= LARGEST_BOX * width
            and SMALLEST_BOX * height <= box[1] <= LARGEST_BOX * height):
        return 'the wrong size for a bobber splash'
    return ''


def render_preview(sighting):
    """Draw what the bot saw as a JPEG: the scanned area and the best candidate box."""
    frame = sighting.frame
    scale = min(1.0, PREVIEW_WIDTH / frame.shape[1])
    if scale < 1.0:
        image = cv2.resize(frame, (int(frame.shape[1] * scale), int(frame.shape[0] * scale)),
                           interpolation=cv2.INTER_AREA)
    else:
        image = frame.copy()

    left, top = sighting.offset
    if sighting.scan_size is not None and sighting.scan_size != (frame.shape[1], frame.shape[0]):
        width, height = sighting.scan_size
        cv2.rectangle(image, (int(left * scale), int(top * scale)),
                      (int((left + width) * scale), int((top + height) * scale)), (255, 200, 60), 2)

    detection = sighting.detection
    if detection.score >= CANDIDATE_SCORE:
        color = (80, 220, 80) if sighting.confident else (40, 180, 255)
        cv2.rectangle(image, (int((detection.x1 + left) * scale), int((detection.y1 + top) * scale)),
                      (int((detection.x2 + left) * scale), int((detection.y2 + top) * scale)), color, 2)

    encoded, data = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 72])
    return data.tobytes() if encoded else b''


def looks_blank(frame):
    """True when a capture is a flat black image, which is what a blocked screen capture returns."""
    return int(frame.max()) < 8
