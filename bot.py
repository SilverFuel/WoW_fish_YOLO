"""World of Warcraft fishing bot.

    python bot.py                 open the control page in your browser
    python bot.py --demo          the same, against a simulated game (sends no input)
    python bot.py --console       fish straight away from this window, using the saved settings

Settings changed on the page or given here are saved for next time.
"""
import argparse
import sys
import webbrowser

from fishbot import platforms
from fishbot.service import BotService
from fishbot.settings import SettingsStore, default_path


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--demo', action='store_true', help='use a simulated game; nothing is sent to your computer')
    parser.add_argument('--console', action='store_true', help='no page: start fishing now, stop with CTRL+C')
    parser.add_argument('--port', type=int, default=None, help='port for the control page (default 8765)')
    parser.add_argument('--no-browser', action='store_true', help='do not open the browser; print the address instead')
    parser.add_argument('--settings', help='settings file to use (default: your user profile)')
    parser.add_argument('--fishing-key', help='key your fishing spell is bound to, e.g. f')
    parser.add_argument('--lure-key', help='key your lure is bound to; turns the lure on')
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


def run_console(service):
    problems = service.start()
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
    from fishbot.server import DEFAULT_PORT, AppServer

    try:
        server = AppServer(service, DEFAULT_PORT if port is None else port)
    except OSError as error:
        print(f'The control page could not start: {error}')
        return 1

    print(f'Control page: {server.url}')
    print('Leave this window open while you fish. Close it, or press CTRL+C here, to quit.')
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
    args = parse_arguments(argv)

    try:
        platform = platforms.load(demo=args.demo)
    except platforms.UnsupportedSystem as error:
        print(error)
        return 1

    store = SettingsStore(args.settings or default_path(), platform.SYSTEM)
    try:
        _, errors = store.update(changes_from(args))
    except OSError as error:
        print(f'The settings could not be saved to {store.path} ({error.strerror or error}). They apply to this run only.')
        errors = {}
    if errors:
        for name, message in errors.items():
            print(f'{name}: {message}')
        return 2

    service = BotService(platform, store)
    if args.console:
        return run_console(service)
    return run_page(service, args.port, not args.no_browser)


if __name__ == '__main__':
    sys.exit(main())
