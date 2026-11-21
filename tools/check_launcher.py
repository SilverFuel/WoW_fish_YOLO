"""Start WoW Fish YOLO the way a person would, by its launcher, and check that it comes up and quits.

    python tools/check_launcher.py

It runs the launcher for this system with a pretend game, waits for the page to answer, presses
Quit through the page's own address, and checks that the launcher ends cleanly. The first run
includes the one-time set-up, so it can take a few minutes. The GitHub workflow runs this on
Windows and macOS.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8791
ADDRESS = f'http://127.0.0.1:{PORT}/'
WAIT_FOR_PAGE_SEC = 900
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def launcher():
    extra = ['--demo', '--no-browser', '--port', str(PORT)]
    if sys.platform == 'win32':
        return ['cmd', '/c', str(ROOT / 'Start on Windows.bat'), *extra]
    return ['bash', str(ROOT / 'Start on Mac.command'), *extra]


def fetch(path, data=None, headers=None):
    request = urllib.request.Request(ADDRESS + path, data=data, headers=headers or {})
    with DIRECT.open(request, timeout=5) as response:
        return response.read().decode('utf-8')


def say(passed, text):
    print(f'{"PASS" if passed else "FAIL"}  {text}', flush=True)
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        print(f'::{"notice" if passed else "error"} title=Launcher ({sys.platform})::{"PASS" if passed else "FAIL"} {text}', flush=True)
    return passed


def main():
    started = time.monotonic()
    process = subprocess.Popen(launcher(), cwd=ROOT, stdin=subprocess.DEVNULL)

    hello = None
    while hello is None and process.poll() is None and time.monotonic() - started < WAIT_FOR_PAGE_SEC:
        try:
            hello = json.loads(fetch('api/hello'))
        except (OSError, ValueError):
            time.sleep(2)
    took = time.monotonic() - started

    if hello is None:
        process.kill()
        say(False, f'the page never answered (launcher exit code {process.poll()}, after {took:.0f} s)')
        return 1

    ok = say(hello.get('app') == 'wow-fish-yolo' and hello.get('demo') is True, f'the launcher brought the page up in {took:.0f} s: {hello}')

    page = fetch('')
    token = re.search(r'name="fishbot-token" content="([^"]+)"', page)
    ok &= say(token is not None and 'Start fishing' in page, 'the page is served and has its Start button')

    again = subprocess.run(launcher(), cwd=ROOT, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
    ok &= say(again.returncode == 0 and 'already running' in again.stdout, f'starting it a second time only points at the page: {again.stdout.strip()!r}')

    fetch('api/quit', data=b'{}', headers={'X-Fishbot-Token': token.group(1), 'Content-Type': 'application/json'})
    try:
        code = process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        code = None
    ok &= say(code == 0, f'Quit ends the launcher cleanly (exit code {code})')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
