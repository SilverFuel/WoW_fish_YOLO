import json
import threading

import pytest

from fishbot import keys
from fishbot.settings import Settings, SettingsStore, apply_changes, problems_before_start


def change(changes, current=Settings(), system='windows'):
    return apply_changes(current, changes, system)


def test_defaults_cannot_start_until_a_fishing_key_is_set():
    assert problems_before_start(Settings()) == ['Pick your fishing key first.']
    assert problems_before_start(Settings(fishing_key='f')) == []


def test_lure_needs_a_key_only_when_it_is_switched_on():
    assert problems_before_start(Settings(fishing_key='f', lure_enabled=True)) == [
        'Pick your lure key, or switch the lure off.']
    assert problems_before_start(Settings(fishing_key='f', lure_enabled=True, lure_key='l')) == []


def test_safeguards_are_on_by_default():
    defaults = Settings()

    assert defaults.pause_on_mouse_move is True
    assert defaults.stop_after_misses == 5
    assert change({'pause_on_mouse_move': False})[1] == {}
    assert list(change({'pause_on_mouse_move': 'on'})[1]) == ['pause_on_mouse_move']
    assert list(change({'practice_mode': True})[1]) == ['practice_mode']  # practice is a button now, not a setting


def test_valid_changes_are_applied_and_normalised():
    settings, errors = change({'fishing_key': ' F ', 'cast_seconds': '30', 'confidence': 0.7,
                               'scan_area': 'center50', 'lure_enabled': True, 'stop_hotkey': 'F10'})

    assert errors == {}
    assert (settings.fishing_key, settings.cast_seconds, settings.confidence) == ('f', 30, 0.7)
    assert (settings.scan_area, settings.lure_enabled, settings.stop_hotkey) == ('center50', True, 'f10')


@pytest.mark.parametrize('changes, field', [
    ({'fishing_key': 'fishing'}, 'fishing_key'),
    ({'fishing_key': 'é'}, 'fishing_key'),
    ({'cast_seconds': 2}, 'cast_seconds'),
    ({'cast_seconds': 'soon'}, 'cast_seconds'),
    ({'cast_seconds': 20.5}, 'cast_seconds'),
    ({'cast_seconds': True}, 'cast_seconds'),
    ({'confidence': 0.2}, 'confidence'),
    ({'confidence': 'nan'}, 'confidence'),
    ({'checks_per_second': 100}, 'checks_per_second'),
    ({'cpu_threads': 0}, 'cpu_threads'),
    ({'scan_area': 'tiny'}, 'scan_area'),
    ({'pause_hotkey': 'a'}, 'pause_hotkey'),
    ({'lure_enabled': 'yes'}, 'lure_enabled'),
    ({'assistant_url': 'localhost:11434'}, 'assistant_url'),
    ({'assistant_url': 'file:///etc/passwd'}, 'assistant_url'),
    ({'assistant_url': 'http://localhost:abc/v1'}, 'assistant_url'),
    ({'assistant_url': 'http://local host:11434/v1'}, 'assistant_url'),
    ({'cast_seconds': 10 ** 400}, 'cast_seconds'),
    ({'confidence': '9' * 400}, 'confidence'),
    ({'assistant_model': ''}, 'assistant_model'),
    ({'not_a_setting': 1}, 'not_a_setting'),
    ({'fishing_key': None}, 'fishing_key'),
    ({'stop_after_minutes': [5]}, 'stop_after_minutes'),
    ({'stop_after_catches': -1}, 'stop_after_catches'),
    ({'spot_bites_by': 'sound'}, 'spot_bites_by'),
    ({'stop_after_catches': 10001}, 'stop_after_catches'),
])
def test_invalid_values_are_rejected_and_leave_the_setting_alone(changes, field):
    settings, errors = change(changes)

    assert list(errors) == [field]
    assert settings == Settings()


def test_a_bad_field_does_not_block_the_good_ones():
    settings, errors = change({'fishing_key': 'f', 'cast_seconds': 999})

    assert settings.fishing_key == 'f'
    assert settings.cast_seconds == 20
    assert list(errors) == ['cast_seconds']


def test_fishing_key_cannot_be_a_hotkey():
    settings, errors = change({'fishing_key': 'f8'})

    assert settings.fishing_key == ''
    assert 'reserved' in errors['fishing_key']


def test_a_hotkey_cannot_take_the_fishing_key():
    current = Settings(fishing_key='f5')

    settings, errors = change({'pause_hotkey': 'f5'}, current)

    assert settings.pause_hotkey == 'f8'
    assert 'already the fishing key' in errors['pause_hotkey']


def test_pause_and_stop_need_different_keys():
    settings, errors = change({'stop_hotkey': 'f8'})

    assert settings.stop_hotkey == 'f9'
    assert list(errors) == ['stop_hotkey']


def test_swapping_both_hotkeys_in_one_change_is_allowed():
    settings, errors = change({'pause_hotkey': 'f9', 'stop_hotkey': 'f8'})

    assert errors == {}
    assert (settings.pause_hotkey, settings.stop_hotkey) == ('f9', 'f8')


def test_a_rejected_change_cannot_leave_a_clash_behind():
    # Fishing is on F5. Moving pause to F5 is only fine if fishing really moves away, and it cannot
    # move to F9 because that is the stop key. Neither change may be half applied.
    current = Settings(fishing_key='f5')

    settings, errors = change({'pause_hotkey': 'f5', 'fishing_key': 'f9'}, current)

    assert settings == current
    assert set(errors) == {'pause_hotkey', 'fishing_key'}


def test_moving_the_fishing_key_onto_the_lure_key_is_refused_even_with_other_bad_changes():
    current = Settings(fishing_key='f', lure_enabled=True, lure_key='g')

    settings, errors = change({'fishing_key': 'g', 'lure_key': 'f8'}, current)

    assert settings == current
    assert set(errors) == {'fishing_key', 'lure_key'}


def test_fishing_and_lure_keys_can_be_swapped_in_one_change():
    current = Settings(fishing_key='f', lure_key='g')

    settings, errors = change({'fishing_key': 'g', 'lure_key': 'f'}, current)

    assert errors == {}
    assert (settings.fishing_key, settings.lure_key) == ('g', 'f')


def test_fishing_and_lure_need_different_keys():
    settings, errors = change({'lure_key': 'f'}, Settings(fishing_key='f'))

    assert settings.lure_key == ''
    assert list(errors) == ['lure_key']


def test_numpad_keys_are_offered_on_windows_only():
    assert change({'fishing_key': 'num1'}, system='windows')[1] == {}
    assert list(change({'fishing_key': 'num1'}, system='macos')[1]) == ['fishing_key']
    assert 'num1' not in keys.pressable_keys('macos')


def test_function_keys_cannot_be_bound_on_macos():
    # A function key pressed by a program makes macOS treat later letters as fn shortcuts.
    assert change({'fishing_key': 'f5'}, system='windows')[1] == {}
    assert list(change({'fishing_key': 'f5'}, system='macos')[1]) == ['fishing_key']
    assert list(change({'lure_key': 'f2'}, system='macos')[1]) == ['lure_key']
    assert change({'fishing_key': 'f'}, system='macos')[1] == {}
    assert change({'pause_hotkey': 'f5'}, system='macos')[1] == {}  # watching a function key is fine


def test_assistant_url_loses_its_trailing_slash():
    settings, errors = change({'assistant_url': 'http://localhost:1234/v1/'})

    assert errors == {}
    assert settings.assistant_url == 'http://localhost:1234/v1'


def test_store_saves_changes_and_loads_them_back(tmp_path):
    path = tmp_path / 'nested' / 'settings.json'
    store = SettingsStore(path, 'windows')

    settings, errors = store.update({'fishing_key': 'f', 'cast_seconds': 25})

    assert errors == {}
    assert json.loads(path.read_text())['cast_seconds'] == 25
    assert SettingsStore(path, 'windows').settings == settings


def test_store_ignores_a_corrupt_file(tmp_path):
    path = tmp_path / 'settings.json'
    path.write_text('{ not json')

    assert SettingsStore(path, 'windows').settings == Settings()


def test_store_keeps_good_values_from_a_file_with_some_bad_ones(tmp_path):
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'fishing_key': 'f', 'cast_seconds': 9999, 'left_over': True}))

    settings = SettingsStore(path, 'windows').settings

    assert settings.fishing_key == 'f'
    assert settings.cast_seconds == 20


def test_store_keeps_every_change_when_many_arrive_at_once(tmp_path):
    path = tmp_path / 'settings.json'
    store = SettingsStore(path, 'windows')
    failures = []

    def writer(changes):
        try:
            for _ in range(40):
                store.update(changes)
                store.update({name: value + 1 for name, value in changes.items()})
        except Exception as error:  # a failed save must not pass silently
            failures.append(error)

    threads = [threading.Thread(target=writer, args=(changes,)) for changes in (
        {'cast_seconds': 30}, {'lure_minutes': 20}, {'checks_per_second': 8}, {'stop_after_minutes': 60})]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    saved = json.loads(path.read_text())
    assert (saved['cast_seconds'], saved['lure_minutes'], saved['checks_per_second'], saved['stop_after_minutes']) == (31, 21, 9, 61)
    assert list(tmp_path.iterdir()) == [path]  # no temporary files left behind


def test_store_retries_when_the_file_is_briefly_locked(tmp_path, monkeypatch):
    from pathlib import Path

    path = tmp_path / 'settings.json'
    store = SettingsStore(path, 'windows')
    real_replace, refusals = Path.replace, []

    def locked_twice(self, target):
        if len(refusals) < 2:
            refusals.append(1)
            raise PermissionError(13, 'Access is denied')
        return real_replace(self, target)

    monkeypatch.setattr(Path, 'replace', locked_twice)
    store.update({'cast_seconds': 25})

    assert len(refusals) == 2
    assert json.loads(path.read_text())['cast_seconds'] == 25


def test_store_does_not_rewrite_the_file_when_nothing_changed(tmp_path):
    path = tmp_path / 'settings.json'
    store = SettingsStore(path, 'windows')

    store.update({'cast_seconds': 20})

    assert not path.exists()


def test_a_range_is_explained_in_the_units_the_person_types():
    # "How sure it must be" is typed as a percentage and stored as a fraction.
    assert change({'confidence': 0.99})[1] == {'confidence': 'must be between 50% and 95%'}
    assert change({'cast_seconds': 2})[1] == {'cast_seconds': 'must be between 5 and 60'}


def test_a_bite_is_spotted_both_ways_unless_chosen_otherwise():
    assert Settings().spot_bites_by == 'both'
    for choice in ('both', 'movement', 'look'):
        settings, errors = change({'spot_bites_by': choice})
        assert errors == {} and settings.spot_bites_by == choice
