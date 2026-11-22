"""Run the detector again over the pictures in a report, to see what it makes of a cast.

    python tools/replay_report.py wow-fish-yolo-report-....zip [folder for marked-up pictures]

A report (the page's "Save a report") holds the last casts as small pictures. This prints, for
every picture, how sure the detector was when it happened and how sure it is now, and where it
looked. With a folder given, it also saves each cast's surest pictures with the box drawn in.
"""
import io
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from fishbot.detector import SplashDetector  # noqa: E402

SUREST_SAVED = 6


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    archive = zipfile.ZipFile(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)

    print(archive.read('report.txt').decode('utf-8', 'replace').split('== What it has been doing ==')[0])
    detector = SplashDetector(threads=2)
    casts = sorted({name.split('/')[1] for name in archive.namelist() if name.startswith('casts/') and name.count('/') == 2})

    for cast in casts:
        looks = json.loads(archive.read(f'casts/{cast}/looks.json'))
        pictures = sorted(name for name in archive.namelist() if name.startswith(f'casts/{cast}/') and name.endswith('.jpg'))
        print(f'\n{cast}: {len(pictures)} pictures')
        print('  seconds   then    now   box now (x1, y1, x2, y2)        size now     held back')
        replayed = []
        for look, name in zip(looks, pictures):
            frame = cv2.imdecode(np.frombuffer(archive.read(name), dtype=np.uint8), cv2.IMREAD_COLOR)
            found = detector.detect(frame)
            replayed.append((found.score, look, name, frame, found))
            print(f'  {look["seconds"]:7.2f}  {look["score"] * 100:5.1f}%  {found.score * 100:5.1f}%  '
                  f'({found.x1:6.1f}, {found.y1:6.1f}, {found.x2:6.1f}, {found.y2:6.1f})  '
                  f'{found.x2 - found.x1:5.1f} x {found.y2 - found.y1:5.1f}  {look["held_back_because"]}')

        if out is not None:
            for score, look, name, frame, found in sorted(replayed, key=lambda item: -item[0])[:SUREST_SAVED]:
                cv2.rectangle(frame, (int(found.x1), int(found.y1)), (int(found.x2), int(found.y2)), (40, 180, 255), 1)
                cv2.imwrite(str(out / f'{cast}-{look["seconds"]:05.2f}s-{round(score * 100):02d}pct.png'), frame)
    return 0


if __name__ == '__main__':
    sys.exit(main())
