"""Everything that differs between operating systems lives behind this package.

Each platform module provides:

    SYSTEM, LABEL        short name ('windows', 'macos', 'demo') and a display name
    SETUP_NOTES          things the user has to do once on this system
    find_game_window()   -> window object, or raises GameWindowNotFound
    key_is_down(name)    -> whether a hotkey (f1..f12) is currently held
    permission_problems() -> what the user still has to allow before the bot can work, as sentences
    create_controls()    -> object with press(key), moveTo(x, y, duration), click(button=...)
    create_grabber()     -> object with grab(region) returning BGR pixels

A window object has exists(), is_foreground(), focus() and capture_region(); the last returns
{'left', 'top', 'width', 'height'} in screen coordinates, or None when there is nothing to capture.
"""
import sys


class GameWindowNotFound(RuntimeError):
    pass


class UnsupportedSystem(RuntimeError):
    pass


def load(demo=False):
    if demo:
        from fishbot.platforms import demo as module
    elif sys.platform == 'win32':
        from fishbot.platforms import windows as module
    elif sys.platform == 'darwin':
        from fishbot.platforms import macos as module
    else:
        raise UnsupportedSystem('The bot runs on Windows and macOS. On other systems, try: python bot.py --demo')
    return module
