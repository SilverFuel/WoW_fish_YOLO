"""Bobber-splash detection with ONNX Runtime.

The model is the original YOLOv8 network exported to ONNX, so the bot needs neither torch nor
ultralytics at run time. Only the single best detection is ever used, which makes non-maximum
suppression unnecessary: the highest-scoring box always survives it.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import onnxruntime

DEFAULT_MODEL = Path(__file__).resolve().parent.parent / 'models' / 'splash.onnx'
MODEL_INPUT_SIZE = 640  # the size the model was trained at, for a full-window frame
STRIDE = 32
PAD_VALUE = 114


@dataclass(frozen=True)
class Detection:
    """The best candidate in one frame, in frame pixels. ``score`` may be below the threshold."""
    score: float
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def center(self):
        return (self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2


def letterbox(frame, size):
    """Resize a BGR frame so its longer side is ``size``, padded to a multiple of the stride.

    Returns the network input (1x3xHxW, RGB, 0..1), the scale applied and the (left, top) padding.
    This mirrors the preprocessing the model was trained and originally run with.
    """
    height, width = frame.shape[:2]
    scale = min(size / height, size / width)
    new_width, new_height = int(round(width * scale)), int(round(height * scale))

    pad_x = ((size - new_width) % STRIDE) / 2
    pad_y = ((size - new_height) % STRIDE) / 2
    left, right = int(round(pad_x - 0.1)), int(round(pad_x + 0.1))
    top, bottom = int(round(pad_y - 0.1)), int(round(pad_y + 0.1))

    if (new_width, new_height) != (width, height):
        frame = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
    frame = cv2.copyMakeBorder(frame, top, bottom, left, right, cv2.BORDER_CONSTANT,
                               value=(PAD_VALUE, PAD_VALUE, PAD_VALUE))

    tensor = frame[:, :, ::-1].transpose(2, 0, 1)[np.newaxis]
    tensor = np.ascontiguousarray(tensor, dtype=np.float32) / 255.0
    return tensor, scale, (left, top)


def best_detection(output, scale, padding):
    """Turn the raw network output (1 x 5 x N: cx, cy, w, h, score) into the top Detection."""
    predictions = output[0]
    best = int(predictions[4].argmax())
    center_x, center_y, box_width, box_height, score = (float(value) for value in predictions[:, best])
    left, top = padding

    return Detection(score,
                     (center_x - box_width / 2 - left) / scale, (center_y - box_height / 2 - top) / scale,
                     (center_x + box_width / 2 - left) / scale, (center_y + box_height / 2 - top) / scale)


def detections(output, scale, padding, minimum, limit=5):
    """The distinct candidates scoring at least ``minimum``, surest first, at most ``limit`` of them.

    The network proposes many overlapping boxes for one thing; boxes that overlap a surer one are
    dropped, so each entry is a different thing on screen.
    """
    predictions = output[0]
    order = [int(index) for index in np.argsort(-predictions[4]) if predictions[4, index] >= minimum][:200]
    left, top = padding
    kept = []
    for index in order:
        center_x, center_y, box_width, box_height, score = (float(value) for value in predictions[:, index])
        box = Detection(score,
                        (center_x - box_width / 2 - left) / scale, (center_y - box_height / 2 - top) / scale,
                        (center_x + box_width / 2 - left) / scale, (center_y + box_height / 2 - top) / scale)
        if all(_overlap(box, other) < 0.5 for other in kept):
            kept.append(box)
            if len(kept) == limit:
                break
    return kept


def _overlap(a, b):
    """How much two boxes overlap, from 0 (apart) to 1 (the same box)."""
    width = min(a.x2, b.x2) - max(a.x1, b.x1)
    height = min(a.y2, b.y2) - max(a.y1, b.y1)
    if width <= 0 or height <= 0:
        return 0.0
    shared = width * height
    return shared / ((a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - shared)


class SplashDetector:
    def __init__(self, model_path=DEFAULT_MODEL, threads=2):
        options = onnxruntime.SessionOptions()
        # A couple of threads is plenty at a few frames per second, and leaves the rest for the game.
        options.intra_op_num_threads = max(1, int(threads))
        options.inter_op_num_threads = 1
        # The arena keeps freed memory for reuse. Without it the process stays about 90 MiB
        # smaller and, at this frame rate, no slower.
        options.enable_cpu_mem_arena = False
        options.enable_mem_pattern = False
        # By default idle worker threads spin while they wait for the next frame, which burns CPU
        # between looks. Letting them sleep costs nothing at a few frames per second.
        options.add_session_config_entry('session.intra_op.allow_spinning', '0')
        self._session = onnxruntime.InferenceSession(str(model_path), sess_options=options,
                                                     providers=['CPUExecutionProvider'])
        self._input_name = self._session.get_inputs()[0].name
        self.last_inference_ms = 0.0

    def detect(self, frame, size=MODEL_INPUT_SIZE):
        """Return the best candidate in a BGR frame. The caller compares its score to the threshold."""
        started = time.perf_counter()
        tensor, scale, padding = letterbox(frame, size)
        output = self._session.run(None, {self._input_name: tensor})[0]
        self.last_inference_ms = (time.perf_counter() - started) * 1000
        return best_detection(output, scale, padding)

    def detect_all(self, frame, size=MODEL_INPUT_SIZE, minimum=0.5):
        """The best candidate, as ``detect`` gives it, followed by the other distinct ones scoring
        at least ``minimum``. The list always has the best one first, whatever it scores."""
        started = time.perf_counter()
        tensor, scale, padding = letterbox(frame, size)
        output = self._session.run(None, {self._input_name: tensor})[0]
        self.last_inference_ms = (time.perf_counter() - started) * 1000
        best = best_detection(output, scale, padding)
        others = [box for box in detections(output, scale, padding, minimum) if _overlap(box, best) < 0.5]
        return [best, *others]
