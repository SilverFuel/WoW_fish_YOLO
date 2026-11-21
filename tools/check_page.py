"""Open the page in a real browser against the pretend game and use it the way a person would.

    python tools/check_page.py [folder for screenshots]

It starts the app with the pretend game and a stand-in for a local language model, runs
tools/page_test.js against them, and stops both. Nothing on this computer is pressed or clicked.

Needs Node.js with Playwright: npm install playwright, then npx playwright install chromium.
The GitHub workflow runs this on Linux.
"""
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
WAIT_FOR_APP_SEC = 60


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def answers(address):
    try:
        with DIRECT.open(address, timeout=2) as response:
            json.loads(response.read().decode('utf-8'))
        return True
    except (OSError, ValueError):
        return False


def main():
    node = shutil.which('node')
    if node is None:
        print('Node.js is needed for this check, and it was not found.')
        return 2

    pictures = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
    if pictures is not None:
        pictures.mkdir(parents=True, exist_ok=True)

    page_port, model_port = free_port(), free_port()
    page, model = f'http://127.0.0.1:{page_port}/', f'http://127.0.0.1:{model_port}/v1'

    with tempfile.TemporaryDirectory() as temporary:
        helpers = [
            subprocess.Popen([sys.executable, str(ROOT / 'tools' / 'page_test_model.py'), str(model_port)]),
            subprocess.Popen([sys.executable, str(ROOT / 'bot.py'), '--demo', '--no-browser', '--port', str(page_port),
                              '--settings', str(Path(temporary) / 'settings.json')], cwd=ROOT),
        ]
        try:
            deadline = time.monotonic() + WAIT_FOR_APP_SEC
            while not (answers(page + 'api/hello') and answers(model + '/models')):
                if time.monotonic() > deadline or any(helper.poll() is not None for helper in helpers):
                    print('The app or the stand-in model server did not come up.')
                    return 1
                time.sleep(0.5)

            command = [node, str(ROOT / 'tools' / 'page_test.js'), page, model]
            return subprocess.run(command + ([str(pictures)] if pictures else []), cwd=ROOT).returncode
        finally:
            for helper in helpers:
                helper.terminate()
            for helper in helpers:
                try:
                    helper.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    helper.kill()


if __name__ == '__main__':
    sys.exit(main())
