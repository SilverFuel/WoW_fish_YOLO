"""User settings: defaults, validation and the JSON file they are saved in."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from urllib.parse import urlparse

from fishbot import keys

# scan area -> (share of the window that is watched, model input size).
# The input size shrinks with the area, so the bobber keeps the size the model was trained on.
SCAN_AREAS = {'full': (1.0, 640), 'center75': (0.75, 480), 'center50': (0.5, 320)}


@dataclass(frozen=True)
class Settings:
    fishing_key: str = ''
    lure_enabled: bool = False
    lure_key: str = ''
    lure_minutes: int = 10
    pause_hotkey: str = 'f8'
    stop_hotkey: str = 'f9'
    cast_seconds: int = 20
    confidence: float = 0.8
    scan_area: str = 'full'
    checks_per_second: int = 5
    cpu_threads: int = 2
    stop_after_minutes: int = 0
    stop_after_misses: int = 10
    assistant_enabled: bool = False
    assistant_url: str = 'http://localhost:11434/v1'
    assistant_model: str = 'qwen3:8b'

    def to_dict(self):
        return asdict(self)


SAVE_ATTEMPTS = 6

# field -> (lowest, highest) for the numeric settings
RANGES = {'lure_minutes': (1, 240), 'cast_seconds': (5, 60), 'confidence': (0.5, 0.95),
          'checks_per_second': (1, 15), 'cpu_threads': (1, 8),
          'stop_after_minutes': (0, 1440), 'stop_after_misses': (0, 100)}

LABELS = {'fishing_key': 'Fishing key', 'lure_key': 'Lure key', 'lure_minutes': 'Lure duration',
          'pause_hotkey': 'Pause hotkey', 'stop_hotkey': 'Stop hotkey', 'cast_seconds': 'Cast time',
          'confidence': 'Confidence', 'scan_area': 'Scan area', 'checks_per_second': 'Checks per second',
          'cpu_threads': 'CPU threads', 'stop_after_minutes': 'Stop after minutes',
          'stop_after_misses': 'Stop after misses', 'assistant_url': 'Assistant server',
          'assistant_model': 'Assistant model', 'lure_enabled': 'Use a lure',
          'assistant_enabled': 'Assistant'}


def _coerce(name, value):
    """Convert one incoming value to the field's type, or raise ValueError with a readable reason."""
    default = getattr(Settings(), name)

    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        raise ValueError('must be on or off')

    if isinstance(default, (int, float)):
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError('must be a number')
        try:
            number = float(value)
        except (ValueError, OverflowError):
            raise ValueError('must be a number') from None
        if number != number or number in (float('inf'), float('-inf')):
            raise ValueError('must be a number')
        if isinstance(default, int):
            if number != int(number):
                raise ValueError('must be a whole number')
            number = int(number)
        low, high = RANGES[name]
        if not low <= number <= high:
            raise ValueError(f'must be between {low} and {high}')
        return number

    if not isinstance(value, str):
        raise ValueError('must be text')
    return value.strip()


def _check_text(name, value, system):
    if name in ('fishing_key', 'lure_key'):
        value = value.lower()
        if value and value not in keys.pressable_keys(system):
            raise ValueError(f"'{value}' is not a key the bot can press on this system")
    elif name in ('pause_hotkey', 'stop_hotkey'):
        value = value.lower()
        if value not in keys.HOTKEYS:
            raise ValueError('must be one of F1 to F12')
    elif name == 'scan_area':
        if value not in SCAN_AREAS:
            raise ValueError('must be full, center75 or center50')
    elif name == 'assistant_url':
        problem = ValueError('must be a web address such as http://localhost:11434/v1')
        if any(character.isspace() for character in value) or len(value) > 300:
            raise problem
        try:
            parsed = urlparse(value)
            parsed.port  # raises for a port that is not a number
        except ValueError:
            raise problem from None
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            raise problem
        value = value.rstrip('/')
    elif name == 'assistant_model':
        if not value or len(value) > 100:
            raise ValueError('must be a model name such as qwen3:8b')
    return value


def apply_changes(current, changes, system):
    """Apply ``changes`` (a dict of field -> new value) on top of ``current``.

    Returns (settings, errors). A field with an error keeps its current value; unknown fields
    are reported. ``errors`` maps field name to a readable message.
    """
    known = {field.name for field in fields(Settings)}
    values, errors = {}, {}

    for name, raw in changes.items():
        if name not in known:
            errors[name] = 'is not a setting'
            continue
        try:
            value = _coerce(name, raw)
            if isinstance(value, str):
                value = _check_text(name, value, system)
            values[name] = value
        except ValueError as error:
            errors[name] = str(error)

    # Rules that involve more than one field. The field that was just changed takes the blame and
    # is dropped; then the rules are checked again, because dropping one change can expose another
    # clash with a value that is being kept.
    def reject(name, message):
        if name in values:
            errors[name] = message
            values.pop(name)
            return True
        return False

    def drop_one_clash():
        candidate = replace(current, **values)

        if candidate.pause_hotkey == candidate.stop_hotkey:
            return any([reject(name, 'pause and stop need different keys') for name in ('stop_hotkey', 'pause_hotkey')])
        for name in ('fishing_key', 'lure_key'):
            key = getattr(candidate, name)
            for hotkey in ('pause_hotkey', 'stop_hotkey'):
                if key and key == getattr(candidate, hotkey):
                    return (reject(name, f'{key.upper()} is reserved for pausing or stopping the bot')
                            or reject(hotkey, f'{key.upper()} is already the {LABELS[name].lower()}'))
        if candidate.lure_key and candidate.lure_key == candidate.fishing_key:
            return any([reject(name, 'fishing and the lure need different keys') for name in ('lure_key', 'fishing_key')])
        return False

    while drop_one_clash():
        pass

    return replace(current, **values), errors


def problems_before_start(settings):
    """Reasons the bot cannot start with these settings, in plain words."""
    problems = []
    if not settings.fishing_key:
        problems.append('Set the key your fishing spell is bound to.')
    if settings.lure_enabled and not settings.lure_key:
        problems.append('Set the lure key, or turn the lure off.')
    return problems


def default_path():
    override = os.environ.get('WOW_FISH_YOLO_SETTINGS')
    if override:
        return Path(override)
    if sys.platform == 'win32':
        base = Path(os.environ.get('APPDATA') or Path.home() / 'AppData' / 'Roaming')
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library' / 'Application Support'
    else:
        base = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    return base / 'WoWFishYOLO' / 'settings.json'


class SettingsStore:
    """Loads settings from disk and writes them back on every change."""

    def __init__(self, path, system):
        self.path = Path(path)
        self.system = system
        self._lock = threading.Lock()
        self.settings = self._load()

    def _load(self):
        try:
            saved = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return Settings()
        if not isinstance(saved, dict):
            return Settings()
        # A value that no longer validates falls back to its default instead of blocking startup.
        settings, _ = apply_changes(Settings(), saved, self.system)
        return settings

    def update(self, changes):
        """Apply and save changes. Raises OSError if the file cannot be written; the new settings
        are still in effect for this run."""
        # One change at a time: requests arrive on several threads, and two half-applied
        # updates would lose one of them.
        with self._lock:
            settings, errors = apply_changes(self.settings, changes, self.system)
            if settings != self.settings:
                self.settings = settings
                self._save()
            return settings, errors

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f'{self.path.name}.{os.getpid()}.tmp')
        temporary.write_text(json.dumps(self.settings.to_dict(), indent=2), encoding='utf-8')
        for attempt in range(SAVE_ATTEMPTS):
            try:
                temporary.replace(self.path)
                return
            except PermissionError:
                # On Windows a virus scanner or a sync program can hold the file for a moment.
                if attempt == SAVE_ATTEMPTS - 1:
                    raise
                time.sleep(0.05 * (attempt + 1))
