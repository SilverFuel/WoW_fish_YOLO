"""The assistant, against a stand-in model server that speaks the OpenAI-compatible API.

No real language model runs in these tests: they check what is sent, and that whatever comes
back is parsed and validated safely.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from fishbot import assistant as assistant_module
from fishbot.assistant import Assistant, AssistantError, parse_answer, review_changes, strip_thinking
from fishbot.service import BotService
from fishbot.settings import Settings, SettingsStore
from tests.test_service import DemoPlatform


class FakeModelServer:
    def __init__(self):
        self.requests = []
        self.models = ['qwen3:8b', 'llama3.2:3b']
        self.answer = json.dumps({'reply': 'Hello.', 'changes': {}})
        self.status = 200
        self.error_body = ''
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def _send(self, status, payload):
                data = payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                outer.requests.append(('GET', self.path, None))
                if self.path == '/v1/models':
                    return self._send(200, {'object': 'list', 'data': [{'id': name} for name in outer.models]})
                return self._send(404, {'error': 'not found'})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                outer.requests.append(('POST', self.path, body))
                if outer.status != 200:
                    return self._send(outer.status, outer.error_body)
                return self._send(200, {'choices': [{'message': {'role': 'assistant', 'content': outer.answer}}]})

        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.httpd.server_address[1]}/v1'
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def model_server():
    server = FakeModelServer()
    yield server
    server.close()


@pytest.fixture
def helper(model_server, tmp_path):
    platform = DemoPlatform()
    store = SettingsStore(tmp_path / 'settings.json', platform.SYSTEM)
    store.update({'fishing_key': 'f', 'assistant_enabled': True, 'assistant_url': model_server.url})
    return Assistant(BotService(platform, store))


def ask(helper, text='Set me up'):
    return helper.chat([{'role': 'user', 'content': text}])


def ask_with(helper, messages):
    return helper.chat(messages)


# ----- reading the model's answer -----

def test_strip_thinking_removes_reasoning_blocks():
    assert strip_thinking('<think>\nlong reasoning\n</think>\n\nThe answer.') == 'The answer.'
    assert strip_thinking('The answer.') == 'The answer.'
    assert strip_thinking('Partly said <think>cut off mid thought') == 'Partly said'


@pytest.mark.parametrize('text, reply, changes', [
    ('{"reply": "Done.", "changes": {"cast_seconds": 30}}', 'Done.', {'cast_seconds': 30}),
    ('<think>hmm {"x": 1}</think>{"reply": "Done.", "changes": {}}', 'Done.', {}),
    ('Sure!\n```json\n{"reply": "Done.", "changes": {"scan_area": "center50"}}\n```', 'Done.', {'scan_area': 'center50'}),
    ('{"reply": "Only talking."}', 'Only talking.', {}),
    ('{"changes": {"cpu_threads": 1}}', '', {'cpu_threads': 1}),
    ('{"reply": "Bad changes.", "changes": "none"}', 'Bad changes.', {}),
    ('{"reply": 5, "changes": {}}', '', {}),
    ('Just plain text, no JSON at all.', 'Just plain text, no JSON at all.', {}),
    ('A brace { that is not JSON', 'A brace { that is not JSON', {}),
    ('', '', {}),
])
def test_parse_answer_copes_with_what_models_actually_send(text, reply, changes):
    assert parse_answer(text) == (reply, changes)


def test_review_keeps_valid_new_values_and_explains_the_rest():
    current = Settings(fishing_key='f', cast_seconds=20)

    changes, rejected = review_changes(current, {
        'fishing_key': 'f',            # no change
        'cast_seconds': 30,            # fine
        'confidence': 5,               # out of range
        'scan_area': 'center50',       # fine
        'assistant_url': 'http://evil.example/v1',   # not the model's to change
        'assistant_enabled': False,
        'made_up': 1,
    }, 'windows')

    assert changes == {'cast_seconds': 30, 'scan_area': 'center50'}
    assert set(rejected) == {'confidence', 'assistant_url', 'assistant_enabled', 'made_up'}
    assert rejected['assistant_url'] == 'the assistant may not change this'


def test_every_suggestable_setting_exists_and_excludes_the_connection():
    names = set(Settings().to_dict())

    assert set(assistant_module.SUGGESTABLE) <= names
    assert not {name for name in assistant_module.SUGGESTABLE if name.startswith('assistant_')}


# ----- talking to the server -----

def test_test_reports_an_installed_model(helper, model_server):
    result = helper.test()

    assert result == {'ok': True, 'message': 'Connected. qwen3:8b is ready.', 'models': ['llama3.2:3b', 'qwen3:8b']}
    assert model_server.requests == [('GET', '/v1/models', None)]


def test_test_says_how_to_get_a_missing_model(helper, model_server):
    model_server.models = ['llama3.2:3b']

    result = helper.test()

    assert result['ok'] is False
    assert result['message'] == 'Connected, but qwen3:8b is not installed. With Ollama, run: ollama pull qwen3:8b'


def test_test_accepts_the_latest_tag(helper, model_server):
    model_server.models = ['mistral:latest']
    helper._service.store.update({'assistant_model': 'mistral'})

    assert helper.test()['ok'] is True


def test_test_explains_an_unreachable_server(helper, model_server):
    model_server.close()

    result = helper.test()

    assert result['ok'] is False
    assert result['message'].startswith(f'Could not reach {model_server.url}. Is the model server running?')


def test_chat_sends_an_openai_style_request_with_the_bots_context(helper, model_server):
    result = ask(helper, 'Why does it miss?')

    method, path, body = model_server.requests[-1]
    system, user = body['messages']
    assert (method, path) == ('POST', '/v1/chat/completions')
    assert body['model'] == 'qwen3:8b' and body['stream'] is False
    assert (system['role'], user) == ('system', {'role': 'user', 'content': 'Why does it miss?'})
    assert '"fishing_key": "f"' in system['content']
    assert 'scan_area' in system['content'] and 'Allowed: 5 to 60.' in system['content']
    assert 'assistant_url' not in system['content']
    assert system['content'].rstrip().endswith('/no_think')
    assert result == {'reply': 'Hello.', 'changes': {}, 'rejected': {}, 'labels': {}}


def test_no_think_switch_is_only_sent_to_qwen3(helper, model_server):
    helper._service.store.update({'assistant_model': 'llama3.2:3b'})

    ask(helper)

    assert '/no_think' not in model_server.requests[-1][2]['messages'][0]['content']


def test_earlier_answers_are_replayed_in_the_answer_format(helper, model_server):
    helper.chat([{'role': 'user', 'content': 'hi'}, {'role': 'assistant', 'content': 'Hello.'},
                 {'role': 'user', 'content': 'and now?'}])

    sent = model_server.requests[-1][2]['messages']
    assert [message['role'] for message in sent] == ['system', 'user', 'assistant', 'user']
    assert json.loads(sent[2]['content']) == {'reply': 'Hello.', 'changes': {}}


def test_chat_returns_validated_suggestions_without_applying_them(helper, model_server):
    model_server.answer = '<think>They want less CPU.</think>' + json.dumps({
        'reply': 'A smaller area and fewer looks will help.',
        'changes': {'scan_area': 'center50', 'checks_per_second': 4, 'cpu_threads': 99,
                    'assistant_url': 'http://evil.example/v1'}})

    result = ask(helper, 'Use less CPU')

    assert result['reply'] == 'A smaller area and fewer looks will help.'
    assert result['changes'] == {'scan_area': 'center50', 'checks_per_second': 4}
    assert set(result['rejected']) == {'cpu_threads', 'assistant_url'}
    assert result['labels']['scan_area'] == 'Scan area'
    # Nothing changed: applying is the user's decision.
    assert helper._service.store.settings.scan_area == 'full'
    assert helper._service.store.settings.assistant_url == model_server.url


def test_plain_text_answers_are_shown_as_they_are(helper, model_server):
    model_server.answer = 'Check that the interface is hidden.'

    assert ask(helper)['reply'] == 'Check that the interface is hidden.'


def test_suggestions_without_a_reply_get_a_default_sentence(helper, model_server):
    model_server.answer = json.dumps({'changes': {'cast_seconds': 30}})

    assert ask(helper) == {'reply': 'Here is what I suggest.', 'changes': {'cast_seconds': 30},
                           'rejected': {}, 'labels': {'cast_seconds': 'Cast time'}}


def test_an_empty_answer_is_an_error(helper, model_server):
    model_server.answer = '<think>nothing to say</think>'

    with pytest.raises(AssistantError, match='empty answer'):
        ask(helper)


def test_a_missing_model_is_explained(helper, model_server):
    model_server.status = 404
    model_server.error_body = json.dumps({'error': {'message': 'model "qwen3:8b" not found, try pulling it first'}})

    with pytest.raises(AssistantError, match='ollama pull qwen3:8b'):
        ask(helper)


def test_other_server_errors_are_passed_on(helper, model_server):
    model_server.status = 500
    model_server.error_body = 'out of memory'

    with pytest.raises(AssistantError, match=r'error \(500\). out of memory'):
        ask(helper)


def test_a_malformed_server_reply_is_an_error(helper, model_server):
    model_server.answer = None

    with pytest.raises(AssistantError, match='could not be read'):
        ask(helper)


@pytest.mark.parametrize('messages', [
    None, [], 'hi', [{'role': 'user'}], [{'role': 'system', 'content': 'x'}],
    [{'role': 'user', 'content': ''}], [{'role': 'user', 'content': 'x' * 5000}],
    [{'role': 'user', 'content': '   '}],
    [{'role': 'user', 'content': 'hi'}, {'role': 'assistant', 'content': 'yo'}],
])
def test_bad_conversations_are_refused_before_anything_is_sent(helper, model_server, messages):
    with pytest.raises(AssistantError):
        helper.chat(messages)

    assert model_server.requests == []


def test_a_long_conversation_is_trimmed_instead_of_refused(helper, model_server):
    history = []
    for number in range(30):
        history.append({'role': 'user', 'content': f'question {number}'})
        history.append({'role': 'assistant', 'content': 'x' * 9000})  # longer than a message may be
    history.append({'role': 'user', 'content': 'the latest question'})

    assert ask_with(helper, history)['reply'] == 'Hello.'

    sent = model_server.requests[-1][2]['messages'][1:]
    assert len(sent) <= 20
    assert sent[0]['role'] == 'user'  # never starts with the assistant
    assert sent[-1] == {'role': 'user', 'content': 'the latest question'}
    assert all(len(json.loads(message['content'])['reply']) == 4000 for message in sent if message['role'] == 'assistant')


def test_a_server_that_does_not_speak_http_is_explained(helper):
    import socket

    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)

    def answer_with_garbage():
        connection, _ = listener.accept()
        connection.recv(65536)
        connection.sendall(b'this is not http\r\n\r\n')
        connection.close()

    threading.Thread(target=answer_with_garbage, daemon=True).start()
    helper._service.store.update({'assistant_url': f'http://127.0.0.1:{listener.getsockname()[1]}/v1'})

    with pytest.raises(AssistantError, match='did not answer like a model server'):
        ask(helper)
    listener.close()


def test_chat_is_refused_while_the_assistant_is_off(helper, model_server):
    helper._service.store.update({'assistant_enabled': False})

    with pytest.raises(AssistantError, match='Turn the assistant on first'):
        ask(helper)

    assert model_server.requests == []
