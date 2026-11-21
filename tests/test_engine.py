"""Tests for the fishing loop. They use stand-ins for the game, so they run on any system."""
from dataclasses import replace

from fishbot import engine
from fishbot.engine import FishingBot
from fishbot.settings import Settings

REGION = {'left': 100, 'top': 50, 'width': 1920, 'height': 1080}
SPLASH = (640, 360)
# The mouse check has its own tests; it is off here so the other tests keep a simple timeline.
BASE = Settings(fishing_key='f', stop_after_misses=0, pause_on_mouse_move=False)
HANDS_OFF = replace(BASE, pause_on_mouse_move=True)
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
        self.pointer = (900, 700)

    def _record(self, *event):
        self.events.append(event)
        self.on_event(event)

    def press(self, key):
        self._record('press', key, self.clock.now)

    def moveTo(self, x, y, duration):
        self.pointer = (x, y)
        self._record('move', x, y)

    def click(self, x=None, y=None, button='left'):
        self.pointer = (x, y)
        self._record('click', button, (x, y))

    def position(self):
        return self.pointer

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
    def __init__(self, settings=BASE, on_frame=None, frame_time=0.25):
        self.clock = FakeClock()
        self.window = FakeWindow()
        self.controls = FakeControls(self.clock)
        self.vision = FakeVision(self.clock, on_frame or self.a_real_bite, frame_time)
        self.messages = []
        self.recorded = []
        self.bot = FishingBot(settings, self.window, self.vision, self.controls,
                              clock=self.clock, idle=self.clock.sleep, log=self.messages.append,
                              on_click=lambda x, y, practice: self.recorded.append((x, y, practice)))

    def a_real_bite(self, frame):
        """Like the game: the bite comes a few seconds after the cast, somewhere new every time."""
        casts = self.controls.presses('f')
        if not casts or self.clock.now - casts[-1] < 3.0:
            return None
        return self.spot(len(casts))

    @staticmethod
    def spot(cast):
        return 500 + 37 * (cast % 23), 300 + 29 * (cast % 17)

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
    game = Game(on_frame=lambda frame: SPLASH)
    game.stop_after('click', 1)

    game.bot.run()

    assert game.controls.events == [('press', 'f', 0.0), ('move', *SPLASH), ('click', 'right', SPLASH)]
    assert game.window.focus_calls == 1
    assert game.bot.state == engine.STOPPED


def test_the_click_names_the_splash_position_instead_of_trusting_the_pointer():
    # The user may move the mouse during the short wait between the move and the click.
    game = Game(on_frame=lambda frame: SPLASH)
    game.stop_after('click', 1)

    game.bot.run()

    assert game.controls.events[-1] == ('click', 'right', SPLASH)


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
    assert 74 <= len(first_cast) <= 77  # 19 seconds of looking: the first second after the cast is skipped
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


def test_a_moment_without_a_window_position_does_not_abandon_the_cast():
    # On macOS the system cannot say where the window is for about half a second after a key press.
    game = Game(on_frame=lambda frame: SPLASH)
    looks_without_position = []
    real_region = game.window.capture_region

    def region_missing_at_first():
        if game.clock.now < 1.6:
            looks_without_position.append(game.clock.now)
            return None
        return real_region()

    def on_event(event):
        if event[0] == 'press':  # the window is found before the cast and lost right after the key press
            game.window.capture_region = region_missing_at_first
        if event[0] == 'click':
            game.bot.stop()

    game.controls.on_event = on_event

    game.bot.run()

    assert len(looks_without_position) >= 2
    assert len(game.controls.presses('f')) == 1  # still the first cast
    assert game.controls.count('click') == 1
    assert game.vision.frames == 1  # no look was attempted without a position


def test_a_cast_without_any_window_position_times_out_without_input():
    game = Game()
    game.controls.on_event = lambda event: event[0] == 'press' and setattr(game.window, 'region', None)
    game.clock.on_sleep = lambda count: game.clock.now > 30 and game.bot.stop()

    game.bot.run()

    assert [event[:2] for event in game.controls.events] == [('press', 'f')]
    assert game.vision.frames == 0
    assert game.bot.stats.missed == 1


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


# ----- safeguards -----

def test_nothing_is_looked_at_while_the_bobber_is_still_in_the_air():
    game = Game(on_frame=lambda frame: SPLASH)
    game.stop_after('click', 1)

    game.bot.run()

    assert game.vision.times[0] >= engine.SETTLE_AFTER_CAST_SEC


def test_each_click_is_reported_once_it_has_happened():
    # Reported after the click, so that nothing slow sits between the last safety check and the click.
    game = Game(on_frame=lambda frame: SPLASH)
    seen_at_report = []
    game.bot._on_click = lambda x, y, practice: seen_at_report.append((x, y, practice, game.controls.count('click')))
    game.stop_after('click', 1)

    game.bot.run()

    assert seen_at_report == [(*SPLASH, False, 1)]


def test_a_failing_click_record_does_not_break_the_loop():
    game = Game()

    def broken(x, y, practice):
        raise RuntimeError('disk full')

    game.bot._on_click = broken
    game.stop_after('click', 3)

    game.bot.run()

    assert game.controls.count('click') == 3
    assert 'The click could not be recorded (disk full).' in game.messages


def test_a_splash_that_always_comes_at_once_stops_the_bot_before_the_third_click():
    # Something on screen that permanently looks like a splash is "seen" as soon as looking starts.
    # Each such click counts as a catch, so nothing else would ever stop it.
    game = Game(on_frame=lambda frame: Game.spot(len(game.controls.presses('f'))))

    game.bot.run()  # stops by itself

    assert game.controls.count('click') == engine.TOO_FAST_STREAK - 1
    assert game.bot.stopped_by_safeguard
    assert 'within 2 seconds of casting' in game.bot.stop_reason


def test_catches_on_exactly_the_same_spot_stop_the_bot_before_the_fourth_click():
    def same_place_after_a_normal_wait(frame):
        cast = game.controls.presses('f')[-1]
        return SPLASH if game.clock.now - cast >= 4.0 else None

    game = Game(on_frame=same_place_after_a_normal_wait)

    game.bot.run()

    assert game.controls.count('click') == engine.SAME_SPOT_COUNT - 1
    assert game.bot.stopped_by_safeguard
    assert '4 of the last 4 catches were on exactly the same spot' in game.bot.stop_reason


def test_a_miss_between_quick_catches_starts_the_count_again():
    # quick, quick, nothing, quick, quick: never three quick ones in a row
    plan = iter(['quick', 'quick', 'nothing', 'quick', 'quick', 'stop'])
    current = {}

    def per_cast(frame):
        casts = len(game.controls.presses('f'))
        if casts != current.get('cast'):
            current.update(cast=casts, outcome=next(plan))
        if current['outcome'] == 'stop':
            game.bot.stop()
        return Game.spot(casts) if current['outcome'] == 'quick' else None

    game = Game(on_frame=per_cast)

    game.bot.run()

    assert game.controls.count('click') == 4
    assert not game.bot.stopped_by_safeguard


def test_constant_recasting_stops_the_bot():
    # Every cast is cut short at once (here: the game keeps losing focus for a moment).
    def lose_focus_briefly(frame):
        game.window.foreground = False
        return None

    game = Game(on_frame=lose_focus_briefly)
    game.clock.on_sleep = lambda count: setattr(game.window, 'foreground', True)

    game.bot.run()

    assert len(game.controls.presses('f')) == engine.CAST_BURST_COUNT
    assert game.controls.count('click') == 0
    assert game.bot.stopped_by_safeguard
    assert 'recast 8 times in 20 seconds' in game.bot.stop_reason


def test_a_black_screen_stops_the_bot():
    def go_black(frame):
        game.vision.blank_streak = frame  # one more black picture on every look
        return None

    game = Game(on_frame=go_black)

    game.bot.run()

    assert game.vision.frames == engine.BLANK_LOOKS
    assert game.controls.count('click') == 0
    assert 'black screen' in game.bot.stop_reason and game.bot.stopped_by_safeguard


def test_an_ignored_sighting_is_mentioned_once_per_cast():
    class Ignored:
        note = 'at the edge of the window, where the bobber does not land'

    def ignore_everything(frame):
        game.vision.last = Ignored()
        return None

    game = Game(on_frame=ignore_everything)
    game.stop_after('press', 3)

    game.bot.run()

    mentions = [message for message in game.messages if message.startswith('Ignored something')]
    assert mentions == ['Ignored something that looked like a splash: it was at the edge of the window, '
                        'where the bobber does not land.'] * 2
    assert game.controls.count('click') == 0


def test_running_out_of_misses_counts_as_a_safeguard_stop_and_a_time_limit_does_not():
    missed = Game(settings=replace(BASE, stop_after_misses=2), on_frame=lambda frame: None)
    timed = Game(settings=replace(BASE, stop_after_minutes=1), on_frame=lambda frame: None)

    missed.bot.run()
    timed.bot.run()

    assert missed.bot.stopped_by_safeguard
    assert not timed.bot.stopped_by_safeguard


# ----- the user takes the mouse -----

def test_waits_for_the_mouse_to_be_left_alone_before_the_first_cast():
    game = Game(settings=HANDS_OFF)

    def still_moving(count):
        if count <= 5:  # the user is still moving the mouse for the first half second
            game.controls.pointer = (900 + 20 * count, 700)

    game.clock.on_sleep = still_moving
    game.stop_after('press', 1)

    game.bot.run()

    assert game.controls.presses('f')[0] >= 0.5 + engine.STILL_BEFORE_START_SEC


def test_moving_the_mouse_during_a_cast_pauses_the_bot_without_a_click():
    def user_grabs_the_mouse(frame):
        if frame == 3:
            game.controls.pointer = (200, 200)
        return None

    game = Game(settings=HANDS_OFF, on_frame=user_grabs_the_mouse)
    game.clock.on_sleep = lambda count: game.bot.paused and game.clock.now > 30 and game.bot.stop()

    game.bot.run()

    assert game.bot.paused
    assert 'you moved the mouse' in ' '.join(game.messages)
    assert len(game.controls.presses('f')) == 1
    assert game.controls.count('move') == 0 and game.controls.count('click') == 0


def test_moving_the_mouse_between_the_bots_move_and_its_click_cancels_the_click():
    game = Game(settings=HANDS_OFF, on_frame=lambda frame: SPLASH)

    def user_pulls_away(event):
        if event[0] == 'move':
            game.controls.pointer = (SPLASH[0] + 300, SPLASH[1])

    game.controls.on_event = user_pulls_away
    game.clock.on_sleep = lambda count: game.bot.paused and game.clock.now > 30 and game.bot.stop()

    game.bot.run()

    assert game.controls.count('move') == 1
    assert game.controls.count('click') == 0
    assert game.bot.paused


def test_the_bots_own_mouse_movement_does_not_pause_it():
    game = Game(settings=HANDS_OFF)
    game.stop_after('click', 25)

    game.bot.run()

    assert game.controls.count('click') == 25
    assert not game.bot.paused
    assert not any('moved the mouse' in message for message in game.messages)


def test_after_resuming_the_bot_waits_for_a_still_mouse_and_carries_on():
    def user_grabs_the_mouse_once(frame):
        if frame == 2:
            game.controls.pointer = (200, 200)
        return game.a_real_bite(frame)

    game = Game(settings=HANDS_OFF, on_frame=user_grabs_the_mouse_once)
    resumed_at = []

    def resume_later(count):
        if game.bot.paused and game.clock.now > 10:
            resumed_at.append(game.clock.now)
            game.bot.set_paused(False)

    game.clock.on_sleep = resume_later
    game.stop_after('click', 1)

    game.bot.run()

    casts = game.controls.presses('f')
    assert len(casts) == 2 and game.controls.count('click') == 1
    assert casts[1] >= resumed_at[0] + engine.STILL_BEFORE_START_SEC


def test_mouse_movement_is_ignored_when_the_setting_is_off():
    def user_moves_the_mouse(frame):
        game.controls.pointer = (frame * 50, 200)
        return game.a_real_bite(frame)

    game = Game(settings=BASE, on_frame=user_moves_the_mouse)
    game.stop_after('click', 2)

    game.bot.run()

    assert game.controls.count('click') == 2
    assert not game.bot.paused


# ----- practice mode -----

def test_practice_mode_reports_what_it_would_click_and_sends_nothing():
    sightings = iter([None, None, SPLASH, None, (700, 400), None])

    def scripted(frame):
        try:
            return next(sightings)
        except StopIteration:
            game.bot.stop()
            return None

    game = Game(settings=replace(BASE, practice_mode=True), on_frame=scripted)
    states = set()
    game.clock.on_sleep = lambda count: states.add(game.bot.state)

    game.bot.run()

    assert game.controls.events == []
    assert game.recorded == [(*SPLASH, True), (700, 400, True)]
    assert game.bot.stats.practice_clicks == 2 and game.bot.stats.looted == 0 and game.bot.stats.casts == 0
    assert states == {engine.PRACTICE}
    assert game.window.focus_calls == 0  # not even the request to bring the game forward
    assert game.messages[0].startswith('Practice mode: watching only.')
    assert 'Practice: would right-click at x: 640, y: 360 (1 so far).' in game.messages


def test_practice_mode_only_watches_while_the_game_is_in_front():
    game = Game(settings=replace(BASE, practice_mode=True), on_frame=lambda frame: None)
    game.window.foreground = False
    game.clock.on_sleep = lambda count: count >= 50 and game.bot.stop()

    game.bot.run()

    assert game.vision.frames == 0
    assert game.controls.events == []


# ----- found by an independent review of the safeguards -----

def slow_bite_at(game, place):
    """A sighting that comes after a normal wait (so the too-fast rule stays out of it), at ``place(cast)``."""
    def on_frame(frame):
        casts = game.controls.presses('f')
        return place(len(casts)) if game.clock.now - casts[-1] >= 4.0 else None
    return on_frame


def test_real_catches_in_between_do_not_hide_a_spot_that_keeps_coming_back():
    # same spot, real, same spot, real, same spot, real, same spot -> stopped before that fourth click
    game = Game()
    game.vision.on_frame = slow_bite_at(game, lambda cast: SPLASH if cast % 2 else Game.spot(cast))

    game.bot.run()

    clicked = [event[2] for event in game.controls.events if event[0] == 'click']
    assert clicked.count(SPLASH) == 3 and len(clicked) == 6
    assert '4 of the last 7 catches were on exactly the same spot' in game.bot.stop_reason


def test_a_miss_does_not_clear_the_memory_of_spots():
    plan = iter(['spot', 'spot', 'nothing', 'spot', 'spot'])
    current = {}

    def per_cast(frame):
        casts = game.controls.presses('f')
        if len(casts) != current.get('cast'):
            current.update(cast=len(casts), outcome=next(plan))
        return SPLASH if current['outcome'] == 'spot' and game.clock.now - casts[-1] >= 4.0 else None

    game = Game(on_frame=per_cast)

    game.bot.run()

    assert game.controls.count('click') == 3
    assert 'same spot' in game.bot.stop_reason


def test_a_detection_that_wobbles_by_a_few_pixels_is_still_the_same_spot():
    game = Game()
    game.vision.on_frame = slow_bite_at(game, lambda cast: (SPLASH[0] + (cast % 3) * 3, SPLASH[1] - (cast % 2) * 4))

    game.bot.run()

    assert game.controls.count('click') == 3
    assert 'same spot' in game.bot.stop_reason


def test_the_same_spot_is_wider_on_a_larger_window():
    def run(width, step):
        game = Game()
        game.window.region = {'left': 0, 'top': 0, 'width': width, 'height': width * 9 // 16}
        game.vision.on_frame = slow_bite_at(game, lambda cast: (800 + cast * step, 500))
        game.stop_after('click', 12)
        game.bot.run()
        return game.bot.stopped_by_safeguard

    # Every catch lands 5 px to the right of the one before. At 1920 wide the spot is 7.7 px, so only
    # the previous catch is near: no cluster. At 3840 wide it is 15.4 px, so the last four all are.
    assert run(width=1920, step=5) is False
    assert run(width=3840, step=5) is True


def test_moving_the_mouse_between_a_catch_and_the_next_cast_stops_the_next_key_press():
    game = Game(settings=HANDS_OFF)

    def user_takes_over_after_the_click(event):
        if event[0] == 'click':
            game.controls.pointer = (150, 150)

    game.controls.on_event = user_takes_over_after_the_click
    game.clock.on_sleep = lambda count: game.bot.paused and game.clock.now > 60 and game.bot.stop()

    game.bot.run()

    assert len(game.controls.presses('f')) == 1 and game.controls.count('click') == 1
    assert game.bot.paused


def test_moving_the_mouse_while_the_lure_is_applied_stops_the_cast():
    game = Game(settings=replace(HANDS_OFF, lure_enabled=True, lure_key='l'))

    def user_takes_over_after_the_lure(event):
        if event[:2] == ('press', 'l'):
            game.controls.pointer = (150, 150)

    game.controls.on_event = user_takes_over_after_the_lure
    game.clock.on_sleep = lambda count: game.bot.paused and game.clock.now > 60 and game.bot.stop()

    game.bot.run()

    assert [event[:2] for event in game.controls.events] == [('press', 'l')]
    assert game.bot.paused


def test_the_pause_key_right_after_the_bot_paused_itself_keeps_it_paused():
    def user_grabs_the_mouse(frame):
        if frame == 2:
            game.controls.pointer = (200, 200)
        return None

    game = Game(settings=HANDS_OFF, on_frame=user_grabs_the_mouse)
    presses = []

    def user_presses_the_pause_key(count):
        if game.bot.paused and not presses:
            presses.append(game.clock.now)
            game.bot.toggle_pause()          # meant as "pause": it must not resume
            assert game.bot.paused
        elif game.bot.paused and len(presses) == 1 and game.clock.now > presses[0] + 1:
            presses.append(game.clock.now)
            game.bot.toggle_pause()          # the second press resumes
            assert not game.bot.paused
            game.bot.stop()

    game.clock.on_sleep = user_presses_the_pause_key

    game.bot.run()

    assert len(presses) == 2
    assert 'Still paused. Press the pause key again to resume.' in game.messages


def test_the_pause_key_resumes_as_usual_once_the_bots_own_pause_is_old():
    def user_grabs_the_mouse(frame):
        if frame == 2:
            game.controls.pointer = (200, 200)
        return None

    game = Game(settings=HANDS_OFF, on_frame=user_grabs_the_mouse)
    paused_at = []

    def later(count):
        if game.bot.paused and not paused_at:
            paused_at.append(game.clock.now)
        elif paused_at and game.clock.now > paused_at[0] + engine.KEEP_OWN_PAUSE_SEC + 1:
            game.bot.toggle_pause()
            assert not game.bot.paused
            game.bot.stop()

    game.clock.on_sleep = later

    game.bot.run()

    assert 'Still paused. Press the pause key again to resume.' not in game.messages


def test_a_resume_that_arrives_at_once_still_waits_for_a_still_mouse():
    # The user is still moving the mouse when the pause is lifted again.
    def user_grabs_the_mouse(frame):
        if frame == 2:
            game.controls.pointer = (200, 200)
        return None

    game = Game(settings=HANDS_OFF, on_frame=user_grabs_the_mouse)
    resumed = []

    def resume_at_once_and_keep_moving(count):
        if game.bot.paused and not resumed:
            game.bot.set_paused(False)
            resumed.append(game.clock.now)
        elif resumed and game.clock.now < resumed[0] + 1.0:
            game.controls.pointer = (200 + count * 15, 200)

    game.clock.on_sleep = resume_at_once_and_keep_moving
    game.stop_after('press', 2)

    game.bot.run()

    assert game.controls.presses('f')[1] >= resumed[0] + 1.0 + engine.STILL_BEFORE_START_SEC - 0.2


def test_nothing_is_sent_to_bring_the_game_forward_once_stop_was_asked():
    game = Game()
    game.bot.stop()

    game.bot.run()

    assert game.window.focus_calls == 0
    assert game.controls.events == []


def test_a_stop_that_arrives_while_the_window_is_being_checked_is_seen():
    game = Game()
    real_check = game.window.is_foreground
    checks = []

    def slow_check():
        checks.append(1)
        if len(checks) == 2:       # the check right before the first key press: stop arrives during it
            game.bot.stop('Stopped with F9.')
        return real_check()

    game.window.is_foreground = slow_check

    game.bot.run()

    assert game.controls.events == []


def test_the_click_is_dropped_when_the_window_moved_after_the_splash_was_seen():
    game = Game(on_frame=lambda frame: SPLASH)

    def user_moves_the_window(event):
        if event[0] == 'move':
            game.window.region = {'left': 900, 'top': 300, 'width': 1920, 'height': 1080}
        if len(game.controls.presses('f')) == 2:
            game.bot.stop()

    game.controls.on_event = user_moves_the_window

    game.bot.run()

    assert game.controls.count('click') == 0
    assert 'The game window moved or changed size after the splash was seen, so the click was dropped.' in game.messages


def test_a_user_stop_and_a_safeguard_stop_never_mix():
    stopped_by_user_first = Game()
    stopped_by_user_first.bot.stop('Stopped with F9.')
    stopped_by_user_first.bot._trip('Stopped: something looked wrong.')

    stopped_by_safeguard_first = Game()
    stopped_by_safeguard_first.bot._trip('Stopped: something looked wrong.')
    stopped_by_safeguard_first.bot.stop('Stopped with F9.')

    assert (stopped_by_user_first.bot.stop_reason, stopped_by_user_first.bot.stopped_by_safeguard) == (
        'Stopped with F9.', False)
    assert (stopped_by_safeguard_first.bot.stop_reason, stopped_by_safeguard_first.bot.stopped_by_safeguard) == (
        'Stopped: something looked wrong.', True)


def test_a_slightly_shaky_pointer_still_counts_as_a_still_mouse():
    game = Game(settings=HANDS_OFF)
    game.clock.on_sleep = lambda count: setattr(game.controls, 'pointer', (900 + count % 2, 700))  # 1 px of jitter
    game.stop_after('press', 1)

    game.bot.run()

    assert game.controls.presses('f')[0] <= 1.0


def test_the_bot_says_so_when_it_is_waiting_for_the_mouse():
    game = Game(settings=HANDS_OFF)

    def keeps_moving(count):
        game.controls.pointer = (900 + 20 * count, 700)
        if game.clock.now > 5:
            game.bot.stop()

    game.clock.on_sleep = keeps_moving

    game.bot.run()

    assert game.messages.count('Waiting for the mouse to be still before sending anything.') == 1
    assert game.controls.events == []
