"""Windows: find the game window with Win32 and poll hotkeys without installing hooks."""
import ctypes

import psutil
import pywintypes
import win32api
import win32con
import win32gui
import win32process

from fishbot import keys
from fishbot.platforms import GameWindowNotFound

SYSTEM = 'windows'
LABEL = 'Windows'
SETUP_NOTES = [
    'Run the game in Windowed or Windowed (Fullscreen) mode.',
]

WINDOW_TITLE = 'World of Warcraft'
# Wow.exe, WowClassic.exe, Wow-64.exe, WowT.exe (PTR)...
PROCESS_NAME_PREFIX = 'wow'


def _use_physical_pixels():
    """Make window positions, screenshots and mouse moves all use real pixels on every monitor.

    Has to run before pyautogui is imported, which otherwise picks a coarser mode that is wrong
    on a second monitor with different scaling.
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass


_use_physical_pixels()


def _keep_console_from_freezing_the_bot():
    """Turn off QuickEdit in the classic console window.

    With QuickEdit on, a click in the console starts a text selection and blocks the next print,
    which would freeze the fishing loop in the middle of a cast until Enter is pressed.
    """
    quick_edit, extended_flags, standard_input = 0x0040, 0x0080, -10
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(standard_input)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, (mode.value & ~quick_edit) | extended_flags)
    except (AttributeError, OSError):
        pass


_keep_console_from_freezing_the_bot()


def _process_name(hwnd):
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    try:
        return psutil.Process(pid).name()
    except psutil.Error:
        return ''


def find_game_window():
    """Return the game client's window.

    The title alone is not enough: a browser tab or an Explorer folder can carry the same
    words, so the owning process has to be the game client as well.
    """
    titled = []

    def collect(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd) == WINDOW_TITLE:
            titled.append(hwnd)
        return True

    win32gui.EnumWindows(collect, None)
    clients = [hwnd for hwnd in titled if _process_name(hwnd).lower().startswith(PROCESS_NAME_PREFIX)]

    if not clients:
        hint = ''
        if titled:
            hint = f' ({len(titled)} window(s) are titled "{WINDOW_TITLE}" but do not belong to the game client.)'
        raise GameWindowNotFound(f'{WINDOW_TITLE} does not seem to be open. Start the game, then try again.' + hint)

    return GameWindow(clients[0])


class GameWindow:
    def __init__(self, hwnd):
        self.hwnd = hwnd

    def exists(self):
        return bool(win32gui.IsWindow(self.hwnd))

    def is_foreground(self):
        return win32gui.GetForegroundWindow() == self.hwnd and not win32gui.IsIconic(self.hwnd)

    def focus(self):
        """Ask Windows to bring the game to the front.

        Windows is allowed to refuse; callers check ``is_foreground`` rather than assume it worked.
        """
        _to_front(self.hwnd)

    def capture_region(self):
        """The game's drawing area (no title bar or borders), or None if there is nothing to capture."""
        try:
            if win32gui.IsIconic(self.hwnd):
                return None
            _, _, width, height = win32gui.GetClientRect(self.hwnd)
            left, top = win32gui.ClientToScreen(self.hwnd, (0, 0))
        except pywintypes.error:
            return None

        if width <= 0 or height <= 0:
            return None
        return {'left': left, 'top': top, 'width': width, 'height': height}


def _to_front(hwnd):
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    except pywintypes.error:
        pass
    try:
        refused = win32gui.GetForegroundWindow() != hwnd
    except pywintypes.error:
        return
    if refused:
        _to_front_from_the_background(hwnd)


def _to_front_from_the_background(hwnd):
    """Second attempt, for when the bot is not the program the user last touched.

    Start is pressed in the browser, so the browser holds the right to change the front
    window and Windows refuses the plain request. Holding ALT counts as fresh input from this
    program, which lifts the refusal. ALT is released again whatever happens.
    """
    try:
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
        try:
            win32gui.SetForegroundWindow(hwnd)
        finally:
            win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
    except pywintypes.error:
        pass


def front_window():
    """The window the person is using right now, so it can be handed back after the game was brought forward."""
    try:
        return win32gui.GetForegroundWindow() or None
    except pywintypes.error:
        return None


def bring_to_front(hwnd):
    """Bring back a window noted by ``front_window``. Windows may refuse, and nothing depends on it."""
    try:
        if hwnd and win32gui.IsWindow(hwnd):
            _to_front(hwnd)
    except pywintypes.error:
        pass


def key_is_down(name):
    return bool(win32api.GetAsyncKeyState(keys.WINDOWS_VK[name]) & 0x8000)


def permission_problems():
    return []


def create_controls():
    import pyautogui
    return pyautogui


def create_grabber():
    from fishbot.vision import ScreenGrabber
    return ScreenGrabber()
