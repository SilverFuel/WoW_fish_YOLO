"""The background service, driven through the simulated game with the real detector."""
import time

import pytest

from fishbot import platforms
from fishbot.platforms import GameWindowNotFound, demo
from fishbot.service import BotService
from fishbot.settings import SettingsStore


class DemoPlatform:
    """The demo platform with its own game, so tests do not share state, and scriptable hotkeys."""

    SYSTEM, LABEL, SETUP_NOTES = demo.SYSTEM, demo.LABEL, demo.SETUP_NOTES

    def __init__(self, bite_after=(0.3, 0.5)):
        self.game = demo.DemoGame(bite_after=bite_after)
        self.keys_down = set()
        self.window_missing = False

    def find_game_window(self):
        if self.window_missing:
            raise GameWindowNotFound('No World of Warcraft game window was found. Is the game running?')
        return demo.DemoWindow()

    def key_is_down(self, name):
        return name in self.keys_down

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

    assert service.start() == ['Set the key your fishing spell is bound to.']
    assert not service.running


def test_will_not_start_when_the_game_is_not_running(service, platform):
    platform.window_missing = True

    assert service.start() == ['No World of Warcraft game window was found. Is the game running?']
    assert service.snapshot()['state'] == 'idle'


def test_fishes_end_to_end_with_the_real_detector(service, platform):
    assert service.start() == []
    assert service.start() == ['The bot is already running.']

    assert wait_for(lambda: service.snapshot()['stats']['looted'] >= 1)
    running = service.snapshot()
    service.stop()
    service.wait(10)
    stopped = service.snapshot()

    kinds = [event[0] for event in platform.game.events]
    assert kinds[:3] == ['press', 'move', 'click']
    assert platform.game.events[0] == ('press', 'f')
    # The click lands on the synthetic splash, which sits near (345, 236) in the demo frame.
    assert platform.game.events[1][1] == pytest.approx(345, abs=6)
    assert platform.game.events[1][2] == pytest.approx(236, abs=6)
    assert running['running'] and running['state'] == 'fishing'
    assert running['stats']['inference_ms'] > 0
    assert not stopped['running'] and stopped['state'] == 'idle'
    assert stopped['message'] == 'Stopped.'
    assert stopped['stats']['looted'] >= 1  # the last session's numbers stay visible


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
    assert snapshot['message'] == 'Stopped by an error: keyboard unplugged'
    assert snapshot['log'][-1]['level'] == 'error'
    assert snapshot['state'] == 'idle'


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

    assert result == {'ok': False, 'message': 'No World of Warcraft game window was found. Is the game running?'}


def test_preview_is_live_while_fishing_and_kept_afterwards(service):
    service.start()
    assert wait_for(lambda: service.snapshot()['preview'].startswith('live-'))
    assert service.preview_jpeg()[:2] == b'\xff\xd8'

    service.stop()
    service.wait(10)

    assert service.snapshot()['preview'].startswith('still-')
    assert service.preview_jpeg()[:2] == b'\xff\xd8'


def test_the_shipped_demo_platform_has_the_interface_the_service_needs():
    module = platforms.load(demo=True)

    for name in ('SYSTEM', 'LABEL', 'SETUP_NOTES', 'find_game_window', 'key_is_down',
                 'create_controls', 'create_grabber'):
        assert hasattr(module, name)
