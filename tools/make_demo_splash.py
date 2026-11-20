"""Rebuild fishbot/assets/demo_splash.png, the synthetic picture used by the demo and the tests.

No splash screenshots ship with this repository, so real pictures only ever produce scores near
zero. This script changes a small patch of the example screenshot until the original PyTorch
model reports a confident splash there. The result is a numerical probe: it lets the confident
path (threshold, coordinates, looting) be tested on any system. It is not a game screenshot.

The patch is optimised while the picture is shifted around at random, so it keeps working when
it is shown a few pixels off, for example below a window's title bar.

    pip install ultralytics
    python tools/make_demo_splash.py path/to/best.pt
"""
import random
import sys
from pathlib import Path

import cv2
import numpy as np
import torch
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fishbot import detector  # noqa: E402

OUTPUT = ROOT / 'fishbot' / 'assets' / 'demo_splash.png'
PATCH_CENTER, PATCH_HALF = (377, 229), 40  # around the bobber, in network pixels
STEPS = 900
MAX_SHIFT = 20  # pixels, in every direction


def main():
    torch.manual_seed(0)
    random.seed(0)
    model = YOLO(sys.argv[1]).model.float().eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)

    screenshot = cv2.imread(str(ROOT / 'example.png'))
    base = cv2.resize(screenshot, (640, 360), interpolation=cv2.INTER_AREA)
    start = torch.from_numpy(detector.letterbox(base, 640)[0])  # 1 x 3 x 384 x 640

    (center_x, center_y), half = PATCH_CENTER, PATCH_HALF
    mask = torch.zeros_like(start)
    mask[:, :, center_y - half:center_y + half, center_x - half:center_x + half] = 1
    change = torch.zeros_like(start, requires_grad=True)
    optimizer = torch.optim.Adam([change], lr=0.02)

    for step in range(STEPS):
        picture = (start + change * mask).clamp(0, 1)
        # Round to 8 bits in the forward pass, so the saved PNG scores the same as what was optimised.
        picture = ((picture * 255).round() - picture * 255).detach() / 255 + picture
        shift = (random.randint(-MAX_SHIFT, MAX_SHIFT), random.randint(-MAX_SHIFT, MAX_SHIFT))
        output = model(torch.roll(picture, shifts=shift, dims=(2, 3)))
        output = output[0] if isinstance(output, (list, tuple)) else output
        score = output[0, 4].max()
        (-torch.logit(score.clamp(1e-6, 1 - 1e-6))).backward()
        optimizer.step()
        optimizer.zero_grad()
        if step % 100 == 0 or step == STEPS - 1:
            print(f'step {step}: score {float(score):.4f}')

    final = ((start + change.detach() * mask).clamp(0, 1) * 255).round().numpy().astype(np.uint8)[0]
    frame = np.ascontiguousarray(final[:, 12:372, :].transpose(1, 2, 0)[:, :, ::-1])  # drop padding, RGB -> BGR
    cv2.imwrite(str(OUTPUT), frame)

    found = detector.SplashDetector().detect(cv2.imread(str(OUTPUT)))
    print(f'Wrote {OUTPUT}: the ONNX model scores it {found.score:.3f} at {tuple(round(v) for v in found.center)}')


if __name__ == '__main__':
    main()
