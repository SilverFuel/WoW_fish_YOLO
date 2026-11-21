"""The control page's HTTP server, over real sockets, with the simulated game behind it."""
import http.client
import json
import threading

import pytest

from fishbot.server import AppServer
from fishbot.service import BotService
from fishbot.settings import SettingsStore
from tests.test_service import DemoPlatform, wait_for


@pytest.fixture
def app(tmp_path):
    platform = DemoPlatform()
    service = BotService(platform, SettingsStore(tmp_path / 'settings.json', platform.SYSTEM))
    server = AppServer(service, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.thread = thread
    yield server
    service.shutdown()
    server.httpd.shutdown()
    server.httpd.server_close()


def call(app, method, path, body=None, token=True, headers=None, host=None):
    connection = http.client.HTTPConnection('127.0.0.1', app.port, timeout=20)
    sent = {'Host': host or f'127.0.0.1:{app.port}'}
    if token:
        sent['X-Fishbot-Token'] = app.token if token is True else token
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        sent['Content-Type'] = 'application/json'
    sent.update(headers or {})
    connection.request(method, path, body=data, headers=sent)
    response = connection.getresponse()
    payload = response.read()
    connection.close()
    return response, payload


def call_json(app, method, path, body=None, **options):
    response, payload = call(app, method, path, body, **options)
    return response.status, json.loads(payload)


def test_page_is_served_with_the_token_and_strict_headers(app):
    response, payload = call(app, 'GET', '/', token=False)

    assert response.status == 200
    assert app.token in payload.decode()
    assert '__TOKEN__' not in payload.decode()
    assert "default-src 'self'" in response.getheader('Content-Security-Policy')
    assert response.getheader('X-Content-Type-Options') == 'nosniff'
    assert response.getheader('Cache-Control') == 'no-store'


@pytest.mark.parametrize('path, content_type', [('/app.js', 'text/javascript'), ('/styles.css', 'text/css'),
                                                ('/favicon.svg', 'image/svg+xml')])
def test_static_files_are_served(app, path, content_type):
    response, payload = call(app, 'GET', path, token=False)

    assert response.status == 200
    assert response.getheader('Content-Type').startswith(content_type)
    assert len(payload) > 100


@pytest.mark.parametrize('path', ['/../settings.py', '/index.html', '/web/app.js', '/api/unknown', '/favicon.ico'])
def test_nothing_else_is_served(app, path):
    response, _ = call(app, 'GET', path)

    assert response.status == 404


def test_api_needs_the_token(app):
    assert call_json(app, 'GET', '/api/state', token=False)[0] == 403
    assert call_json(app, 'GET', '/api/state', token='wrong')[0] == 403
    assert call_json(app, 'POST', '/api/start', {}, token=False)[0] == 403
    assert call(app, 'GET', '/api/preview.jpg', token=False)[0].status == 403
    assert not app.service.running


def test_requests_for_another_host_name_are_refused(app):
    # A DNS-rebinding page reaches this server under its own host name.
    assert call(app, 'GET', '/', token=False, host='evil.example:80')[0].status == 403
    assert call_json(app, 'GET', '/api/state', host=f'evil.example:{app.port}')[0] == 403
    assert call_json(app, 'GET', '/api/state', host=f'localhost:{app.port}')[0] == 200


def test_posts_from_another_origin_are_refused(app):
    status, _ = call_json(app, 'POST', '/api/start', {}, headers={'Origin': 'http://evil.example'})

    assert status == 403
    assert not app.service.running
    assert call_json(app, 'POST', '/api/settings', {}, headers={'Origin': f'http://127.0.0.1:{app.port}'})[0] == 200


def test_posts_must_be_json_objects_of_a_sane_size(app):
    assert call_json(app, 'POST', '/api/settings', b'x=1', headers={'Content-Type': 'text/plain'})[0] == 415
    assert call_json(app, 'POST', '/api/settings', b'{not json')[0] == 400
    assert call_json(app, 'POST', '/api/settings', [1, 2])[0] == 400
    assert call_json(app, 'POST', '/api/settings', {'fishing_key': 'f' * 100_000})[0] == 413
    assert call_json(app, 'POST', '/api/pause', {'paused': 'yes'})[0] == 400


def test_deeply_nested_json_is_refused_not_fatal(app):
    assert call_json(app, 'POST', '/api/settings', b'[' * 50_000)[0] == 400
    assert call_json(app, 'POST', '/api/settings', b'{"a":' * 40 + b'1' + b'}' * 40)[0] == 400
    assert call_json(app, 'GET', '/api/state')[0] == 200


def test_brackets_inside_text_do_not_count_as_nesting(app):
    from fishbot.server import MAX_JSON_DEPTH, nested_deeper_than

    text = json.dumps({'messages': [{'role': 'user', 'content': '[' * 500 + '"{' + '\\'}]}).encode()

    assert not nested_deeper_than(text, MAX_JSON_DEPTH)
    assert nested_deeper_than(b'[' * (MAX_JSON_DEPTH + 1), MAX_JSON_DEPTH)
    assert not nested_deeper_than(b'[' * MAX_JSON_DEPTH + b']' * MAX_JSON_DEPTH, MAX_JSON_DEPTH)
    assert call_json(app, 'POST', '/api/assistant/chat', text)[0] == 409  # parsed fine; the assistant is just off


def test_an_unwritable_settings_file_is_reported_and_the_change_still_applies(app):
    def cannot_save():
        raise PermissionError(13, 'Access is denied')

    app.service.store._save = cannot_save
    status, result = call_json(app, 'POST', '/api/settings', {'fishing_key': 'f'})

    assert status == 200
    assert result['settings']['fishing_key'] == 'f'
    assert result['errors'] == {'fishing_key': 'is in use now, but the settings file could not be saved (Access is denied)'}


def test_a_bug_in_a_request_gets_an_answer_and_the_server_keeps_running(app, capsys):
    def broken(since=0):
        raise RuntimeError('unexpected')

    working, app.service.snapshot = app.service.snapshot, broken
    status, result = call_json(app, 'GET', '/api/state')
    app.service.snapshot = working

    assert status == 500
    assert result == {'error': 'Something went wrong in the app. The details are in its console window.'}
    assert 'RuntimeError: unexpected' in capsys.readouterr().err
    assert call_json(app, 'GET', '/api/state')[0] == 200


def test_state_reports_what_the_page_needs(app):
    status, state = call_json(app, 'GET', '/api/state')

    assert status == 200
    assert state['state'] == 'idle' and state['running'] is False
    assert state['problems'] == ['Pick your fishing key first.']
    assert state['platform']['system'] == 'demo'
    assert call_json(app, 'GET', '/api/state?since=abc')[0] == 400


def test_settings_are_validated_and_saved(app):
    status, result = call_json(app, 'POST', '/api/settings', {'fishing_key': 'F', 'cast_seconds': 500})

    assert status == 200
    assert result['settings']['fishing_key'] == 'f'
    assert result['settings']['cast_seconds'] == 20
    assert list(result['errors']) == ['cast_seconds']
    assert app.service.store.settings.fishing_key == 'f'


def test_start_reports_problems_instead_of_starting(app):
    status, result = call_json(app, 'POST', '/api/start', {})

    assert status == 200
    assert result == {'problems': ['Pick your fishing key first.']}


def test_full_session_over_http(app):
    call_json(app, 'POST', '/api/settings', {'fishing_key': 'f', 'checks_per_second': 15})
    assert call_json(app, 'POST', '/api/start', {})[1] == {'problems': []}
    assert wait_for(lambda: call_json(app, 'GET', '/api/state')[1]['stats']['looted'] >= 1)

    call_json(app, 'POST', '/api/pause', {'paused': True})
    assert wait_for(lambda: call_json(app, 'GET', '/api/state')[1]['state'] == 'paused')
    call_json(app, 'POST', '/api/pause', {'paused': False})
    assert wait_for(lambda: call_json(app, 'GET', '/api/state')[1]['state'] == 'fishing')

    response, picture = call(app, 'GET', '/api/preview.jpg')
    assert response.status == 200 and response.getheader('Content-Type') == 'image/jpeg'
    assert picture[:2] == b'\xff\xd8'

    call_json(app, 'POST', '/api/stop', {})
    assert wait_for(lambda: call_json(app, 'GET', '/api/state')[1]['running'] is False)
    final = call_json(app, 'GET', '/api/state')[1]
    assert final['message'] == 'Stopped.'
    assert any(entry['message'].startswith('Got a bite and clicked the bobber') for entry in final['log'])


def test_preview_is_404_before_any_picture_and_check_provides_one(app):
    assert call(app, 'GET', '/api/preview.jpg')[0].status == 404

    status, result = call_json(app, 'POST', '/api/check', {})

    assert status == 200 and result['ok'] is True
    assert call(app, 'GET', '/api/preview.jpg')[0].status == 200


def test_pictures_of_recent_clicks_are_served(app):
    assert call(app, 'GET', '/api/click.jpg?id=1')[0].status == 404
    assert call(app, 'GET', '/api/click.jpg?id=abc')[0].status == 404
    assert call(app, 'GET', '/api/click.jpg?id=1', token=False)[0].status == 403

    call_json(app, 'POST', '/api/settings', {'fishing_key': 'f', 'checks_per_second': 15})
    call_json(app, 'POST', '/api/start', {})
    assert wait_for(lambda: call_json(app, 'GET', '/api/state')[1]['clicks'] != [])

    click = call_json(app, 'GET', '/api/state')[1]['clicks'][0]
    response, picture = call(app, 'GET', f'/api/click.jpg?id={click["id"]}')
    assert response.status == 200 and response.getheader('Content-Type') == 'image/jpeg'
    assert picture[:2] == b'\xff\xd8'


def test_assistant_chat_is_refused_while_switched_off(app):
    status, result = call_json(app, 'POST', '/api/assistant/chat', {'messages': [{'role': 'user', 'content': 'hi'}]})

    assert status == 409
    assert result == {'error': 'Turn the assistant on first.'}


def test_quit_stops_the_server(app):
    assert app.thread.is_alive()

    assert call_json(app, 'POST', '/api/quit', {})[0] == 200

    app.thread.join(5)
    assert not app.thread.is_alive()


def test_hello_needs_no_token_and_says_only_what_a_second_launch_needs(app):
    status, hello = call_json(app, 'GET', '/api/hello', token=False)

    assert status == 200
    assert hello == {'app': 'wow-fish-yolo', 'demo': True}
    assert call_json(app, 'GET', '/api/hello', token=False, host='evil.example:80')[0] == 403


def test_the_get_ready_picture_is_served(app):
    response, picture = call(app, 'GET', '/ready.jpg', token=False)

    assert response.status == 200 and response.getheader('Content-Type') == 'image/jpeg'
    assert picture[:2] == b'\xff\xd8'


def test_practice_is_a_way_of_starting(app):
    call_json(app, 'POST', '/api/settings', {'fishing_key': 'f'})

    assert call_json(app, 'POST', '/api/start', {'practice': True})[1] == {'problems': []}
    assert wait_for(lambda: call_json(app, 'GET', '/api/state')[1]['state'] == 'practice')

    state = call_json(app, 'GET', '/api/state')[1]
    assert state['practice'] is True
    assert 'practice_mode' not in state['settings']
    assert app.service.platform.game.events == []


def test_starting_a_second_time_finds_the_copy_that_is_running(app):
    import bot

    assert bot.already_running(app.port, demo=True) == f'http://127.0.0.1:{app.port}/'
    assert bot.already_running(app.port, demo=False) is None  # the real thing must not reuse a demo


def test_nothing_running_means_a_normal_start():
    import socket

    import bot

    probe = socket.socket()
    probe.bind(('127.0.0.1', 0))
    free_port = probe.getsockname()[1]
    probe.close()

    assert bot.already_running(free_port, demo=False) is None


def test_a_second_launch_opens_the_page_and_exits(app, monkeypatch, capsys):
    import bot

    opened = []
    monkeypatch.setattr(bot.webbrowser, 'open', opened.append)

    assert bot.main(['--demo', '--port', str(app.port)]) == 0

    assert opened == [f'http://127.0.0.1:{app.port}/']
    assert 'already running' in capsys.readouterr().out
