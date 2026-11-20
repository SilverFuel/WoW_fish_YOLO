"""Runs the fishing loop on a background thread and reports on it.

This is what the web interface and the console mode talk to: start, pause, stop, the current
state and statistics, a log, and a picture of what the bot last saw.
"""
from __future__ import annotations

import collections
import threading
import time
import traceback
from dataclasses import asdict

from fishbot import __version__, keys
from fishbot.detector import DEFAULT_MODEL, SplashDetector
from fishbot.engine import FishingBot, Stats
from fishbot.platforms import GameWindowNotFound
from fishbot.settings import problems_before_start
from fishbot.vision import Vision, looks_blank, render_preview

HOTKEY_POLL_SEC = 0.03
FOCUS_WAIT_SEC = 3.0
FOCUS_SETTLE_SEC = 0.6
LOG_LINES = 300


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

    def start(self):
        """Start fishing. Returns a list of problems; empty means it started."""
        with self._lock:
            if self.running:
                return ['The bot is already running.']

            settings = self.store.settings
            problems = problems_before_start(settings)
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
            self._message = ''
            self._thread = threading.Thread(target=self._run, args=(settings, window), name='fishing', daemon=True)
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
        bot = self._bot
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

    def _run(self, settings, window):
        bot = None
        finished = threading.Event()
        try:
            vision = Vision(self._detector_for(settings.cpu_threads), self._grabber,
                            settings.confidence, settings.scan_area)
            bot = FishingBot(settings, window, vision, self._controls_once(), log=self.log)
            with self._lock:
                self._bot, self._vision = bot, vision
                self._starting = False
                if self._stop_while_starting is not None:
                    bot.stop(self._stop_while_starting)

            self.log(f'Started. {settings.pause_hotkey.upper()} pauses, {settings.stop_hotkey.upper()} stops.')
            threading.Thread(target=self._watch_hotkeys, args=(bot, settings, finished),
                             name='hotkeys', daemon=True).start()
            bot.run()
            message, level = bot.stop_reason or 'Stopped.', 'info'
        except Exception as error:  # the loop must never take the app down with it
            if type(error).__name__ == 'FailSafeException':
                message, level = 'Stopped: the mouse was moved into a screen corner (fail-safe).', 'info'
            else:
                traceback.print_exc()
                message, level = f'Stopped by an error: {error}', 'error'
        finally:
            finished.set()

        with self._lock:
            if bot is not None:
                self._last_stats = bot.stats
                self._last_elapsed = bot.elapsed_seconds()
                if self._vision is not None and self._vision.last is not None:
                    self._sighting = self._vision.last
                    self._preview_id += 1
            self._bot, self._vision = None, None
            self._starting = False
            self._message = message
        self.log(message, level)

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
                    self.log(f'Hotkeys are unavailable ({error}). Use the buttons instead.', 'warning')
                    return
                if down and not was_down[name]:
                    action()
                was_down[name] = down

    # ----- setup check and preview -----

    def check_setup(self):
        """Bring the game to the front, take one look and describe what was found."""
        with self._lock:
            if self.running:
                return {'ok': False, 'message': 'Stop the bot first. While it runs, the preview is live.'}

        try:
            window = self.platform.find_game_window()
        except GameWindowNotFound as error:
            return {'ok': False, 'message': str(error)}

        missing = self.platform.permission_problems()
        if missing:
            return {'ok': False, 'message': ' '.join(missing)}

        window.focus()
        deadline = time.monotonic() + FOCUS_WAIT_SEC
        while not window.is_foreground() and time.monotonic() < deadline:
            time.sleep(0.1)
        in_front = window.is_foreground()
        if in_front and self.platform.SYSTEM != 'demo':
            time.sleep(FOCUS_SETTLE_SEC)

        region = window.capture_region()
        if region is None:
            return {'ok': False, 'message': 'The game window is minimised or on another desktop. Bring it up and try again.'}

        settings = self.store.settings
        try:
            vision = Vision(self._detector_for(settings.cpu_threads), self._grabber,
                            settings.confidence, settings.scan_area)
            sighting = vision.survey(region)
        except Exception as error:
            traceback.print_exc()
            return {'ok': False, 'message': f'The screen could not be captured: {error}'}

        with self._lock:
            self._sighting = sighting
            self._preview_id += 1

        blank = looks_blank(sighting.frame)
        if blank:
            message = 'The capture is black, so the bot cannot see the game. Is the game window covered or on a screen that is off?'
        elif not in_front:
            message = 'The game could not be brought to the front, so the picture may show another window.'
        else:
            message = 'This is what the bot sees. The bobber should be inside the outlined area.'

        return {'ok': not blank, 'message': message, 'in_front': in_front, 'blank': blank,
                'width': region['width'], 'height': region['height'],
                'best_score': round(sighting.detection.score, 3),
                'inference_ms': round(self._detector.last_inference_ms)}

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
