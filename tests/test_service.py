"""The background service, driven through the simulated game with the real detector."""
import threading
import time

import pytest

from fishbot import platforms
from fishbot.platforms import GameWindowNotFound, demo
from fishbot.service import BotService
from fishbot.settings import SettingsStore


class DemoPlatform:
    """The demo platform with its own game, so tests do not share state, and scriptable hotkeys."""

    SYSTEM, LABEL, SETUP_NOTES = demo.SYSTEM, demo.LABEL, demo.SETUP_NOTES

    def __init__(self, bite_after=(2.1, 2.3)):  # a bite sooner than 2 s after casting counts as suspicious
        self.game = demo.DemoGame(bite_after=bite_after)
        self.keys_down = set()
        self.window_missing = False
        self.missing_permissions = []

    def find_game_window(self):
        if self.window_missing:
            raise GameWindowNotFound('World of Warcraft does not seem to be open. Start the game, then try again.')
        return demo.DemoWindow()

    def key_is_down(self, name):
        return name in self.keys_down

    def permission_problems(self):
        return list(self.missing_permissions)

    def create_controls(self):
        return demo.DemoControls(self.game)

    def create_grabber(self):
        return demo.DemoGrabber(self.game)


@pytest.fixture
def platform():
    return DemoPlatform()


@pytest.fixture
def service(platform, tmp_path):
    store = SettingsStore(tmp_path / 'settings.json', platform.SYSTEM)
    store.update({'fishing_key': 'f', 'checks_per_second': 15})
    service = BotService(platform, store)
    yield service
    service.shutdown()


def wait_for(condition, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_will_not_start_without_a_fishing_key(platform, tmp_path):
    service = BotService(platform, SettingsStore(tmp_path / 'settings.json', platform.SYSTEM))

    assert service.start() == ['Pick your fishing key first.']
    assert not service.running


def test_will_not_start_when_the_game_is_not_running(service, platform):
    platform.window_missing = True

    assert service.start() == ['World of Warcraft does not seem to be open. Start the game, then try again.']
    assert service.snapshot()['state'] == 'idle'


def test_will_not_start_until_the_system_allows_it(service, platform):
    platform.missing_permissions = ['macOS is not letting the bot press keys or click.']

    assert service.start() == ['macOS is not letting the bot press keys or click.']
    assert service.check_setup() == {'ok': False, 'message': 'macOS is not letting the bot press keys or click.'}
    assert not service.running
    assert platform.game.events == []


def test_status_is_still_answered_while_the_model_and_controls_load(service, platform):
    release = threading.Event()
    real_controls = platform.create_controls

    def slow_controls():
        release.wait(10)
        return real_controls()

    platform.create_controls = slow_controls
    service.start()
    try:
        assert wait_for(lambda: service._load_lock.locked(), timeout=5)
        started = time.monotonic()
        snapshot = service.snapshot()
        assert time.monotonic() - started < 0.5
        assert snapshot['state'] == 'starting' and snapshot['running'] is True
    finally:
        release.set()
    assert wait_for(lambda: service.snapshot()['state'] == 'fishing')


def test_fishes_end_to_end_with_the_real_detector(service, platform):
    assert service.start() == []
    assert service.start() == ['It is already running.']

    assert wait_for(lambda: service.snapshot()['stats']['looted'] >= 1)
    running = service.snapshot()
    service.stop()
    service.wait(10)
    stopped = service.snapshot()

    kinds = [event[0] for event in platform.game.events]
    assert kinds[:3] == ['press', 'move', 'click']
    assert platform.game.events[0] == ('press', 'f')
    # The click lands where the simulated game put the splash for that cast.
    assert platform.game.events[1][1:] == pytest.approx(platform.game.landings[0], abs=6)
    assert platform.game.events[2] == ('click', 'right', platform.game.events[1][1], platform.game.events[1][2])
    assert running['running'] and running['state'] == 'fishing'
    assert running['stats']['inference_ms'] > 0
    assert not stopped['running'] and stopped['state'] == 'idle'
    assert stopped['message'] == 'Stopped.'
    assert stopped['stats']['looted'] >= 1  # the last session's numbers stay visible


def test_every_click_is_kept_with_the_picture_it_was_based_on(service, platform):
    assert service.snapshot()['clicks'] == []

    service.start()
    assert wait_for(lambda: service.snapshot()['stats']['looted'] >= 1)
    service.stop()
    service.wait(10)

    newest = service.snapshot()['clicks'][0]
    assert (newest['x'], newest['y']) == pytest.approx(platform.game.landings[newest['id'] - 1], abs=6)
    assert newest['practice'] is False and newest['score'] >= 0.8
    assert 'picture' not in newest
    assert service.click_jpeg(newest['id'])[:2] == b'\xff\xd8'
    assert service.click_jpeg(999) is None


def test_practice_needs_no_keys_because_it_presses_none(platform, tmp_path):
    service = BotService(platform, SettingsStore(tmp_path / 'fresh.json', platform.SYSTEM))
    try:
        assert service.start() == ['Pick your fishing key first.']
        assert service.start(practice=True) == []
        assert wait_for(lambda: service.snapshot()['state'] == 'practice')
    finally:
        service.shutdown()
    assert platform.game.events == []


def test_the_pretend_game_does_not_promise_keys_that_do_nothing(service):
    service.start()
    assert wait_for(lambda: service.snapshot()['state'] == 'fishing')
    service.stop()
    service.wait(10)

    lines = [entry['message'] for entry in service.snapshot()['log']]
    assert lines[0] == 'Started. This is the pretend game, so use the buttons on this page to pause and stop.'
    assert not any('F8' in line for line in lines)


def test_the_page_is_told_what_it_is_waiting_for(service):
    assert service.snapshot()['waiting_for'] == ''

    service.start()
    assert wait_for(lambda: service.snapshot()['state'] == 'fishing')
    assert service.snapshot()['waiting_for'] in ('game', 'mouse')  # the engine's own value is passed on


def test_practice_sends_nothing_and_still_records_what_it_would_click(service, platform):
    assert service.start(practice=True) == []
    assert wait_for(lambda: service.snapshot()['state'] == 'practice')

    platform.game.cast()  # the user casts in the game themselves
    assert wait_for(lambda: service.snapshot()['stats']['practice_clicks'] >= 1)
    service.stop()
    service.wait(10)

    snapshot = service.snapshot()
    assert platform.game.events == []
    assert snapshot['clicks'][0]['practice'] is True
    assert (snapshot['clicks'][0]['x'], snapshot['clicks'][0]['y']) == pytest.approx(platform.game.landings[0], abs=6)
    assert snapshot['stats']['looted'] == 0 and snapshot['stats']['casts'] == 0
    assert snapshot['practice'] is True

    service.start()  # a normal start afterwards is a normal session again
    assert wait_for(lambda: service.snapshot()['state'] == 'fishing')
    assert service.snapshot()['practice'] is False


def test_a_stop_by_a_safeguard_is_marked_as_one(service, platform):
    # Nothing ever bites, and the bot gives up after one miss.
    platform.game.bite_after = (1000, 1000)
    service.store.update({'stop_after_misses': 1, 'cast_seconds': 5})
    service.start()

    assert wait_for(lambda: not service.running, timeout=30)

    snapshot = service.snapshot()
    assert snapshot['stopped_by_safeguard'] is True
    assert snapshot['message'].startswith('Stopped: no bite on the last cast.')

    service.store.update({'stop_after_misses': 0})
    service.start()
    assert wait_for(lambda: service.snapshot()['state'] == 'fishing')
    assert service.snapshot()['stopped_by_safeguard'] is False  # a new session starts clean


def test_a_stop_by_the_user_is_not_marked_as_a_safeguard(service):
    service.start()
    assert wait_for(lambda: service.snapshot()['state'] == 'fishing')
    service.stop()
    service.wait(10)

    assert service.snapshot()['stopped_by_safeguard'] is False


def test_pause_and_resume(service, platform):
    service.start()
    assert wait_for(lambda: service.snapshot()['state'] == 'fishing')

    service.set_paused(True)
    assert wait_for(lambda: service.snapshot()['state'] == 'paused')
    events_while_paused = len(platform.game.events)
    time.sleep(0.6)
    assert len(platform.game.events) == events_while_paused

    service.set_paused(False)
    assert wait_for(lambda: service.snapshot()['state'] == 'fishing')


def test_hotkeys_pause_and_stop_the_session(service, platform):
    service.start()
    assert wait_for(lambda: service.snapshot()['state'] == 'fishing')

    platform.keys_down = {'f8'}
    assert wait_for(lambda: service.snapshot()['state'] == 'paused')
    time.sleep(0.5)  # holding the key down must not toggle again
    assert service.snapshot()['state'] == 'paused'

    platform.keys_down = set()
    time.sleep(0.5)  # long enough for the poller to see the key come up, even on a busy machine
    platform.keys_down = {'f8'}
    assert wait_for(lambda: service.snapshot()['state'] == 'fishing')

    platform.keys_down = {'f9'}
    assert wait_for(lambda: not service.running)
    assert service.snapshot()['message'] == 'Stopped with F9.'


def test_an_error_in_the_loop_is_reported_and_the_service_survives(service, platform):
    class BrokenControls:
        def press(self, key):
            raise RuntimeError('keyboard unplugged')

    platform.create_controls = BrokenControls
    assert service.start() == []
    assert wait_for(lambda: not service.running)

    snapshot = service.snapshot()
    assert snapshot['message'] == 'Stopped because something went wrong: keyboard unplugged'
    assert snapshot['log'][-1]['level'] == 'error'
    assert snapshot['state'] == 'idle'


def test_stop_pressed_while_the_model_is_still_loading_is_not_lost(service, platform):
    release = threading.Event()
    real_controls = platform.create_controls

    def slow_controls():
        release.wait(10)
        return real_controls()

    platform.create_controls = slow_controls
    assert service.start() == []
    assert service.snapshot()['state'] == 'starting'

    service.stop('Stopped.')
    release.set()

    assert wait_for(lambda: not service.running)
    assert platform.game.events == []
    assert service.snapshot()['message'] == 'Stopped.'


def test_pause_pressed_while_the_model_is_still_loading_is_not_lost(service, platform):
    release = threading.Event()
    real_controls = platform.create_controls

    def slow_controls():
        release.wait(10)
        return real_controls()

    platform.create_controls = slow_controls
    assert service.start() == []
    service.set_paused(True)
    release.set()

    assert wait_for(lambda: service.snapshot()['state'] == 'paused')
    time.sleep(1.5)
    assert platform.game.events == []


def test_snapshot_only_returns_log_lines_after_the_cursor(service):
    service.log('one')
    cursor = service.snapshot()['log_cursor']
    service.log('two')

    assert [entry['message'] for entry in service.snapshot(since=cursor)['log']] == ['two']


def test_snapshot_describes_the_platform_and_settings(service):
    snapshot = service.snapshot()

    assert snapshot['platform']['system'] == 'demo'
    assert snapshot['settings']['fishing_key'] == 'f'
    assert snapshot['problems'] == []
    assert 'f8' in snapshot['hotkeys'] and 'f' in snapshot['keys']
    assert snapshot['preview'] == ''


def test_check_setup_takes_a_picture_and_reports_on_it(service):
    assert service.preview_jpeg() is None

    result = service.check_setup()

    assert result['ok'] and result['in_front'] and not result['blank']
    assert (result['width'], result['height']) == (640, 360)
    assert result['best_score'] < 0.2
    assert service.preview_jpeg()[:2] == b'\xff\xd8'
    assert service.snapshot()['preview'].startswith('still-')


def test_check_setup_is_refused_while_fishing(service):
    service.start()
    assert wait_for(lambda: service.snapshot()['state'] == 'fishing')

    assert service.check_setup()['ok'] is False


def test_check_setup_explains_a_missing_game(service, platform):
    platform.window_missing = True

    result = service.check_setup()

    assert result == {'ok': False, 'message': 'World of Warcraft does not seem to be open. Start the game, then try again.'}


def test_preview_is_live_while_fishing_and_kept_afterwards(service):
    service.start()
    assert wait_for(lambda: service.snapshot()['preview'].startswith('live-'))
    assert service.preview_jpeg()[:2] == b'\xff\xd8'

    # Every look gets a new tag, otherwise the page would keep showing an old picture.
    tags = set()
    assert wait_for(lambda: tags.add(service.snapshot()['preview']) or len(tags) >= 5)
    assert all(tag.startswith('live-') for tag in tags)

    service.stop()
    service.wait(10)

    assert service.snapshot()['preview'].startswith('still-')
    assert service.preview_jpeg()[:2] == b'\xff\xd8'


def test_the_shipped_demo_platform_has_the_interface_the_service_needs():
    module = platforms.load(demo=True)

    for name in ('SYSTEM', 'LABEL', 'SETUP_NOTES', 'find_game_window', 'key_is_down',
                 'create_controls', 'create_grabber'):
        assert hasattr(module, name)
