"""Tests for the platform layer that can run anywhere, plus smoke tests that run only on their own system."""
import sys

import pytest

from fishbot import keys, platforms
from fishbot.platforms import macos


def window(owner, number, pid, width, height, x=0, y=0, layer=0, name='Main'):
    return {'kCGWindowOwnerName': owner, 'kCGWindowNumber': number, 'kCGWindowOwnerPID': pid, 'kCGWindowName': name,
            'kCGWindowLayer': layer, 'kCGWindowBounds': {'X': x, 'Y': y, 'Width': width, 'Height': height}}


GAME = window('World of Warcraft', 11, 500, 1728, 1117, y=38)
BROWSER = window('Safari', 12, 600, 1400, 900, x=100, y=80)
MENU_BAR = window('Window Server', 1, 100, 1728, 38, layer=24)


def test_mac_picks_the_games_largest_normal_window():
    tooltip = window('World of Warcraft', 13, 500, 180, 60)
    overlay = window('World of Warcraft', 14, 500, 1728, 1117, layer=25)

    assert macos.pick_game_window([MENU_BAR, tooltip, overlay, BROWSER, GAME]) is GAME


def test_mac_prefers_a_titled_window_over_a_larger_untitled_helper():
    # Seen on a real Mac: an application can own an untitled window the size of the screen.
    windowed_game = window('World of Warcraft', 31, 500, 1280, 720, x=100, y=100, name='World of Warcraft')
    helper = window('World of Warcraft', 32, 500, 1728, 1117, name='')

    assert macos.pick_game_window([helper, windowed_game]) is windowed_game


def test_mac_uses_any_window_when_titles_are_hidden():
    # Without the Screen Recording permission macOS reports no window titles at all.
    untitled = window('World of Warcraft', 33, 500, 1280, 720, name='')
    smaller = window('World of Warcraft', 34, 500, 400, 300, name='')

    assert macos.pick_game_window([smaller, untitled]) is untitled


def test_mac_matches_the_classic_client_too():
    classic = window('World of Warcraft Classic', 21, 700, 1280, 720)

    assert macos.pick_game_window([BROWSER, classic]) is classic


def test_mac_finds_nothing_when_the_game_is_not_running():
    lookalike = window('Safari', 12, 600, 1400, 900)  # a browser tab about the game does not count

    assert macos.pick_game_window([MENU_BAR, lookalike]) is None
    assert macos.pick_game_window([]) is None


def test_mac_frontmost_is_the_first_normal_window_in_the_list():
    assert macos.frontmost_pid([MENU_BAR, GAME, BROWSER]) == 500
    assert macos.frontmost_pid([MENU_BAR, BROWSER, GAME]) == 600
    assert macos.frontmost_pid([MENU_BAR]) is None


def test_mac_region_uses_whole_points():
    assert macos.region_of(window('World of Warcraft', 1, 1, 1727.5, 1116.5, x=0.5, y=38.0)) == {
        'left': 0, 'top': 38, 'width': 1727, 'height': 1116}


def test_hotkey_tables_cover_every_hotkey():
    assert set(keys.WINDOWS_VK) == set(keys.HOTKEYS) == set(keys.MAC_KEYCODES)
    assert keys.WINDOWS_VK['f1'] == 0x70 and keys.WINDOWS_VK['f12'] == 0x7B
    assert len(set(keys.MAC_KEYCODES.values())) == 12


def test_pressable_keys_never_include_duplicates():
    for system in ('windows', 'macos', 'demo'):
        names = keys.pressable_keys(system)
        assert len(names) == len(set(names))
        assert all(name == name.lower() for name in names)


def test_demo_platform_loads_everywhere():
    demo = platforms.load(demo=True)

    assert demo.SYSTEM == 'demo'
    assert demo.find_game_window().capture_region() == demo.REGION
    assert demo.key_is_down('f8') is False


@pytest.mark.skipif(sys.platform not in ('win32', 'darwin'), reason='needs Windows or macOS')
def test_real_platform_reports_a_missing_game_cleanly():
    # On a build machine the game is not running: the lookup must say so rather than crash.
    platform = platforms.load()

    with pytest.raises(platforms.GameWindowNotFound):
        platform.find_game_window()


@pytest.mark.skipif(sys.platform not in ('win32', 'darwin'), reason='needs Windows or macOS')
def test_real_platform_can_poll_every_hotkey():
    platform = platforms.load()

    assert [platform.key_is_down(name) for name in keys.HOTKEYS] == [False] * 12


@pytest.mark.skipif(sys.platform not in ('win32', 'darwin'), reason='needs Windows or macOS')
def test_real_platform_can_press_every_key_it_offers():
    # pyautogui silently ignores names it has no key code for, so every offered name must have one.
    platform = platforms.load()
    controls = platform.create_controls()
    mapping = controls.platformModule.keyboardMapping

    missing = [name for name in keys.pressable_keys(platform.SYSTEM) if mapping.get(name) is None]

    assert missing == []
    assert all(callable(getattr(controls, name)) for name in ('press', 'moveTo', 'click'))


@pytest.mark.skipif(sys.platform in ('win32', 'darwin'), reason='only meaningful on unsupported systems')
def test_unsupported_system_gets_a_clear_message():
    with pytest.raises(platforms.UnsupportedSystem, match='--demo'):
        platforms.load()
