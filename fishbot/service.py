"""Runs the fishing loop on a background thread and reports on it.

This is what the web interface and the console mode talk to: start, pause, stop, the current
state and statistics, a log, and a picture of what the bot last saw.
"""
from __future__ import annotations

import collections
import threading
import time
import traceback
from dataclasses import asdict, replace

from fishbot import __version__, keys, report
from fishbot.detector import DEFAULT_MODEL, SplashDetector
from fishbot.engine import FishingBot, Stats
from fishbot.platforms import GameWindowNotFound
from fishbot.settings import problems_before_start
from fishbot.vision import Vision, looks_blank, render_preview

HOTKEY_POLL_SEC = 0.03
FOCUS_WAIT_SEC = 3.0
FOCUS_SETTLE_SEC = 0.6
LOG_LINES = 300
CLICKS_KEPT = 6


class BotService:
    def __init__(self, platform, store, model_path=DEFAULT_MODEL):
        self.platform = platform
        self.store = store
        self._model_path = model_path
        self._lock = threading.RLock()
        self._load_lock = threading.Lock()  # separate, so a slow load never blocks status requests
        self._thread = None
        self._bot = None
        self._starting = False
        self._stop_while_starting = None
        self._pause_while_starting = False
        self._detector = None
        self._detector_threads = None
        self._controls = None
        self._grabber = platform.create_grabber()
        self._vision = None
        self._sighting = None
        self._preview_id = 0
        self._log = collections.deque(maxlen=LOG_LINES)
        self._log_id = 0
        self._last_stats = Stats()
        self._last_elapsed = 0.0
        self._message = ''
        self._practice = False
        self._test, self._test_result = False, ''
        self._recorder = report.CastRecorder()
        self._stopped_by_safeguard = False
        self._clicks = collections.deque(maxlen=CLICKS_KEPT)  # what was clicked, newest last
        self._click_id = 0

    # ----- log -----

    def log(self, message, level='info'):
        with self._lock:
            self._log_id += 1
            self._log.append({'id': self._log_id, 'time': time.time(), 'level': level, 'message': message})
        print(message, flush=True)

    # ----- control -----

    @property
    def running(self):
        thread = self._thread
        return self._starting or (thread is not None and thread.is_alive())

    def start(self, practice=False, test=False):
        """Start fishing. Returns a list of problems; empty means it started.

        ``practice`` only watches. ``test`` is one real cast: it casts once, clicks the bobber if it
        sees a bite, stops, and hands the front back to the window it was started from.
        """
        with self._lock:
            if self.running:
                return ['It is already running.']

            settings = self.store.settings
            if test:
                # One cast, no lure: the point is to see a single cast and click.
                settings = replace(settings, lure_enabled=False, stop_after_catches=1, stop_after_misses=1)
            # Practice presses nothing, so it needs no keys.
            problems = [] if practice else problems_before_start(settings)
            if problems:
                return problems

            try:
                window = self.platform.find_game_window()
            except GameWindowNotFound as error:
                return [str(error)]

            missing = self.platform.permission_problems()
            if missing:
                return missing

            self._starting = True
            self._stop_while_starting = None
            self._pause_while_starting = False
            self._message = ''
            self._stopped_by_safeguard = False
            self._practice = practice
            self._test, self._test_result = test, ''
            came_from = self._front_window() if test else None
            self._thread = threading.Thread(target=self._run, args=(settings, window, practice, came_from),
                                            name='fishing', daemon=True)
            self._thread.start()
            return []

    def stop(self, reason='Stopped.'):
        with self._lock:
            bot = self._bot
            if bot is None and self._starting:
                # The loop does not exist yet (the model is loading); remember the request for it.
                self._stop_while_starting = reason
        if bot is not None:
            bot.stop(reason)

    def set_paused(self, paused):
        with self._lock:
            bot = self._bot
            if bot is None and self._starting:
                # The loop does not exist yet; it must not start casting against a pause already asked for.
                self._pause_while_starting = paused
        if bot is not None:
            bot.set_paused(paused)

    def wait(self, timeout=None):
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def shutdown(self):
        self.stop('Stopped: the app is closing.')
        self.wait(5)

    def _detector_for(self, threads):
        with self._load_lock:
            if self._detector is None or self._detector_threads != threads:
                self._detector = SplashDetector(self._model_path, threads)
                self._detector_threads = threads
            return self._detector

    def _controls_once(self):
        with self._load_lock:
            if self._controls is None:
                self._controls = self.platform.create_controls()
            return self._controls

    def _run(self, settings, window, practice, hand_back_to=None):
        bot = None
        finished = threading.Event()
        try:
            vision = Vision(self._detector_for(settings.cpu_threads), self._grabber,
                            settings.confidence, settings.scan_area)
            bot = FishingBot(settings, window, vision, self._controls_once(), log=self.log,
                             on_click=lambda x, y, practised: self._remember_click(vision, x, y, practised),
                             practice=practice, on_look=self._recorder.look, stop_if_mouse_moves=self._test)
            with self._lock:
                self._bot, self._vision = bot, vision
                self._starting = False
                if self._stop_while_starting is not None:
                    bot.stop(self._stop_while_starting)
                if self._pause_while_starting:
                    bot.set_paused(True)

            if self._test:
                self.log('Test cast: it casts once, clicks the bobber if it sees a bite, then stops.')
            elif self.platform.SYSTEM == 'demo':
                self.log('Started. This is the pretend game, so use the buttons on this page to pause and stop.')
            elif not practice:
                self.log(f'Started. In the game, {settings.pause_hotkey.upper()} pauses and {settings.stop_hotkey.upper()} stops.')
            threading.Thread(target=self._watch_hotkeys, args=(bot, settings, finished),
                             name='hotkeys', daemon=True).start()
            bot.run()
            message, level = bot.stop_reason or 'Stopped.', 'info'
        except Exception as error:  # the loop must never take the app down with it
            if type(error).__name__ == 'FailSafeException':
                message, level = 'Stopped because the mouse went into a corner of the screen.', 'info'
            else:
                traceback.print_exc()
                message, level = f'Stopped because something went wrong: {error}', 'error'
        finally:
            finished.set()
            self._release_capture()

        with self._lock:
            if bot is not None:
                self._last_stats = bot.stats
                self._last_elapsed = bot.elapsed_seconds()
                self._stopped_by_safeguard = bot.stopped_by_safeguard
                if self._vision is not None and self._vision.last is not None:
                    self._sighting = self._vision.last
                    self._preview_id += 1
                if self._test:
                    # A test cast ends after one cast either way; neither ending is an alarm.
                    if bot.stats.looted:
                        self._test_result, message = 'caught', 'The test cast is done.'
                    elif bot.stats.missed:
                        self._test_result = 'no_bite'
                        message = f'The test cast saw no bite. {bot.why_no_bite}'.strip()
                        self._stopped_by_safeguard = False
                    else:
                        self._test_result = 'stopped'
            self._bot, self._vision = None, None
            self._starting = False
            self._message = message
        self.log(message, level)
        self._hand_back(hand_back_to)

    def _release_capture(self):
        """Each session and each check runs on its own thread, and screen capture handles belong to a thread."""
        close = getattr(self._grabber, 'close', None)
        if close is not None:
            close()

    def _front_window(self):
        """What the person has in front right now, normally this page, so it can be handed back."""
        try:
            return self.platform.front_window()
        except Exception:
            traceback.print_exc()
            return None

    def _hand_back(self, window):
        """Bring the person's own window back after the game was brought forward for them."""
        if window is None:
            return
        try:
            self.platform.bring_to_front(window)
        except Exception:
            traceback.print_exc()

    def _remember_click(self, vision, x, y, practice):
        """Keep the picture the bot acted on, so a wrong click can be looked at afterwards."""
        sighting = vision.last
        if sighting is None:
            return
        picture = render_preview(sighting)
        with self._lock:
            self._click_id += 1
            self._clicks.append({'id': self._click_id, 'time': time.time(), 'x': x, 'y': y, 'practice': practice,
                                 'score': round(sighting.detection.score, 3), 'picture': picture})

    def click_jpeg(self, click_id):
        with self._lock:
            for click in self._clicks:
                if click['id'] == click_id:
                    return click['picture']
        return None

    def _watch_hotkeys(self, bot, settings, finished):
        """Poll the two hotkeys while a session runs. Polling needs no keyboard hook."""
        actions = {settings.pause_hotkey: bot.toggle_pause,
                   settings.stop_hotkey: lambda: bot.stop(f'Stopped with {settings.stop_hotkey.upper()}.')}
        was_down = dict.fromkeys(actions, False)

        while not finished.wait(HOTKEY_POLL_SEC):
            for name, action in actions.items():
                try:
                    down = self.platform.key_is_down(name)
                except Exception as error:
                    self.log(f'The pause and stop keys are not working here ({error}). Use the buttons on the page.', 'warning')
                    return
                if down and not was_down[name]:
                    action()
                was_down[name] = down

    # ----- setup check and preview -----

    def check_setup(self):
        """Bring the game to the front, take one look and describe what was found."""
        with self._lock:
            if self.running:
                return {'ok': False, 'message': 'It is running, so the picture updates by itself.'}

        try:
            window = self.platform.find_game_window()
        except GameWindowNotFound as error:
            return {'ok': False, 'message': str(error)}

        missing = self.platform.permission_problems()
        if missing:
            return {'ok': False, 'message': ' '.join(missing)}

        came_from = self._front_window()
        try:
            return self._look_once(window)
        finally:
            self._release_capture()
            self._hand_back(came_from)

    def _look_once(self, window):
        window.focus()
        deadline = time.monotonic() + FOCUS_WAIT_SEC
        while not window.is_foreground() and time.monotonic() < deadline:
            time.sleep(0.1)
        in_front = window.is_foreground()
        if in_front and self.platform.SYSTEM != 'demo':
            time.sleep(FOCUS_SETTLE_SEC)

        region = window.capture_region()
        if region is None:
            return {'ok': False, 'message': 'The game is minimised or on another desktop. Bring it back and try again.'}

        settings = self.store.settings
        try:
            vision = Vision(self._detector_for(settings.cpu_threads), self._grabber,
                            settings.confidence, settings.scan_area)
            sighting = vision.survey(region)
        except Exception as error:
            traceback.print_exc()
            return {'ok': False, 'message': f'It could not take a picture of the screen: {error}'}

        with self._lock:
            self._sighting = sighting
            self._preview_id += 1

        blank = looks_blank(sighting.frame)
        if blank:
            message = 'The picture is black, so it cannot see the game. Is the game covered up, or on a screen that is off?'
        elif not in_front:
            message = 'The game did not come to the front, so this may show another window. Click on the game and try again.'
        else:
            message = ('This is what it sees.' if settings.scan_area == 'full'
                       else 'This is what it sees. The bobber has to land inside the blue box.')

        return {'ok': not blank, 'message': message, 'in_front': in_front, 'blank': blank,
                'width': region['width'], 'height': region['height'],
                'best_score': round(sighting.detection.score, 3),
                'inference_ms': round(self._detector.last_inference_ms)}

    def report_zip(self):
        """Everything needed to see why it does not work on this computer, as one ZIP file."""
        try:
            facts = list(self.platform.facts())
        except Exception as error:
            traceback.print_exc()
            facts = [f'The facts about this computer could not be read ({type(error).__name__}: {error}).']

        snapshot = self.snapshot()
        with self._lock:
            clicks = [(f'click-{click["id"]:03d}-{"practice-" if click["practice"] else ""}{round(click["score"] * 100)}pct',
                       click['picture']) for click in self._clicks]
            log = list(self._log)
        state = {'state': snapshot['state'], 'message': snapshot['message'], 'practice': snapshot['practice'],
                 'test cast': snapshot['test'], 'test cast result': snapshot['test_result'],
                 'waiting for': snapshot['waiting_for'], 'stopped itself': snapshot['stopped_by_safeguard'],
                 **{name: value for name, value in snapshot['stats'].items()}}
        return report.build(__version__, facts, snapshot['settings'], state, log, self._recorder.casts(),
                            clicks, self.preview_jpeg())

    def preview_jpeg(self):
        """The most recent look at the game as a JPEG, or None if there has not been one."""
        vision = self._vision
        sighting = vision.last if vision is not None and vision.last is not None else self._sighting
        return render_preview(sighting) if sighting is not None else None

    # ----- reporting -----

    def snapshot(self, since=0):
        with self._lock:
            bot, vision = self._bot, self._vision
            settings = self.store.settings

            if bot is not None:
                state, stats, elapsed = bot.state, bot.stats, bot.elapsed_seconds()
            else:
                state, stats, elapsed = ('starting' if self._starting else 'idle'), self._last_stats, self._last_elapsed

            sighting = vision.last if vision is not None else None
            if sighting is not None:
                # Each new frame is a new preview while the bot runs.
                preview = f'live-{vision.looks}'
            else:
                preview = f'still-{self._preview_id}' if self._sighting is not None else ''

            return {
                'version': __version__,
                'state': state,
                'running': self.running,
                'message': self._message,
                'practice': self._practice,  # the current or last session only watched
                'test': self._test,  # the current or last session was a single test cast
                'test_result': self._test_result,  # '', 'caught', 'no_bite' or 'stopped'
                'waiting_for': bot.waiting_for if bot is not None else '',
                # The last session ended because a safeguard stopped it, not because the user did.
                'stopped_by_safeguard': self._stopped_by_safeguard and bot is None,
                'clicks': [{name: value for name, value in click.items() if name != 'picture'}
                           for click in reversed(self._clicks)],
                'stats': dict(asdict(stats), elapsed_seconds=round(elapsed),
                              inference_ms=round(self._detector.last_inference_ms) if self._detector else 0,
                              best_score=round(sighting.detection.score, 3) if sighting is not None else None),
                'settings': settings.to_dict(),
                'problems': problems_before_start(settings),
                'platform': {'system': self.platform.SYSTEM, 'label': self.platform.LABEL,
                             'notes': list(self.platform.SETUP_NOTES)},
                'keys': keys.pressable_keys(self.platform.SYSTEM),
                'hotkeys': keys.HOTKEYS,
                'preview': preview,
                'log': [entry for entry in self._log if entry['id'] > since],
                'log_cursor': self._log_id,
            }
