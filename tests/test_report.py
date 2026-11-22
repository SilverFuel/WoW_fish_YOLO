"""The record of what was seen during the last casts, and the report built from it."""
import io
import json
import zipfile

import numpy as np

from fishbot import report
from fishbot.detector import Detection
from fishbot.vision import Sighting


def sighting(score, width=1920, height=1080, note=''):
    frame = np.full((height, width, 3), 90, dtype=np.uint8)
    return Sighting(frame, Detection(score, 900, 500, 1020, 580), score >= 0.8 and not note, note=note)


def test_looks_are_kept_small_and_spaced_out_but_a_bite_like_look_is_never_skipped():
    recorder = report.CastRecorder()
    for seconds in (1.0, 1.1, 1.2, 1.35, 1.5, 1.7):   # looks come faster than pictures are kept
        recorder.look(1, seconds, sighting(0.02))
    recorder.look(1, 1.75, sighting(0.91))            # right after the last one, but it looks like a bite

    looks = recorder.casts()[0]['looks']

    assert [look['seconds'] for look in looks] == [1.0, 1.35, 1.7, 1.75]
    assert looks[-1]['score'] == 0.91 and looks[-1]['sure_enough'] is True
    assert looks[0]['seen_size'] == [1920, 1080]
    assert looks[0]['box_in_picture'] == [300.0, 166.7, 340.0, 193.3]   # the box, scaled with the picture
    picture = np.frombuffer(looks[0]['jpeg'], dtype=np.uint8)
    assert picture[:2].tobytes() == b'\xff\xd8'


def test_only_the_last_casts_are_kept_and_a_small_window_is_not_enlarged():
    recorder = report.CastRecorder()
    for cast in range(1, 5):
        recorder.look(cast, 1.0, sighting(0.1, width=320, height=180))

    casts = recorder.casts()

    assert [cast['cast'] for cast in casts] == [3, 4]
    assert casts[0]['looks'][0]['box_in_picture'] == [900.0, 500.0, 1020.0, 580.0]


def test_the_report_is_one_file_that_says_what_happened_in_plain_words():
    recorder = report.CastRecorder()
    recorder.look(7, 1.0, sighting(0.03))
    recorder.look(7, 6.4, sighting(0.64))
    recorder.look(7, 9.0, sighting(0.93, note='too close to the edge of the game window'))

    data = report.build('2.0.0', ['Screens: 1920 x 1080 at (0, 0), scaling 150%, main screen'],
                        {'fishing_key': '1', 'confidence': 0.8}, {'state': 'idle', 'casts': 7},
                        [{'time': 0, 'message': 'Cast 7. Waiting for a bite...'}], recorder.casts(),
                        [('click-003-91pct', b'\xff\xd8click')], b'\xff\xd8last')

    archive = zipfile.ZipFile(io.BytesIO(data))
    names = archive.namelist()
    text = archive.read('report.txt').decode()

    assert 'Version: 2.0.0' in text and 'scaling 150%' in text and 'fishing_key: 1' in text
    assert ('Cast 7: 3 pictures from 1.0 s to 9.0 s after casting, each 1920 x 1080 as seen. Surest look: 93% at 9.0 s. '
            'Never sure enough to click. Held back because: too close to the edge of the game window.') in text
    assert 'Cast 7. Waiting for a bite...' in text
    assert 'casts/cast-0007/001-at-06.40s-64pct.jpg' in names
    assert 'clicked/click-003-91pct.jpg' in names and 'last-picture.jpg' in names
    looks = json.loads(archive.read('casts/cast-0007/looks.json'))
    assert [look['score'] for look in looks] == [0.03, 0.64, 0.93] and 'jpeg' not in looks[0]


def test_a_report_with_nothing_recorded_still_says_so():
    data = report.build('2.0.0', [], {}, {}, [], [], [], None)

    assert 'No cast has been recorded yet.' in zipfile.ZipFile(io.BytesIO(data)).read('report.txt').decode()
