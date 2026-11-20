"""The local web interface: a small HTTP server for this computer only.

The page can start input automation, so the server is strict about who may talk to it:

- it listens on 127.0.0.1 only;
- the Host header must be this server, which defeats DNS rebinding;
- every API call needs a random token that is only handed to the page itself, and a custom
  header that a cross-site form or image cannot send.
"""
from __future__ import annotations

import hmac
import json
import secrets
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fishbot.assistant import Assistant, AssistantError

WEB =Path(__file__).resolve().parent / 'web'
STATIC = {'/app.js': ('app.js', 'text/javascript; charset=utf-8'),
          '/styles.css': ('styles.css', 'text/css; charset=utf-8'),
          '/favicon.svg': ('favicon.svg', 'image/svg+xml')}
MAX_BODY_BYTES = 64 * 1024
MAX_JSON_DEPTH = 32
DEFAULT_PORT = 8765
PORT_ATTEMPTS = 20
SECURITY_HEADERS = {
    'Content-Security-Policy': "default-src 'self'; img-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'",
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    'Cache-Control': 'no-store',
}


def nested_deeper_than(data, limit):
    """Whether JSON text nests objects and arrays more than ``limit`` deep (brackets inside strings do not count).

    Checked before parsing, because a parser that recurses can exhaust a thread's stack.
    """
    depth, in_string, escaped = 0, False, False
    for byte in data:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:  # backslash
                escaped = True
            elif byte == 0x22:  # quote
                in_string = False
        elif byte == 0x22:
            in_string = True
        elif byte in (0x5B, 0x7B):  # [ {
            depth += 1
            if depth > limit:
                return True
        elif byte in (0x5D, 0x7D):  # ] }
            depth -= 1
    return False


class BadRequest(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class AppServer:
    def __init__(self, service, port=DEFAULT_PORT):
        self.service = service
        self.assistant = Assistant(service)
        self.token = secrets.token_urlsafe(24)
        self.httpd = self._bind(port)
        self.httpd.app = self
        self.port = self.httpd.server_address[1]
        self.url = f'http://127.0.0.1:{self.port}/'

    @staticmethod
    def _bind(port):
        if port == 0:
            return ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        for candidate in range(port, port + PORT_ATTEMPTS):
            try:
                return ThreadingHTTPServer(('127.0.0.1', candidate), Handler)
            except OSError:
                continue
        raise OSError(f'No free port between {port} and {port + PORT_ATTEMPTS - 1}.')

    def allowed_hosts(self):
        return {f'127.0.0.1:{self.port}', f'localhost:{self.port}'}

    def serve_forever(self):
        self.httpd.serve_forever(poll_interval=0.2)

    def close(self):
        # shutdown() waits for serve_forever, so it must not run on a request thread.
        threading.Thread(target=self.httpd.shutdown, daemon=True).start()

    # ----- API -----

    def api_get(self, path, query):
        if path == '/api/state':
            try:
                since = int(query.get('since', ['0'])[0])
            except ValueError:
                raise BadRequest(400, 'since must be a number') from None
            return self.service.snapshot(since)
        raise BadRequest(404, 'Not found')

    def api_post(self, path, body):
        service = self.service

        if path == '/api/settings':
            try:
                settings, errors = service.store.update(body)
            except OSError as error:
                reason = error.strerror or str(error)
                settings = service.store.settings
                errors = {name: f'is in use now, but the settings file could not be saved ({reason})' for name in body}
            return {'settings': settings.to_dict(), 'errors': errors}
        if path == '/api/start':
            return {'problems': service.start()}
        if path == '/api/stop':
            service.stop('Stopped.')
            return {}
        if path == '/api/pause':
            if not isinstance(body.get('paused'), bool):
                raise BadRequest(400, 'paused must be true or false')
            service.set_paused(body['paused'])
            return {}
        if path == '/api/check':
            return service.check_setup()
        if path == '/api/quit':
            service.stop('Stopped: the app is closing.')
            self.close()
            return {}
        if path == '/api/assistant/test':
            return self.assistant.test()
        if path == '/api/assistant/chat':
            try:
                return self.assistant.chat(body.get('messages'))
            except AssistantError as error:
                raise BadRequest(error.status, str(error)) from None
        raise BadRequest(404, 'Not found')


class Handler(BaseHTTPRequestHandler):
    server_version = 'WoWFishYOLO'
    sys_version = ''
    protocol_version = 'HTTP/1.1'
    timeout = 60  # a connection that sends nothing must not hold a thread forever

    @property
    def app(self):
        return self.server.app

    def log_message(self, format, *args):
        pass  # the console is for the fishing log, not for page requests

    # ----- plumbing -----

    def _send(self, status, body, content_type):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload, status=200):
        self._send(status, json.dumps(payload).encode('utf-8'), 'application/json; charset=utf-8')

    def _fail(self, status, message):
        self.close_connection = True
        self._send_json({'error': message}, status)

    def _crashed(self):
        """Answer a request that hit a bug, so the page gets a message instead of a dropped connection."""
        traceback.print_exc()
        try:
            self._fail(500, 'Something went wrong in the app. The details are in its console window.')
        except OSError:
            pass

    def _check_host(self):
        if self.headers.get('Host', '') not in self.app.allowed_hosts():
            raise BadRequest(403, 'This address is not allowed.')

    def _check_token(self):
        sent = self.headers.get('X-Fishbot-Token', '')
        if not hmac.compare_digest(sent.encode('utf-8'), self.app.token.encode('utf-8')):
            raise BadRequest(403, 'Open the page again from the app; this session is not valid.')

    def _read_json(self):
        if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
            raise BadRequest(415, 'Send JSON.')
        origin = self.headers.get('Origin')
        if origin is not None and origin not in {f'http://{host}' for host in self.app.allowed_hosts()}:
            raise BadRequest(403, 'This origin is not allowed.')

        try:
            length = int(self.headers.get('Content-Length', ''))
        except ValueError:
            raise BadRequest(411, 'Content-Length is required.') from None
        if not 0 <= length <= MAX_BODY_BYTES:
            raise BadRequest(413, 'The request is too large.')

        data = self.rfile.read(length) or b'{}'
        if nested_deeper_than(data, MAX_JSON_DEPTH):
            raise BadRequest(400, 'The request is not valid JSON.')
        try:
            body = json.loads(data)
        except (ValueError, RecursionError):
            raise BadRequest(400, 'The request is not valid JSON.') from None
        if not isinstance(body, dict):
            raise BadRequest(400, 'The request must be a JSON object.')
        return body

    # ----- routes -----

    def do_GET(self):
        try:
            self._check_host()
            url = urlparse(self.path)

            if url.path == '/':
                page = (WEB / 'index.html').read_text(encoding='utf-8').replace('__TOKEN__', self.app.token)
                return self._send(200, page.encode('utf-8'), 'text/html; charset=utf-8')
            if url.path in STATIC:
                name, content_type = STATIC[url.path]
                return self._send(200, (WEB / name).read_bytes(), content_type)

            self._check_token()
            if url.path == '/api/preview.jpg':
                picture = self.app.service.preview_jpeg()
                if picture is None:
                    raise BadRequest(404, 'No picture yet.')
                return self._send(200, picture, 'image/jpeg')
            return self._send_json(self.app.api_get(url.path, parse_qs(url.query)))
        except BadRequest as error:
            self._fail(error.status, error.message)
        except Exception:
            self._crashed()

    def do_POST(self):
        try:
            self._check_host()
            self._check_token()
            body = self._read_json()
            self._send_json(self.app.api_post(urlparse(self.path).path, body))
        except BadRequest as error:
            self._fail(error.status, error.message)
        except Exception:
            self._crashed()
