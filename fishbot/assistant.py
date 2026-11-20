"""Optional helper that talks to a language model running on the user's own computer.

It speaks the OpenAI-compatible chat API, which Ollama, LM Studio and llama.cpp all provide, so
any local model works; the default is Qwen3 8B on Ollama. The model is given the current
settings, statistics and recent log lines, and may answer and *suggest* setting changes.
Suggestions go through the same validation as the settings form and are only applied when the
user presses Apply. The model never controls the game and is never part of the fishing loop.
"""
from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.request
from urllib.parse import urlparse

from fishbot.settings import LABELS, RANGES, apply_changes

TIMEOUT_SEC = 180
TEST_TIMEOUT_SEC = 8
MAX_MESSAGES = 20
MAX_MESSAGE_CHARS = 4000
MAX_REPLY_TOKENS = 700
LOG_LINES_SHARED = 15
LOOPBACK_HOSTS = {'localhost', '127.0.0.1', '::1'}

# The settings the model may suggest, with the values it may use. Its own connection
# settings are deliberately absent: a model must not be able to redirect itself.
SUGGESTABLE = {
    'fishing_key': 'key the Fishing spell is bound to, e.g. "f", "1", "f5", "space"',
    'lure_enabled': 'true or false',
    'lure_key': 'key the lure is bound to',
    'lure_minutes': 'how long one lure lasts',
    'cast_seconds': 'how long to wait for a bite before casting again (default 20)',
    'confidence': 'how sure the detector must be, as a fraction (default 0.8)',
    'scan_area': '"full" (whole window, most reliable), "center75" (about half the CPU) or "center50" (about a quarter)',
    'checks_per_second': 'how often it looks for the splash (default 5)',
    'cpu_threads': 'CPU threads for the detector (default 2)',
    'stop_after_minutes': 'stop after this many minutes, 0 = no limit',
    'stop_after_misses': 'stop after this many casts in a row with no catch, 0 = off (default 10)',
    'pause_hotkey': '"f1" to "f12"',
    'stop_hotkey': '"f1" to "f12"',
}

GUIDE = """\
You are the built-in helper of WoW Fish YOLO, a fishing bot for World of Warcraft that runs on the user's own computer.
You help the user set the bot up and fix problems. You cannot see the screen or the game and you cannot press keys.
You can only answer and suggest setting changes; the user decides whether to apply them.

How the bot works:
- It presses the fishing key, then looks at the game window a few times a second with a small vision model.
  When it sees the bobber splash it right-clicks the bobber. Auto Loot must be on in the game.
- It only sends keys and clicks while the game is the window in front.
- The model was trained in first-person view with the game interface hidden (Alt+Z).
- "Check now" on the page shows what the bot sees and the area it scans.

Common problems:
- Every cast misses: not in first-person view; interface not hidden; the bobber lands outside the scanned area
  (use "full"); wrong fishing key; bags are full; confidence too high (try 0.7); cast_seconds shorter than the real cast.
- Nothing happens: the game is not the window in front; on macOS the Accessibility permission is missing;
  on Windows the game runs as administrator and the bot does not.
- The preview is black on macOS: the Screen Recording permission is missing.
- High CPU use: a smaller scan_area, fewer checks_per_second, fewer cpu_threads.

Rules:
- Keep answers short and in plain language.
- Suggest changes only when the user asks for them or they clearly fix the problem described.
- Only use the settings listed below, with values in the allowed range.
- Do not help with hiding the bot from the game or its operator. Say you cannot help with that.
"""

ANSWER_FORMAT = """\
Answer with one JSON object and nothing else:
{"reply": "<what to tell the user>", "changes": {"<setting>": <new value>}}
Use {} for "changes" when no setting should change.
"""


class AssistantError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def strip_thinking(text):
    """Remove the reasoning block that thinking models such as Qwen3 put before the answer."""
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    if '<think>' in text:  # the answer was cut off while the model was still thinking
        text = text.split('<think>', 1)[0]
    return text.strip()


def parse_answer(text):
    """Split the model's text into (reply, changes). Text that is not the JSON asked for is the reply."""
    text = strip_thinking(text)
    decoder = json.JSONDecoder()

    for start, character in enumerate(text):
        if character != '{':
            continue
        try:
            candidate, _ = decoder.raw_decode(text[start:])
        except ValueError:
            continue
        if isinstance(candidate, dict) and ('reply' in candidate or 'changes' in candidate):
            reply = candidate.get('reply')
            changes = candidate.get('changes')
            return (reply.strip() if isinstance(reply, str) else '',
                    changes if isinstance(changes, dict) else {})

    return text, {}


def review_changes(settings, proposed, system):
    """Check proposed changes. Returns (changes that are valid and new, {name: why it was rejected})."""
    allowed = {name: value for name, value in proposed.items() if name in SUGGESTABLE}
    rejected = {name: 'the assistant may not change this' for name in proposed if name not in SUGGESTABLE}

    updated, errors = apply_changes(settings, allowed, system)
    rejected.update(errors)
    changes = {name: getattr(updated, name) for name in allowed
               if name not in errors and getattr(updated, name) != getattr(settings, name)}
    return changes, rejected


def describe_settings():
    lines = []
    for name, meaning in SUGGESTABLE.items():
        allowed = f' Allowed: {RANGES[name][0]} to {RANGES[name][1]}.' if name in RANGES else ''
        lines.append(f'- {name}: {meaning}.{allowed}')
    return '\n'.join(lines)


class Assistant:
    def __init__(self, service):
        self._service = service

    # ----- talking to the model server -----

    def _request(self, path, payload=None, timeout=TIMEOUT_SEC):
        settings = self._service.store.settings
        url = f'{settings.assistant_url}{path}'
        data = None if payload is None else json.dumps(payload).encode('utf-8')
        request = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})

        # A server on this computer must be reached directly, never through a system proxy.
        local = (urlparse(url).hostname or '') in LOOPBACK_HOSTS
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if local else urllib.request.build_opener()

        try:
            with opener.open(request, timeout=timeout) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as error:
            detail = error.read().decode('utf-8', 'replace')[:300]
            if error.code == 404 and 'model' in detail.lower():
                raise AssistantError(502, f'The server does not have the model "{settings.assistant_model}". '
                                          f'With Ollama, run: ollama pull {settings.assistant_model}') from None
            raise AssistantError(502, f'The model server answered with an error ({error.code}). {detail}'.strip()) from None
        except (TimeoutError, socket.timeout):
            raise AssistantError(504, 'The model took too long to answer. Try a smaller model.') from None
        except (urllib.error.URLError, ConnectionError, OSError) as error:
            raise AssistantError(502, f'Could not reach {settings.assistant_url}. Is the model server running? '
                                      f'({getattr(error, "reason", error)})') from None
        except ValueError:
            raise AssistantError(502, 'The model server sent an answer that could not be read.') from None

    def test(self):
        settings = self._service.store.settings
        try:
            listing = self._request('/models', timeout=TEST_TIMEOUT_SEC)
        except AssistantError as error:
            return {'ok': False, 'message': str(error), 'models': []}

        entries = listing.get('data') if isinstance(listing, dict) else None
        models = sorted(str(entry.get('id')) for entry in entries or [] if isinstance(entry, dict) and entry.get('id'))
        wanted = settings.assistant_model
        installed = wanted in models or f'{wanted}:latest' in models

        if installed:
            message = f'Connected. {wanted} is ready.'
        elif models:
            message = f'Connected, but {wanted} is not installed. With Ollama, run: ollama pull {wanted}'
        else:
            message = 'Connected, but the server lists no models.'
        if (urlparse(settings.assistant_url).hostname or '') not in LOOPBACK_HOSTS:
            message += ' Note: this server is another computer; your settings and log lines are sent to it.'
        return {'ok': installed, 'message': message, 'models': models}

    # ----- chat -----

    def _system_prompt(self):
        snapshot = self._service.snapshot()
        settings = self._service.store.settings
        current = {name: getattr(settings, name) for name in SUGGESTABLE}
        stats = snapshot['stats']
        recent = [entry['message'] for entry in snapshot['log'][-LOG_LINES_SHARED:]]

        prompt = '\n'.join([
            GUIDE,
            'Settings you may suggest:',
            describe_settings(),
            '',
            f'Current settings: {json.dumps(current)}',
            f'System: {snapshot["platform"]["label"]}. Bot state: {snapshot["state"]}.',
            f'Last or current session: {stats["casts"]} casts, {stats["looted"]} caught, {stats["missed"]} missed, '
            f'{stats["inference_ms"]} ms per look.',
            'Recent activity:' if recent else 'Recent activity: none yet.',
            *[f'- {line}' for line in recent],
            '',
            ANSWER_FORMAT,
        ])
        # Qwen3 thinks out loud by default, which is slow on a home computer; this is its off switch.
        if 'qwen3' in settings.assistant_model.lower():
            prompt += '/no_think\n'
        return prompt

    @staticmethod
    def _check_messages(messages):
        if not isinstance(messages, list) or not 1 <= len(messages) <= MAX_MESSAGES:
            raise AssistantError(400, 'Send between 1 and 20 messages.')
        for message in messages:
            if (not isinstance(message, dict) or message.get('role') not in ('user', 'assistant')
                    or not isinstance(message.get('content'), str)
                    or not 0 < len(message['content']) <= MAX_MESSAGE_CHARS):
                raise AssistantError(400, 'A message is missing, empty or too long.')
        if messages[-1]['role'] != 'user':
            raise AssistantError(400, 'The last message must be yours.')

    def chat(self, messages):
        settings = self._service.store.settings
        if not settings.assistant_enabled:
            raise AssistantError(409, 'Turn the assistant on first.')
        self._check_messages(messages)

        conversation = [{'role': 'system', 'content': self._system_prompt()}]
        for message in messages:
            content = message['content']
            if message['role'] == 'assistant':
                # Show the model its earlier answers in the format it is asked to keep using.
                content = json.dumps({'reply': content, 'changes': {}})
            conversation.append({'role': message['role'], 'content': content})

        answer = self._request('/chat/completions', {
            'model': settings.assistant_model, 'messages': conversation,
            'temperature': 0.2, 'max_tokens': MAX_REPLY_TOKENS, 'stream': False})

        try:
            text = answer['choices'][0]['message']['content']
        except (KeyError, IndexError, TypeError):
            raise AssistantError(502, 'The model server sent an answer that could not be read.') from None
        if not isinstance(text, str):
            raise AssistantError(502, 'The model server sent an answer that could not be read.')

        reply, proposed = parse_answer(text)
        changes, rejected = review_changes(settings, proposed, self._service.platform.SYSTEM)
        if not reply:
            if not changes and not rejected:
                raise AssistantError(502, 'The model returned an empty answer. Try again, or try a different model.')
            reply = 'Here is what I suggest.'

        return {'reply': reply, 'changes': changes, 'rejected': rejected,
                'labels': {name: LABELS.get(name, name) for name in {**changes, **rejected}}}
