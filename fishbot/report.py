"""A report to send when it does not work on someone's computer.

While it fishes, the last couple of casts are kept in memory as small pictures, each with what the
detector made of it. Nothing is written anywhere until the person asks for a report. The report is
one ZIP: those pictures, the pictures of what it clicked, the log, the settings and plain facts
about the screens and the game window. With it, a cast can be replayed and looked at elsewhere.
"""
from __future__ import annotations

import collections
import io
import json
import platform as host
import sys
import threading
import time
import zipfile

import cv2

RECORDED_CASTS = 2
LOOKS_PER_CAST = 180        # the most recent ones are kept, which is where a bite or a miss is decided
RECORDED_WIDTH = 512        # wider than the bobber watcher works at, and close to the detector's own input
RECORD_EVERY_SEC = 0.15     # so that at the usual five looks a second every look is kept, and a cast can be replayed
ALWAYS_RECORD_SCORE = 0.2   # a look this bite-like is kept however soon it comes after the last one
JPEG_QUALITY = 78


class CastRecorder:
    """Keeps what the bot saw during the last casts. Safe to call from the fishing thread."""

    def __init__(self):
        self._lock = threading.Lock()
        self._casts = collections.deque(maxlen=RECORDED_CASTS)

    def look(self, cast, seconds, sighting):
        score = float(sighting.detection.score)
        with self._lock:
            if not self._casts or self._casts[-1]['cast'] != cast:
                self._casts.append({'cast': cast, 'looks': collections.deque(maxlen=LOOKS_PER_CAST)})
            looks = self._casts[-1]['looks']
            # Pictures from before the cast (negative time) are few and all needed to replay it.
            if looks and 0 <= seconds - looks[-1]['seconds'] < RECORD_EVERY_SEC and seconds >= 0 and score < ALWAYS_RECORD_SCORE:
                return

        frame = sighting.frame
        height, width = frame.shape[:2]
        scale = min(1.0, RECORDED_WIDTH / width)
        if scale < 1.0:
            frame = cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))),
                               interpolation=cv2.INTER_AREA)
        encoded, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if not encoded:
            return

        found = sighting.detection
        look = {'seconds': round(float(seconds), 2), 'score': round(score, 4),
                'sure_enough': bool(sighting.confident), 'held_back_because': sighting.note,
                'spotted_by': getattr(sighting, 'by', ''),
                'seen_size': [width, height],
                'box_in_picture': [round(float(value) * scale, 1) for value in (found.x1, found.y1, found.x2, found.y2)],
                'jpeg': jpeg.tobytes()}
        movement = getattr(sighting, 'movement', None)
        if movement is not None:
            look['movement'] = {'phase': movement.phase, 'share_of_a_bite': round(float(movement.strength), 3),
                                'bite': bool(movement.bite), 'bobber_still_there': bool(movement.still_out),
                                'bobber_in_picture': None if movement.bobber is None else
                                [round(float(value) * scale, 1) for value in movement.bobber]}
        with self._lock:
            looks.append(look)

    def casts(self):
        with self._lock:
            return [{'cast': cast['cast'], 'looks': list(cast['looks'])} for cast in self._casts]


def _summary(cast):
    looks = cast['looks']
    if not looks:
        return f'Cast {cast["cast"]}: nothing was recorded.'
    surest = max(looks, key=lambda look: look['score'])
    clicked = [look for look in looks if look['sure_enough']]
    held_back = sorted({look['held_back_because'] for look in looks if look['held_back_because']})
    line = (f'Cast {cast["cast"]}: {len(looks)} pictures from {looks[0]["seconds"]} s to {looks[-1]["seconds"]} s '
            f'after casting, each {surest["seen_size"][0]} x {surest["seen_size"][1]} as seen. '
            f'Surest look: {round(surest["score"] * 100)}% at {surest["seconds"]} s. ')
    line += (f'Sure enough to click at {clicked[0]["seconds"]} s (by its {clicked[0].get("spotted_by") or "look"}).'
             if clicked else 'Never sure enough to click.')
    if held_back:
        line += f' Held back because: {"; ".join(held_back)}.'

    watched = [look['movement'] for look in looks if 'movement' in look]
    if watched:
        found_at = next((look['seconds'] for look in looks if look.get('movement', {}).get('bobber_in_picture')), None)
        if found_at is None:
            line += ' By movement: the bobber was never found.'
        else:
            strongest = max(movement['share_of_a_bite'] for movement in watched)
            line += (f' By movement: bobber found at {found_at} s; its strongest movement was {round(strongest * 100)}% of a bite'
                     f'{"; it was pulled in" if any(movement["phase"] == "gone" for movement in watched) else ""}.')
    return line


def build(version, system_facts, settings, state, log, casts, clicks, last_picture):
    """The report as the bytes of a ZIP file.

    ``clicks`` is a list of (name, jpeg bytes); ``last_picture`` is jpeg bytes or None.
    """
    lines = ['WoW Fish YOLO report', '',
             f'Made: {time.strftime("%Y-%m-%d %H:%M:%S")}',
             f'Version: {version}',
             f'Python: {sys.version.split()[0]} on {host.platform()}',
             '', '== This computer ==', *system_facts,
             '', '== Settings ==', *(f'{name}: {value}' for name, value in settings.items()),
             '', '== Right now ==', *(f'{name}: {value}' for name, value in state.items()),
             '', '== The last casts ==', *([_summary(cast) for cast in casts] or ['No cast has been recorded yet.']),
             '', '== What it has been doing ==',
             *(f'{time.strftime("%H:%M:%S", time.localtime(entry["time"]))} {entry["message"]}' for entry in log)]

    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('report.txt', '\n'.join(lines) + '\n')
        for cast in casts:
            folder = f'casts/cast-{cast["cast"]:04d}'
            archive.writestr(f'{folder}/looks.json', json.dumps(
                [{name: value for name, value in look.items() if name != 'jpeg'} for look in cast['looks']], indent=1))
            for number, look in enumerate(cast['looks']):
                name = f'{number:03d}-at-{look["seconds"]:05.2f}s-{round(look["score"] * 100):02d}pct.jpg'
                archive.writestr(f'{folder}/{name}', look['jpeg'], zipfile.ZIP_STORED)
        for name, jpeg in clicks:
            archive.writestr(f'clicked/{name}.jpg', jpeg, zipfile.ZIP_STORED)
        if last_picture is not None:
            archive.writestr('last-picture.jpg', last_picture, zipfile.ZIP_STORED)
    return data.getvalue()
