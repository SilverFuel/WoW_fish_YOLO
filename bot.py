"""World of Warcraft fishing bot.

    python bot.py --fishing-key f        fish from the console with these settings
    python bot.py --demo                 try it against a simulated game (sends no input)

Settings given here are saved, so the next run only needs: python bot.py
"""
import argparse
import sys

from fishbot import platforms
from fishbot.service import BotService
from fishbot.settings import SettingsStore, default_path


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--demo', action='store_true', help='run against a simulated game; nothing is sent to your computer')
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


def main(argv=None):
    args = parse_arguments(argv)

    try:
        platform = platforms.load(demo=args.demo)
    except platforms.UnsupportedSystem as error:
        print(error)
        return 1

    store = SettingsStore(args.settings or default_path(), platform.SYSTEM)
    _, errors = store.update(changes_from(args))
    if errors:
        for name, message in errors.items():
            print(f'{name}: {message}')
        return 2

    return run_console(BotService(platform, store))


if __name__ == '__main__':
    sys.exit(main())
