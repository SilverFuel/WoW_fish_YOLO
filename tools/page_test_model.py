"""A stand-in for a local language model server, for tools/check_page.py only.

It speaks the same OpenAI-compatible API as Ollama and LM Studio and gives two canned answers:
one that suggests setting changes (one of them out of range on purpose), and one that only talks.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SUGGESTION = {'reply': 'Watching only the middle of the game and looking 4 times a second saves the most. '
                       'Press Check my game afterwards to check the bobber still lands inside the blue box.',
              'changes': {'scan_area': 'center50', 'checks_per_second': 4, 'cpu_threads': 99}}
PLAIN = {'reply': 'Check three things first: zoomed all the way in, the buttons and bars hidden with Alt+Z, '
                  'and Auto Loot switched on.', 'changes': {}}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *arguments):
        pass

    def _send(self, payload):
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send({'object': 'list', 'data': [{'id': 'qwen3:8b'}, {'id': 'llama3.2:3b'}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        question = body['messages'][-1]['content'].lower()
        answer = SUGGESTION if 'cpu' in question or 'computer' in question else PLAIN
        # Reasoning models put their thinking first; the app has to cope with that.
        self._send({'choices': [{'message': {'role': 'assistant', 'content': '<think>working it out</think>' + json.dumps(answer)}}]})


if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', int(sys.argv[1])), Handler).serve_forever()
