"""WoW Fish YOLO: a fishing bot for World of Warcraft.

    python bot.py              open the page in your browser (this is the normal way)
    python bot.py --demo       the same, with a pretend game: nothing is pressed or clicked
    python bot.py --console    no page: start fishing now with your saved settings, CTRL+C stops

Starting it a second time just opens the page of the copy that is already running.
"""
import argparse
import json
import socket
import sys
import urllib.request
import webbrowser

from fishbot import platforms
from fishbot.service import BotService
from fishbot.settings import SettingsStore, default_path


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--demo', action='store_true', help='use a pretend game; nothing is pressed or clicked')
    parser.add_argument('--console', action='store_true', help='no page: start fishing now, stop with CTRL+C')
    parser.add_argument('--practice', action='store_true', help='with --console: only watch, never press or click')
    parser.add_argument('--port', type=int, default=None, help='port for the page (default 8765)')
    parser.add_argument('--no-browser', action='store_true', help='do not open the browser; print the address instead')
    parser.add_argument('--settings', help='settings file to use (default: your user profile)')
    parser.add_argument('--fishing-key', help='the key you cast with, e.g. f')
    parser.add_argument('--lure-key', help='the key your lure is on; switches the lure on')
    parser.add_argument('--lure-minutes', type=int, help='how long a lure lasts')
    return parser.parse_args(argv)


def changes_from(args):
    changes = {}
    if args.fishing_key is not None:
        changes['fishing_key'] = args.fishing_key
    if args.lure_key is not None:
        changes.update(lure_key=args.lure_key, lure_enabled=True)
    if args.lure_minutes is not None:
        changes['lure_minutes'] = args.lure_minutes
    return changes


def already_running(port, demo):
    """The address of a copy that is already running in the same mode, or None.

    A copy that found its usual port taken sits on one of the next few, so those are asked as well,
    up to the first port that nothing is listening on.
    """
    from fishbot.server import APP_NAME, PORT_ATTEMPTS

    directly = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # this computer, never a proxy
    for candidate in range(port, port + PORT_ATTEMPTS):
        try:
            socket.create_connection(('127.0.0.1', candidate), timeout=1.5).close()
        except OSError:
            return None  # nothing listens here, so a running copy would have taken this port

        address = f'http://127.0.0.1:{candidate}/'
        try:
            with directly.open(address + 'api/hello', timeout=1.5) as response:
                hello = json.loads(response.read().decode('utf-8'))
        except (OSError, ValueError):
            continue  # some other program has this port
        if isinstance(hello, dict) and hello.get('app') == APP_NAME and hello.get('demo') == demo:
            return address
    return None


def run_console(service, practice):
    problems = service.start(practice=practice)
    if problems:
        for problem in problems:
            print(problem)
        return 1

    try:
        while service.running:
            service.wait(0.2)
    except KeyboardInterrupt:
        service.stop('Stopped with CTRL+C.')
        service.wait(5)
    return 0


def run_page(service, port, open_browser):
    from fishbot.server import AppServer

    try:
        server = AppServer(service, port)
    except OSError as error:
        print(f'The page could not start: {error}')
        return 1

    print('WoW Fish YOLO is running.')
    print(f'The page: {server.url}')
    print('Keep this window open while you fish. To quit, press Quit on the page or close this window.')
    if open_browser:
        webbrowser.open(server.url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.shutdown()
        server.httpd.server_close()
    return 0


def main(argv=None):
    from fishbot.server import DEFAULT_PORT

    args = parse_arguments(argv)
    port = DEFAULT_PORT if args.port is None else args.port

    if not args.console and port:
        running = already_running(port, args.demo)
        if running:
            print('WoW Fish YOLO is already running. Opening its page.')
            if args.no_browser:
                print(f'The page: {running}')
            else:
                webbrowser.open(running)
            return 0

    try:
        platform = platforms.load(demo=args.demo)
    except platforms.UnsupportedSystem as error:
        print(error)
        return 1

    store = SettingsStore(args.settings or default_path(), platform.SYSTEM)
    try:
        _, errors = store.update(changes_from(args))
    except OSError as error:
        print(f'Your settings could not be saved to {store.path} ({error.strerror or error}). They apply to this run only.')
        errors = {}
    if errors:
        for name, message in errors.items():
            print(f'{name}: {message}')
        return 2

    service = BotService(platform, store)
    if args.console:
        return run_console(service, args.practice)
    return run_page(service, port, not args.no_browser)


if __name__ == '__main__':
    sys.exit(main())
