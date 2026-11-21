"""Start WoW Fish YOLO the way a person would, by its starter, and check what happens.

    python tools/check_launcher.py

Three situations, on whatever system this runs on:

  1. No Python on the computer: the starter says which Python to get.
  2. Only a Python that is too new: the starter tries it, and says so when set-up fails.
  3. The normal case: set-up, the page comes up, a second start points at the page, Quit ends it.

The first two run in a throwaway copy with a pretend Python, so nothing is installed for them.
The third includes the real one-time set-up and can take a few minutes. The GitHub workflow runs
this on Windows and macOS.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = sys.platform == 'win32'
STARTER = 'Start on Windows.bat' if WINDOWS else 'Start on Mac.command'
SHELL = os.environ.get('ComSpec', 'cmd.exe') if WINDOWS else shutil.which('bash')
PORT = 8791
ADDRESS = f'http://127.0.0.1:{PORT}/'
WAIT_FOR_PAGE_SEC = 900
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# Stands in for a Python that is newer than anything the app's parts are built for.
PRETEND_PYTHON = """import sys
arguments = sys.argv[1:]
if arguments[:1] == ['-c']:
    sys.version_info = (3, 15, 0, 'final', 0)
    exec(arguments[1])
    sys.exit(0)
print('ERROR: No matching distribution found for onnxruntime>=1.17', file=sys.stderr)
sys.exit(1)
"""


def starter(folder, *extra):
    return [SHELL, '/c', str(folder / STARTER), *extra] if WINDOWS else [SHELL, str(folder / STARTER), *extra]


def say(passed, text):
    print(f'{"PASS" if passed else "FAIL"}  {text}', flush=True)
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        print(f'::{"notice" if passed else "error"} title=Starter ({sys.platform})::{"PASS" if passed else "FAIL"} {text}', flush=True)
    return passed


# ----- the two situations where it cannot start -----

def bare_copy(folder):
    """Just the starter and the list of what it needs, with no set-up done."""
    folder.mkdir()
    for name in (STARTER, 'requirements.txt'):
        shutil.copy2(ROOT / name, folder / name)
    return folder


def search_path(folder, with_pretend_python):
    """A PATH with the system's own tools and no Python, or only the pretend one."""
    programs = folder / 'programs'
    programs.mkdir()
    if WINDOWS:
        system = str(Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32')
        if with_pretend_python:
            (programs / 'pretend_python.py').write_text(PRETEND_PYTHON)
            (programs / 'python.bat').write_text(f'@"{sys.executable}" "{programs / "pretend_python.py"}" %*\r\n')
        return os.pathsep.join([str(programs), system])

    for tool in ('cmp', 'dirname', 'uname', 'cp', 'cat'):
        (programs / tool).symlink_to(shutil.which(tool))
    if with_pretend_python:
        (programs / 'pretend_python.py').write_text(PRETEND_PYTHON)
        pretend = programs / 'python3'
        pretend.write_text(f'#!/bin/bash\nexec "{sys.executable}" "{programs / "pretend_python.py"}" "$@"\n')
        pretend.chmod(0o755)
    return str(programs)


def cannot_start(with_pretend_python, expected, description):
    with tempfile.TemporaryDirectory() as temporary:
        folder = bare_copy(Path(temporary) / 'copy')
        environment = dict(os.environ, PATH=search_path(Path(temporary), with_pretend_python))
        result = subprocess.run(starter(folder), cwd=folder, env=environment, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=180)
        output = result.stdout + result.stderr
        said = ' '.join(output.split())
        passed = result.returncode == 1 and all(text in said for text in expected) and 'Traceback' not in output
        if not passed:
            print(output, flush=True)
        return say(passed, f'{description} (exit code {result.returncode}): {said[:300]!r}')


# ----- the normal case -----

def fetch(path, data=None, headers=None):
    request = urllib.request.Request(ADDRESS + path, data=data, headers=headers or {})
    with DIRECT.open(request, timeout=5) as response:
        return response.read().decode('utf-8')


def starts_and_quits():
    extra = ('--demo', '--no-browser', '--port', str(PORT))
    started = time.monotonic()
    process = subprocess.Popen(starter(ROOT, *extra), cwd=ROOT, stdin=subprocess.DEVNULL)

    hello = None
    while hello is None and process.poll() is None and time.monotonic() - started < WAIT_FOR_PAGE_SEC:
        try:
            hello = json.loads(fetch('api/hello'))
        except (OSError, ValueError):
            time.sleep(2)
    took = time.monotonic() - started

    if hello is None:
        process.kill()
        return say(False, f'the page never answered (starter exit code {process.poll()}, after {took:.0f} s)')

    ok = say(hello.get('app') == 'wow-fish-yolo' and hello.get('demo') is True, f'the starter brought the page up in {took:.0f} s: {hello}')

    page = fetch('')
    token = re.search(r'name="fishbot-token" content="([^"]+)"', page)
    ok &= say(token is not None and 'Start fishing' in page, 'the page is served and has its Start button')

    again = subprocess.run(starter(ROOT, *extra), cwd=ROOT, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
    ok &= say(again.returncode == 0 and 'already running' in again.stdout, f'starting it a second time only points at the page: {again.stdout.strip()!r}')

    fetch('api/quit', data=b'{}', headers={'X-Fishbot-Token': token.group(1), 'Content-Type': 'application/json'})
    try:
        code = process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        code = None
    ok &= say(code == 0, f'Quit ends the starter cleanly (exit code {code})')
    return ok


def main():
    ok = cannot_start(False, ['needs Python 3.13', 'python.org'], 'with no Python it says which one to get')
    ok &= cannot_start(True, ['Setting up did not finish', 'It used Python 3.15', 'Python 3.13 is known to work'],
                       'with only a too-new Python it says so')
    ok &= starts_and_quits()
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
