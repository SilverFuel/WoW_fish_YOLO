"""Spotting a bite by movement, against a moving scene made from the real screenshot (tests/lake.py).

The scene's movement is made up, so these show that the mechanics work and how much room there
is, not that it works in the game.
"""
import pytest

from fishbot import motion
from fishbot.motion import BobberWatcher
from tests.lake import Lake

BEFORE = 4


def fish(lake, watcher, start, spot, bite_after, rate=5.0, until=11.0, after_cast=None):
    """Make one cast and watch it. Returns what happened, as a dictionary."""
    for picture in range(BEFORE):
        watcher.before_cast(lake.frame(start - (BEFORE - picture) / rate))
    lake.cast(start, spot=spot, bite_after=bite_after)
    if after_cast is not None:
        after_cast(lake)
    watcher.cast_started()

    seen = {'found_at': None, 'bobber': None, 'bite_at': None, 'strongest_while_floating': 0.0, 'phases': []}
    seconds = 1.0
    while seconds < until:
        movement = watcher.look(lake.frame(start + seconds), seconds)
        if movement.phase not in seen['phases']:
            seen['phases'].append(movement.phase)
        if movement.bobber is not None and seen['found_at'] is None:
            seen['found_at'], seen['bobber'] = seconds, movement.bobber
        if movement.bite:
            seen['bite_at'] = seconds
            break
        if bite_after is None or seconds < bite_after - 0.05:
            seen['strongest_while_floating'] = max(seen['strongest_while_floating'], movement.strength)
        seconds += 1 / rate
    return seen


def close_to(found, wanted, size):
    return abs(found[0] - wanted[0]) <= 0.02 * size[0] and abs(found[1] - wanted[1]) <= 0.02 * size[1]


@pytest.mark.parametrize('size, rate, ripple', [
    ((1918, 1080), 5.0, 5.0),      # as in the screenshot
    ((1918, 1080), 3.5, 5.0),      # a slow computer
    ((1280, 720), 5.0, 5.0),       # a small window
    ((1918, 1080), 5.0, 15.0),     # water three times as rough
])
def test_it_finds_the_bobber_and_then_the_bite(size, rate, ripple):
    lake = Lake(seed=1, size=size, ripple=ripple)
    spot = lake.random_spot()

    seen = fish(lake, BobberWatcher(), 10.0, spot, bite_after=5.5, rate=rate)

    assert seen['found_at'] is not None and seen['found_at'] <= 3.0
    assert close_to(seen['bobber'], lake.on_screen(spot), size)
    assert seen['bite_at'] is not None and 5.5 <= seen['bite_at'] <= 5.5 + 0.8
    assert seen['strongest_while_floating'] < 0.6     # floating, it stays well below what counts as a bite


def test_a_floating_bobber_is_never_taken_for_a_bite():
    lake = Lake(seed=2)

    seen = fish(lake, BobberWatcher(), 10.0, lake.random_spot(), bite_after=None, until=14.0)

    assert seen['found_at'] is not None
    assert seen['bite_at'] is None
    assert seen['strongest_while_floating'] < 0.6


def test_another_anglers_bite_is_not_ours():
    # Their bobber is already out when we cast, well away from ours, and it bites while ours floats.
    lake = Lake(seed=3)
    spot = lake.random_spot()
    lake.other_angler = (spot[0] - 420 if spot[0] > 1100 else spot[0] + 420, spot[1] + 40, 2.0, 13.6)

    seen = fish(lake, BobberWatcher(), 10.0, spot, bite_after=6.5)

    assert close_to(seen['bobber'], lake.on_screen(spot), lake.size)
    assert seen['bite_at'] is not None and seen['bite_at'] >= 6.5     # theirs at 3.6 s was ignored


def test_a_bite_that_takes_the_bobber_right_under_is_still_a_bite():
    # Out of sight for a moment, with spray where it was: that must not read as "the bobber is gone".
    lake = Lake(seed=8)
    lake.dips_under = True

    seen = fish(lake, BobberWatcher(), 10.0, lake.random_spot(), bite_after=5.5)

    assert seen['bite_at'] is not None and 5.5 <= seen['bite_at'] <= 6.3
    assert 'gone' not in seen['phases']


def test_a_bobber_pulled_in_with_no_fish_is_not_a_bite():
    lake = Lake(seed=4)

    def pulled_in(lake):
        lake.pulled_in_at = 16.0

    seen = fish(lake, BobberWatcher(), 10.0, lake.random_spot(), bite_after=None, after_cast=pulled_in)

    assert seen['bite_at'] is None
    assert seen['phases'][-1] == 'gone'


def test_a_bobber_that_fades_out_is_not_a_bite_either():
    lake = Lake(seed=4)
    watcher = BobberWatcher()

    def fades(lake):
        lake.pulled_in_at, lake.fades_over = 16.0, 0.7

    seen = fish(lake, watcher, 10.0, lake.random_spot(), bite_after=None, after_cast=fades)

    assert seen['bite_at'] is None
    assert watcher.pulled_in
    assert watcher.peak_strength < 0.6     # its going is not counted as "nearly a bite"


def test_the_last_casts_bobber_still_floating_is_not_mistaken_for_the_new_one():
    lake = Lake(seed=5)
    watcher = BobberWatcher()
    first, second = (800, 700), (1380, 820)

    fish(lake, watcher, 10.0, first, bite_after=None, until=4.0)       # no fish yet; its bobber stays out
    seen = fish(lake, watcher, 20.0, second, bite_after=5.5)

    assert close_to(seen['bobber'], lake.on_screen(second), lake.size)
    assert seen['bite_at'] is not None


def test_a_new_bobber_landing_almost_where_the_old_one_floated_is_still_found():
    lake = Lake(seed=6)
    watcher = BobberWatcher()

    fish(lake, watcher, 10.0, (980, 795), bite_after=None, until=4.0)
    seen = fish(lake, watcher, 20.0, (940, 760), bite_after=5.5)

    assert seen['found_at'] is not None
    assert close_to(seen['bobber'], lake.on_screen((940, 760)), lake.size)
    assert seen['bite_at'] is not None


def test_a_flash_across_the_whole_picture_is_not_a_bite():
    lake = Lake(seed=7)
    lake.flash_at = 14.0

    seen = fish(lake, BobberWatcher(), 10.0, lake.random_spot(), bite_after=None, until=8.0)

    assert seen['bite_at'] is None


def test_without_pictures_from_before_the_cast_it_says_nothing():
    lake = Lake(seed=1)
    watcher = BobberWatcher()
    lake.cast(10.0, bite_after=3.0)
    watcher.cast_started()

    assert not watcher.ready
    assert watcher.look(lake.frame(13.2), 3.2) is motion.NOTHING_YET


def test_it_gives_up_looking_for_a_bobber_that_never_shows():
    lake = Lake(seed=1)
    watcher = BobberWatcher()
    for picture in range(BEFORE):
        watcher.before_cast(lake.frame(9.0 + picture * 0.2))
    watcher.cast_started()     # the cast never happens in the scene: no bobber lands

    phases = [watcher.look(lake.frame(10.0 + step * 0.4), 1.0 + step * 0.4).phase for step in range(18)]

    assert phases[0] == 'looking' and phases[-1] == 'lost'
    assert not watcher.found
