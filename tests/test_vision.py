"""Detector and capture tests. They run the real ONNX model on pictures shipped in the repo.

demo_splash.png is a synthetic input optimised to trigger the detector; it is not a game
screenshot. It exists so the confident path can be tested on every system.
"""
import cv2
import numpy as np
import pytest

from fishbot import detector, vision
from fishbot.platforms import demo
from tests.conftest import ROOT

SPLASH_CENTER = (344, 248)  # where the synthetic splash sits in the 640x360 demo frame


@pytest.fixture(scope='module')
def splash_detector():
    return detector.SplashDetector(threads=2)


@pytest.fixture(scope='module')
def calm():
    return cv2.imread(str(demo.ASSETS / 'demo_calm.jpg'))


@pytest.fixture(scope='module')
def splash():
    return cv2.imread(str(demo.ASSETS / 'demo_splash.png'))


class ArrayGrabber:
    """Stands in for the screen: the region is cut out of a picture, optionally at 2x pixel density."""

    def __init__(self, picture, density=1):
        self.picture = picture
        self.density = density
        self.regions = []

    def grab(self, region):
        self.regions.append(region)
        cut = self.picture[region['top']:region['top'] + region['height'],
                           region['left']:region['left'] + region['width']]
        if self.density != 1:
            cut = cv2.resize(cut, None, fx=self.density, fy=self.density, interpolation=cv2.INTER_LINEAR)
        return cut.copy()


@pytest.mark.parametrize('shape, size, expected', [
    ((1080, 1918), 640, (384, 640)),   # the repo's example screenshot
    ((1080, 1920), 640, (384, 640)),
    ((1440, 2560), 640, (384, 640)),
    ((1200, 1920), 640, (416, 640)),   # 16:10
    ((1600, 1200), 640, (640, 480)),   # taller than wide
    ((360, 640), 640, (384, 640)),
    ((810, 1440), 480, (288, 480)),
    ((540, 960), 320, (192, 320)),
])
def test_letterbox_pads_to_the_stride_like_the_original_pipeline(shape, size, expected):
    frame = np.zeros((*shape, 3), dtype=np.uint8)

    tensor, scale, (left, top) = detector.letterbox(frame, size)

    assert tensor.shape == (1, 3, *expected)
    assert tensor.dtype == np.float32
    assert expected[0] % detector.STRIDE == 0 and expected[1] % detector.STRIDE == 0
    assert scale == pytest.approx(min(size / shape[0], size / shape[1]))
    assert 0 <= left < detector.STRIDE and 0 <= top < detector.STRIDE


def test_letterbox_converts_bgr_to_rgb_and_scales_to_0_1():
    frame = np.zeros((384, 640, 3), dtype=np.uint8)
    frame[:, :] = (255, 0, 51)  # blue, green, red

    tensor, scale, padding = detector.letterbox(frame, 640)

    assert scale == 1 and padding == (0, 0)
    assert tensor[0, :, 0, 0].tolist() == pytest.approx([0.2, 0.0, 1.0])


def test_best_detection_maps_the_top_box_back_to_frame_pixels():
    output = np.zeros((1, 5, 3), dtype=np.float32)
    output[0, :, 0] = (100, 100, 20, 20, 0.30)
    output[0, :, 1] = (200, 112, 40, 20, 0.90)
    output[0, :, 2] = (300, 100, 20, 20, 0.60)

    found = detector.best_detection(output, scale=0.5, padding=(0, 12))

    assert found.score == pytest.approx(0.90)
    assert (found.x1, found.y1, found.x2, found.y2) == pytest.approx((360, 180, 440, 220))
    assert found.center == pytest.approx((400, 200))


def test_calm_water_scores_far_below_the_threshold(splash_detector, calm):
    assert splash_detector.detect(calm).score < 0.2


def test_the_shipped_example_screenshot_scores_far_below_the_threshold(splash_detector):
    example = cv2.imread(str(ROOT / 'example.png'))

    assert splash_detector.detect(example).score < 0.2


def test_synthetic_splash_is_found_where_it_was_placed(splash_detector, splash):
    found = splash_detector.detect(splash)

    assert found.score > 0.85
    assert found.center == pytest.approx(SPLASH_CENTER, abs=6)
    assert splash_detector.last_inference_ms > 0


@pytest.mark.parametrize('title_bar', [0, 22, 28, 32, 40])
def test_synthetic_splash_is_still_found_below_a_title_bar(splash_detector, splash, title_bar):
    # On macOS the captured window includes its title bar, whose height differs between systems.
    frame = np.full((360 + title_bar, 640, 3), 235, dtype=np.uint8)
    frame[title_bar:] = splash

    found = splash_detector.detect(frame)

    assert found.score > 0.85
    assert found.center == pytest.approx((SPLASH_CENTER[0], SPLASH_CENTER[1] + title_bar), abs=6)


def test_vision_reports_nothing_on_calm_water(splash_detector, calm):
    watcher = vision.Vision(splash_detector, ArrayGrabber(calm), confidence=0.8, scan_area='full')

    assert watcher.find_splash(dict(demo.REGION)) is None
    assert watcher.last.confident is False


def test_vision_returns_the_screen_position_of_the_splash(splash_detector, splash):
    # The window sits at (300, 200) on the screen; the picture is its contents.
    canvas = np.zeros((560, 940, 3), dtype=np.uint8)
    canvas[200:560, 300:940] = splash
    watcher = vision.Vision(splash_detector, ArrayGrabber(canvas), confidence=0.8, scan_area='full')

    x, y = watcher.find_splash({'left': 300, 'top': 200, 'width': 640, 'height': 360})

    assert (x, y) == pytest.approx((300 + SPLASH_CENTER[0], 200 + SPLASH_CENTER[1]), abs=6)


def test_vision_converts_pixels_to_screen_units_on_a_scaled_display(splash_detector, splash):
    # The grabber returns twice as many pixels as the region asked for, like an unscaled Retina capture.
    watcher = vision.Vision(splash_detector, ArrayGrabber(splash, density=2), confidence=0.8, scan_area='full')

    x, y = watcher.find_splash(dict(demo.REGION))

    assert (x, y) == pytest.approx(SPLASH_CENTER, abs=8)


def test_confidence_setting_decides_what_counts(splash_detector, splash):
    score = splash_detector.detect(splash).score

    strict = vision.Vision(splash_detector, ArrayGrabber(splash), confidence=min(0.999, score + 0.01), scan_area='full')

    assert strict.find_splash(dict(demo.REGION)) is None


@pytest.mark.parametrize('area, fraction', [('full', 1.0), ('center75', 0.75), ('center50', 0.5)])
def test_scan_area_captures_only_the_centre_part(splash_detector, calm, area, fraction):
    grabber = ArrayGrabber(calm)
    watcher = vision.Vision(splash_detector, grabber, confidence=0.8, scan_area=area)

    watcher.find_splash(dict(demo.REGION))

    region = grabber.regions[0]
    assert (region['width'], region['height']) == (round(640 * fraction), round(360 * fraction))
    assert region['left'] == (640 - region['width']) // 2
    assert region['top'] == (360 - region['height']) // 2
    assert watcher.last.frame.shape[:2] == (region['height'], region['width'])


def test_scan_region_keeps_the_window_offset():
    region = vision.scan_region({'left': 100, 'top': 50, 'width': 1920, 'height': 1080}, 0.5)

    assert region == {'left': 580, 'top': 320, 'width': 960, 'height': 540}


def test_survey_looks_at_the_whole_window_and_marks_the_scanned_part(splash_detector, calm):
    watcher = vision.Vision(splash_detector, ArrayGrabber(calm), confidence=0.8, scan_area='center50')

    sighting = watcher.survey(dict(demo.REGION))

    assert sighting.frame.shape[:2] == (360, 640)
    assert sighting.offset == (160, 90)
    assert sighting.scan_size == (320, 180)


def test_preview_is_a_jpeg_no_wider_than_the_preview_width(splash_detector, splash):
    big = cv2.resize(splash, (1920, 1080))
    watcher = vision.Vision(splash_detector, ArrayGrabber(big), confidence=0.8, scan_area='center75')
    sighting = watcher.survey({'left': 0, 'top': 0, 'width': 1920, 'height': 1080})

    data = vision.render_preview(sighting)
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)

    assert data[:2] == b'\xff\xd8'
    assert image.shape[1] == vision.PREVIEW_WIDTH
    assert image.shape[0] == 405


def test_a_confident_sighting_at_the_edge_of_the_window_is_not_accepted(splash_detector, splash):
    # The window is placed so that the splash sits 15 pixels from its left edge.
    canvas = np.zeros((360, 1200, 3), dtype=np.uint8)
    canvas[:, :640] = splash
    window = {'left': SPLASH_CENTER[0] - 15, 'top': 0, 'width': 640, 'height': 360}
    watcher = vision.Vision(splash_detector, ArrayGrabber(canvas), confidence=0.8, scan_area='full')

    assert watcher.find_splash(window) is None
    assert watcher.last.detection.score > 0.8  # the model was sure
    assert watcher.last.confident is False
    assert watcher.last.note == 'too close to the edge of the game window'


def test_take_a_look_judges_a_candidate_the_same_way_a_real_look_does(splash_detector, splash):
    # Green on the page means "it would click this", so the edge and size rules have to apply here too.
    canvas = np.zeros((360, 1200, 3), dtype=np.uint8)
    canvas[:, :640] = splash
    at_the_edge = {'left': SPLASH_CENTER[0] - 15, 'top': 0, 'width': 640, 'height': 360}
    in_the_middle = {'left': 0, 'top': 0, 'width': 640, 'height': 360}
    watcher = vision.Vision(splash_detector, ArrayGrabber(canvas), confidence=0.8, scan_area='full')

    edge = watcher.survey(at_the_edge)
    assert edge.detection.score > 0.8 and edge.confident is False
    assert edge.note == 'too close to the edge of the game window'

    middle = watcher.survey(in_the_middle)
    assert middle.confident is True and middle.note == ''


@pytest.mark.parametrize('position, box, expected', [
    ((960, 540), (80, 60), ''),
    ((100 + 97, 50 + 540), (80, 60), ''),                 # just inside the 5% margin
    ((100 + 60, 50 + 540), (80, 60), 'edge'),             # left edge
    ((100 + 1900, 50 + 540), (80, 60), 'edge'),           # right edge
    ((960, 50 + 20), (80, 60), 'edge'),                   # top edge
    ((960, 50 + 1070), (80, 60), 'edge'),                 # bottom edge
    ((960, 540), (900, 60), 'size'),                      # far too wide
    ((960, 540), (80, 500), 'size'),                      # far too tall
    ((960, 540), (4, 3), 'size'),                         # a speck
])
def test_implausible_judges_position_and_size_against_the_window(position, box, expected):
    window = {'left': 100, 'top': 50, 'width': 1920, 'height': 1080}

    assert expected in vision.implausible(position, box, window)
    assert bool(vision.implausible(position, box, window)) == bool(expected)


def test_black_pictures_are_counted_in_a_row(splash_detector, calm):
    black = ArrayGrabber(np.zeros((360, 640, 3), dtype=np.uint8))
    watcher = vision.Vision(splash_detector, black, confidence=0.8, scan_area='full')

    for _ in range(3):
        watcher.find_splash(dict(demo.REGION))
    assert watcher.blank_streak == 3

    black.picture = calm
    watcher.find_splash(dict(demo.REGION))
    assert watcher.blank_streak == 0


def test_blank_capture_is_recognised():
    assert vision.looks_blank(np.zeros((10, 10, 3), dtype=np.uint8))
    assert not vision.looks_blank(np.full((10, 10, 3), 40, dtype=np.uint8))
