"""Find the World of Warcraft window and report where its game area is on screen."""
import psutil
import pywintypes
import win32con
import win32gui
import win32process

WINDOW_TITLE = 'World of Warcraft'
# Wow.exe, WowClassic.exe, Wow-64.exe, WowT.exe (PTR)...
PROCESS_NAME_PREFIX = 'wow'


class GameWindowNotFound(RuntimeError):
    pass


def _process_name(hwnd):
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    try:
        return psutil.Process(pid).name()
    except psutil.Error:
        return ''


def find_game_window():
    """Return the game client's window.

    The title alone is not enough: a browser tab or an Explorer folder can carry the
    same words, so the owning process has to be the game client as well.
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
        raise GameWindowNotFound(f'No {WINDOW_TITLE} game window was found. Did you launch the game?' + hint)

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
        try:
            if win32gui.IsIconic(self.hwnd):
                win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(self.hwnd)
        except pywintypes.error:
            pass

    def capture_region(self):
        """Return the game's drawing area as an mss region, or None if there is nothing to capture.

        This is the client area, so the title bar and window borders are left out.
        """
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
