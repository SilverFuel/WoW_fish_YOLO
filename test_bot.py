"""Tests for the fishing loop. They use stand-ins for the game, so they run on any OS: pytest test_bot.py"""
import pytest

import bot
from bot import Config, FishingBot

REGION = {'left': 100, 'top': 50, 'width': 1920, 'height': 1080}
SPLASH = (640, 360)
KEYS = ['f', 'l', '1', 'f5', 'f8', 'f9', 'space']


class FakeClock:
    """Time only moves when something sleeps on it, so tests run instantly."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = 0
        self.on_sleep = lambda count: None

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        self.sleeps += 1
        assert self.sleeps < 200_000, 'the bot is idling forever'
        self.on_sleep(self.sleeps)


class FakeWindow:
    def __init__(self):
        self.open = True
        self.foreground = True
        self.region = REGION
        self.focus_calls = 0

    def exists(self):
        return self.open

    def is_foreground(self):
        return self.open and self.foreground

    def focus(self):
        self.focus_calls += 1

    def capture_region(self):
        return self.region


class FakeControls:
    """Records input the same way the bot calls pyautogui."""

    def __init__(self, clock):
        self.clock = clock
        self.events = []
        self.on_event = lambda event: None

    def _record(self, *event):
        self.events.append(event)
        self.on_event(event)

    def press(self, key):
        self._record('press', key, self.clock.now)

    def moveTo(self, x, y, duration):
        self._record('move', x, y)

    def click(self, button):
        self._record('click', button)

    def count(self, kind):
        return sum(1 for event in self.events if event[0] == kind)

    def presses(self, key):
        return [event[2] for event in self.events if event[:2] == ('press', key)]


class FakeDetector:
    """Each frame costs ``frame_time`` seconds and returns whatever ``on_frame`` says."""

    def __init__(self, clock, on_frame, frame_time=0.25):
        self.clock = clock
        self.on_frame = on_frame
        self.frame_time = frame_time
        self.frames = 0
        self.regions = []

    def find_splash(self, region):
        self.frames += 1
        self.regions.append(region)
        self.clock.sleep(self.frame_time)
        return self.on_frame(self.frames)


class Game:
    def __init__(self, config=Config('f'), on_frame=lambda frame: SPLASH):
        self.clock = FakeClock()
        self.window = FakeWindow()
        self.controls = FakeControls(self.clock)
        self.detector = FakeDetector(self.clock, on_frame)
        self.bot = FishingBot(config, self.window, self.detector, self.controls,
                              clock=self.clock, idle=self.clock.sleep)

    def stop_after(self, kind, count):
        def check(event):
            if self.controls.count(kind) >= count:
                self.bot.stop()

        self.controls.on_event = check


def test_keeps_fishing_far_past_the_old_recursion_limit():
    # The original start() -> cast() -> restart() -> start() chain died after 333 casts.
    game = Game()
    game.stop_after('click', 2000)

    game.bot.run()

    assert game.bot.loot_attempts == 2000
    assert game.controls.count('click') == 2000
    assert len(game.controls.presses('f')) == 2000


def test_one_catch_presses_the_key_then_right_clicks_the_splash():
    game = Game()
    game.stop_after('click', 1)

    game.bot.run()

    assert [event[:3] for event in game.controls.events] == [
        ('press', 'f', 0.0), ('move', *SPLASH), ('click', 'right')]
    assert game.window.focus_calls == 1


def test_sends_nothing_while_another_window_is_in_front():
    game = Game()
    game.window.foreground = False
    game.clock.on_sleep = lambda count: count >= 50 and game.bot.stop()

    game.bot.run()

    assert game.controls.events == []
    assert game.detector.frames == 0


def test_resumes_when_the_game_comes_back_to_the_front():
    game = Game()
    game.window.foreground = False

    def bring_back(count):
        if count == 50:
            game.window.foreground = True

    game.clock.on_sleep = bring_back
    game.stop_after('click', 1)

    game.bot.run()

    assert game.controls.count('click') == 1
    assert game.window.focus_calls == 1  # focus is requested once, never stolen back


def test_focus_lost_when_the_splash_appears_means_no_mouse_input():
    def lose_focus(frame):
        game.window.foreground = False
        return SPLASH

    game = Game(on_frame=lose_focus)
    game.clock.on_sleep = lambda count: count >= 200 and game.bot.stop()

    game.bot.run()

    assert game.controls.count('move') == 0
    assert game.controls.count('click') == 0
    assert game.bot.loot_attempts == 0


def test_focus_lost_after_the_mouse_moved_means_no_click():
    game = Game()

    def lose_focus_on_move(event):
        if event[0] == 'move':
            game.window.foreground = False

    game.controls.on_event = lose_focus_on_move
    game.clock.on_sleep = lambda count: count >= 200 and game.bot.stop()

    game.bot.run()

    assert game.controls.count('move') == 1
    assert game.controls.count('click') == 0


def test_pause_blocks_input_until_resumed():
    game = Game()
    game.bot.toggle_pause()
    sent_while_paused = []

    def resume_later(count):
        if count == 30:
            sent_while_paused.extend(game.controls.events)
            game.bot.toggle_pause()

    game.clock.on_sleep = resume_later
    game.stop_after('click', 1)

    game.bot.run()

    assert sent_while_paused == []
    assert game.controls.count('click') == 1


def test_pausing_mid_cast_abandons_that_cast_without_clicking():
    def pause_on_third_frame(frame):
        if frame == 3:
            game.bot.toggle_pause()
        return None

    game = Game(on_frame=pause_on_third_frame)
    game.clock.on_sleep = lambda count: count >= 200 and game.bot.stop()

    game.bot.run()

    assert game.detector.frames == 3
    assert len(game.controls.presses('f')) == 1
    assert game.controls.count('click') == 0


def test_a_cast_with_no_splash_times_out_and_recasts():
    game = Game(on_frame=lambda frame: None)
    game.stop_after('press', 3)

    game.bot.run()

    first, second, third = game.controls.presses('f')
    assert bot.CAST_DURATION_SEC <= second - first <= bot.CAST_DURATION_SEC + 3
    assert bot.CAST_DURATION_SEC <= third - second <= bot.CAST_DURATION_SEC + 3
    assert game.controls.count('click') == 0


def test_lure_is_applied_first_and_again_only_after_it_expires():
    game = Game(config=Config('f', 'l', 600), on_frame=lambda frame: None)

    def stop_on_second_lure(event):
        if len(game.controls.presses('l')) == 2:
            game.bot.stop()

    game.controls.on_event = stop_on_second_lure

    game.bot.run()

    first_lure, second_lure = game.controls.presses('l')
    casts = game.controls.presses('f')
    assert game.controls.events[0][:2] == ('press', 'l')
    assert casts[0] - first_lure == bot.LURE_APPLY_WAIT_SEC
    assert second_lure - first_lure > 600
    assert len(casts) > 20  # many casts happened on the first lure


def test_focus_lost_while_the_lure_is_applied_means_no_cast():
    game = Game(config=Config('f', 'l', 600))

    def lose_focus_after_lure(event):
        if event[:2] == ('press', 'l'):
            game.window.foreground = False

    game.controls.on_event = lose_focus_after_lure
    game.clock.on_sleep = lambda count: count >= 200 and game.bot.stop()

    game.bot.run()

    assert [event[:2] for event in game.controls.events] == [('press', 'l')]


def test_stops_by_itself_when_the_game_window_closes():
    def close_on_third_frame(frame):
        if frame == 3:
            game.window.open = False
        return None

    game = Game(on_frame=close_on_third_frame)

    game.bot.run()  # returns without anyone calling stop()

    assert len(game.controls.presses('f')) == 1
    assert game.controls.count('click') == 0


def test_waits_instead_of_casting_while_the_window_is_minimised():
    game = Game()
    game.window.region = None
    game.clock.on_sleep = lambda count: count >= 50 and game.bot.stop()

    game.bot.run()

    assert game.controls.events == []


def test_capture_region_is_read_again_for_every_frame():
    moved = {'left': 300, 'top': 200, 'width': 1280, 'height': 720}

    def move_window(frame):
        game.window.region = moved
        return SPLASH if frame == 2 else None

    game = Game(on_frame=move_window)
    game.stop_after('click', 1)

    game.bot.run()

    assert game.detector.regions == [REGION, moved]


def test_quit_during_a_cast_stops_before_any_click():
    def quit_on_second_frame(frame):
        if frame == 2:
            game.bot.stop()
        return SPLASH if frame >= 2 else None

    game = Game(on_frame=quit_on_second_frame)

    game.bot.run()

    assert game.controls.count('click') == 0


@pytest.mark.parametrize('raw, expected', [('f', 'f'), ('  F ', 'f'), ('F5', 'f5'), ('Space', 'space')])
def test_validate_key_normalises_known_keys(raw, expected):
    assert bot.validate_key(raw, KEYS) == expected


@pytest.mark.parametrize('raw', ['', 'fishing', 'ff', 'f8', 'F9'])
def test_validate_key_rejects_keys_the_bot_cannot_or_must_not_press(raw):
    with pytest.raises(ValueError):
        bot.validate_key(raw, KEYS)


def scripted(*answers):
    remaining = list(answers)
    return lambda prompt: remaining.pop(0)


def test_configure_without_lure():
    assert bot.configure(KEYS, scripted(' F ', 'n')) == Config('f')


def test_configure_asks_again_instead_of_crashing_on_bad_answers():
    answers = scripted('fishing', 'f', 'Y', 'bogus', 'l', 'ten', '0', '-5', '10')

    assert bot.configure(KEYS, answers) == Config('f', 'l', 600)
