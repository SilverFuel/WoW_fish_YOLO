"""Tests for the fishing loop. They use stand-ins for the game, so they run on any system."""
from dataclasses import replace

from fishbot import engine
from fishbot.engine import FishingBot
from fishbot.settings import Settings

REGION = {'left': 100, 'top': 50, 'width': 1920, 'height': 1080}
SPLASH = (640, 360)
BASE = Settings(fishing_key='f', stop_after_misses=0)
WITH_LURE = replace(BASE, lure_enabled=True, lure_key='l', lure_minutes=10)


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
        assert self.sleeps < 400_000, 'the bot is idling forever'
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


class FakeVision:
    """Each look costs ``frame_time`` seconds and returns whatever ``on_frame`` says."""

    def __init__(self, clock, on_frame, frame_time=0.25):
        self.clock = clock
        self.on_frame = on_frame
        self.frame_time = frame_time
        self.frames = 0
        self.regions = []
        self.times = []

    def find_splash(self, region):
        self.frames += 1
        self.regions.append(region)
        self.times.append(self.clock.now)
        self.clock.sleep(self.frame_time)
        return self.on_frame(self.frames)


class Game:
    def __init__(self, settings=BASE, on_frame=lambda frame: SPLASH, frame_time=0.25):
        self.clock = FakeClock()
        self.window = FakeWindow()
        self.controls = FakeControls(self.clock)
        self.vision = FakeVision(self.clock, on_frame, frame_time)
        self.messages = []
        self.bot = FishingBot(settings, self.window, self.vision, self.controls,
                              clock=self.clock, idle=self.clock.sleep, log=self.messages.append)

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

    assert game.bot.stats.looted == 2000
    assert game.bot.stats.casts == 2000
    assert game.controls.count('click') == 2000
    assert len(game.controls.presses('f')) == 2000


def test_one_catch_presses_the_key_then_right_clicks_the_splash():
    game = Game()
    game.stop_after('click', 1)

    game.bot.run()

    assert [event[:3] for event in game.controls.events] == [
        ('press', 'f', 0.0), ('move', *SPLASH), ('click', 'right')]
    assert game.window.focus_calls == 1
    assert game.bot.state == engine.STOPPED


def test_sends_nothing_while_another_window_is_in_front():
    game = Game()
    game.window.foreground = False
    states = []

    def watch(count):
        states.append(game.bot.state)
        if count >= 50:
            game.bot.stop()

    game.clock.on_sleep = watch

    game.bot.run()

    assert game.controls.events == []
    assert game.vision.frames == 0
    assert set(states) == {engine.WAITING}


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
    assert game.bot.stats.looted == 0


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
    game.bot.set_paused(True)
    seen = {}

    def resume_later(count):
        if count == 30:
            seen['events'] = list(game.controls.events)
            seen['state'] = game.bot.state
            game.bot.set_paused(False)

    game.clock.on_sleep = resume_later
    game.stop_after('click', 1)

    game.bot.run()

    assert seen == {'events': [], 'state': engine.PAUSED}
    assert game.controls.count('click') == 1
    assert game.messages[:2] == ['Paused.', 'Resumed.']


def test_set_paused_twice_is_the_same_as_once():
    game = Game()

    game.bot.set_paused(True)
    game.bot.set_paused(True)

    assert game.bot.paused
    assert game.messages == ['Paused.']


def test_pausing_mid_cast_abandons_that_cast_without_clicking():
    def pause_on_third_frame(frame):
        if frame == 3:
            game.bot.toggle_pause()
        return None

    game = Game(on_frame=pause_on_third_frame)
    game.clock.on_sleep = lambda count: count >= 200 and game.bot.stop()

    game.bot.run()

    assert game.vision.frames == 3
    assert len(game.controls.presses('f')) == 1
    assert game.controls.count('click') == 0


def test_a_cast_with_no_splash_times_out_and_recasts():
    game = Game(on_frame=lambda frame: None)
    game.stop_after('press', 3)

    game.bot.run()

    first, second, third = game.controls.presses('f')
    assert BASE.cast_seconds <= second - first <= BASE.cast_seconds + 3
    assert BASE.cast_seconds <= third - second <= BASE.cast_seconds + 3
    assert game.controls.count('click') == 0
    assert game.bot.stats.missed == 2


def test_cast_time_follows_the_setting():
    game = Game(settings=replace(BASE, cast_seconds=30), on_frame=lambda frame: None)
    game.stop_after('press', 2)

    game.bot.run()

    first, second = game.controls.presses('f')
    assert 30 <= second - first <= 33


def test_looks_no_more_often_than_the_checks_per_second_setting():
    # A fast detector (10 ms a frame) is held to 4 looks a second.
    game = Game(settings=replace(BASE, checks_per_second=4), on_frame=lambda frame: None, frame_time=0.01)
    game.stop_after('press', 2)

    game.bot.run()

    first_cast = [time for time in game.vision.times if time < BASE.cast_seconds]
    gaps = [later - earlier for earlier, later in zip(first_cast, first_cast[1:])]
    assert 78 <= len(first_cast) <= 81
    assert min(gaps) >= 0.25 - 1e-6


def test_a_slow_detector_is_not_slowed_down_further():
    game = Game(settings=replace(BASE, checks_per_second=5), on_frame=lambda frame: None, frame_time=0.4)
    game.stop_after('press', 2)

    game.bot.run()

    first_cast = [time for time in game.vision.times if time < BASE.cast_seconds]
    gaps = [later - earlier for earlier, later in zip(first_cast, first_cast[1:])]
    assert max(gaps) <= 0.4 + 1e-6


def test_lure_is_applied_first_and_again_only_after_it_expires():
    game = Game(settings=WITH_LURE, on_frame=lambda frame: None)

    def stop_on_second_lure(event):
        if len(game.controls.presses('l')) == 2:
            game.bot.stop()

    game.controls.on_event = stop_on_second_lure

    game.bot.run()

    first_lure, second_lure = game.controls.presses('l')
    casts = game.controls.presses('f')
    assert game.controls.events[0][:2] == ('press', 'l')
    assert casts[0] - first_lure == engine.LURE_APPLY_WAIT_SEC
    assert second_lure - first_lure > 600
    assert len(casts) > 20  # many casts happened on the first lure


def test_lure_key_is_ignored_while_the_lure_is_switched_off():
    game = Game(settings=replace(WITH_LURE, lure_enabled=False))
    game.stop_after('click', 3)

    game.bot.run()

    assert game.controls.presses('l') == []


def test_focus_lost_while_the_lure_is_applied_means_no_cast():
    game = Game(settings=WITH_LURE)

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
    assert 'window was closed' in game.bot.stop_reason


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

    assert game.vision.regions == [REGION, moved]


def test_quit_during_a_cast_stops_before_any_click():
    def quit_on_second_frame(frame):
        if frame == 2:
            game.bot.stop()
        return SPLASH if frame >= 2 else None

    game = Game(on_frame=quit_on_second_frame)

    game.bot.run()

    assert game.controls.count('click') == 0


def test_stops_after_the_configured_number_of_misses_in_a_row():
    game = Game(settings=replace(BASE, stop_after_misses=3), on_frame=lambda frame: None)

    game.bot.run()  # stops by itself

    assert len(game.controls.presses('f')) == 3
    assert game.bot.stats.missed == 3
    assert '3 casts in a row' in game.bot.stop_reason


def test_a_catch_resets_the_run_of_misses():
    # miss, miss, catch, miss, miss, miss -> stops only after the three in a row at the end
    outcomes = iter([None, None, SPLASH, None, None, None])
    current = {'cast': None, 'frames_in_cast': 0}

    def per_cast(frame):
        casts = len(game.controls.presses('f'))
        if casts != current['cast']:
            current.update(cast=casts, outcome=next(outcomes))
        return current['outcome']

    game = Game(settings=replace(BASE, stop_after_misses=3), on_frame=per_cast)

    game.bot.run()

    assert game.bot.stats.casts == 6
    assert game.bot.stats.looted == 1
    assert game.bot.stats.missed == 5


def test_stops_when_the_time_limit_is_reached():
    game = Game(settings=replace(BASE, stop_after_minutes=2), on_frame=lambda frame: None)

    game.bot.run()

    assert 120 <= game.clock.now <= 120 + BASE.cast_seconds + 3
    assert '2 minute limit' in game.bot.stop_reason


def test_stop_keeps_the_first_reason():
    game = Game()

    game.bot.stop('Stopped with F9.')
    game.bot.stop('Stopped.')

    assert game.bot.stop_reason == 'Stopped with F9.'
