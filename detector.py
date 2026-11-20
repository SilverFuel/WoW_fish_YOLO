"""Screen capture and bobber-splash detection."""
import cv2
import mss
import numpy as np
from ultralytics import YOLO

CONFIDENCE = 0.8


class SplashDetector:
    def __init__(self, model_path, device='cpu', screen=None):
        self._model = YOLO(str(model_path))
        self._device = device
        # One capture handle for the whole session; opening a new one for every frame is slow.
        self._screen = screen if screen is not None else mss.mss()

    def find_splash(self, region):
        """Return the on-screen (x, y) centre of the splash inside ``region``, or None.

        ``region`` is an mss region: left/top/width/height in screen pixels.
        """
        frame = np.array(self._screen.grab(region))
        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)  # ultralytics expects BGR arrays

        results = self._model.predict(source=frame, conf=CONFIDENCE, device=self._device, verbose=False)
        if not results or len(results[0].boxes) == 0:
            return None

        boxes = results[0].boxes
        x1, y1, x2, y2 = boxes.xyxy[int(boxes.conf.argmax())].tolist()

        return region['left'] + int((x1 + x2) / 2), region['top'] + int((y1 + y2) / 2)
