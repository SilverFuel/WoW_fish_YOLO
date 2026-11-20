"""macOS: find the game window with Quartz and poll hotkeys from the keyboard state.

Positions here are in points, which is what both the mouse and the screen capture use, so a
Retina display needs no special handling.
"""
import contextlib

from fishbot import keys
from fishbot.platforms import GameWindowNotFound

SYSTEM = 'macos'
LABEL = 'macOS'
SETUP_NOTES = [
    'Allow your terminal (or Python) under System Settings > Privacy & Security > Screen Recording, '
    'so the bot can see the game. Without it the preview is black.',
    'Allow it under Privacy & Security > Accessibility as well, so it can press keys and click.',
    'If F8/F9 do nothing, allow it under Input Monitoring, or use the buttons on this page. '
    'On a Mac keyboard the function keys may need the fn key.',
]

# The app is "World of Warcraft" or "World of Warcraft Classic".
OWNER_NAME_PREFIX = 'World of Warcraft'
MIN_WINDOW_SIDE = 200  # ignore tooltips, menus and other small helper windows


def _is_normal_window(window):
    bounds = window.get('kCGWindowBounds') or {}
    return (window.get('kCGWindowLayer') == 0
            and bounds.get('Width', 0) >= MIN_WINDOW_SIDE and bounds.get('Height', 0) >= MIN_WINDOW_SIDE)


def pick_game_window(windows):
    """Choose the game's main window from a window list: the largest normal window the game owns."""
    owned = [window for window in windows
             if str(window.get('kCGWindowOwnerName', '')).startswith(OWNER_NAME_PREFIX) and _is_normal_window(window)]
    if not owned:
        return None
    return max(owned, key=lambda window: window['kCGWindowBounds']['Width'] * window['kCGWindowBounds']['Height'])


def frontmost_pid(onscreen_windows):
    """The process that owns the frontmost normal window. The list is ordered front to back."""
    for window in onscreen_windows:
        if _is_normal_window(window):
            return window.get('kCGWindowOwnerPID')
    return None


def region_of(window):
    bounds = window['kCGWindowBounds']
    return {'left': int(bounds['X']), 'top': int(bounds['Y']),
            'width': int(bounds['Width']), 'height': int(bounds['Height'])}


def _pool():
    """Free the temporary objects macOS hands out, which a background thread never does by itself.

    The fishing loop calls into macOS many times a second from its own thread; without this the
    memory would only be returned when the session ends.
    """
    try:
        import objc
        return objc.autorelease_pool()
    except (ImportError, AttributeError):
        return contextlib.nullcontext()


def _window_list(onscreen_only):
    import Quartz

    options = Quartz.kCGWindowListExcludeDesktopElements
    options |= Quartz.kCGWindowListOptionOnScreenOnly if onscreen_only else Quartz.kCGWindowListOptionAll
    with _pool():
        windows = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or []
        # Copy into plain Python data so the helpers above need no macOS objects.
        return [{str(key): (dict(value) if key == 'kCGWindowBounds' else value if isinstance(value, (int, float)) else str(value))
                 for key, value in window.items()} for window in windows]


def focused_pid():
    """The process that has keyboard focus, or None if macOS will not say (Accessibility not allowed)."""
    from ApplicationServices import (AXUIElementCopyAttributeValue, AXUIElementCreateSystemWide, AXUIElementGetPid,
                                     kAXFocusedApplicationAttribute)

    with _pool():
        error, application = AXUIElementCopyAttributeValue(AXUIElementCreateSystemWide(), kAXFocusedApplicationAttribute, None)
        if error or application is None:
            return None
        error, pid = AXUIElementGetPid(application, None)
        return None if error else int(pid)


def find_game_window():
    # Search every Space, not just the visible one: a full-screen game sits on its own Space.
    window = pick_game_window(_window_list(onscreen_only=False))
    if window is None:
        raise GameWindowNotFound(f'No {OWNER_NAME_PREFIX} game window was found. Is the game running?')
    return GameWindow(window['kCGWindowOwnerPID'], window['kCGWindowNumber'])


class GameWindow:
    def __init__(self, pid, window_number):
        self.pid = pid
        self.window_number = window_number

    def _application(self):
        from AppKit import NSRunningApplication
        return NSRunningApplication.runningApplicationWithProcessIdentifier_(self.pid)

    def exists(self):
        with _pool():
            application = self._application()
            return application is not None and not application.isTerminated()

    def is_foreground(self):
        return frontmost_pid(_window_list(onscreen_only=True)) == self.pid

    def focus(self):
        from AppKit import NSApplicationActivateIgnoringOtherApps

        with _pool():
            application = self._application()
            if application is not None:
                application.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)

    def capture_region(self):
        """The game window's rectangle, or None while it is minimised or on another Space.

        In windowed mode this includes the title bar; the game area is everything below it.
        """
        for window in _window_list(onscreen_only=True):
            if window.get('kCGWindowNumber') == self.window_number:
                region = region_of(window)
                return region if region['width'] > 0 and region['height'] > 0 else None
        return None


def key_is_down(name):
    import Quartz
    return bool(Quartz.CGEventSourceKeyState(Quartz.kCGEventSourceStateHIDSystemState, keys.MAC_KEYCODES[name]))


def screen_recording_allowed():
    import Quartz
    preflight = getattr(Quartz, 'CGPreflightScreenCaptureAccess', None)  # macOS 10.15 and newer
    return True if preflight is None else bool(preflight())


def accessibility_allowed():
    from ApplicationServices import AXIsProcessTrusted
    return bool(AXIsProcessTrusted())


def permission_problems():
    """What still has to be allowed in System Settings. Asking makes macOS show its own prompt too."""
    import Quartz
    from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt

    where = 'System Settings > Privacy & Security'
    problems = []
    with _pool():
        if not screen_recording_allowed():
            request = getattr(Quartz, 'CGRequestScreenCaptureAccess', None)
            if request is not None:
                request()
            problems.append(f'macOS is not letting the bot see the screen. Allow the app you started it from '
                            f'(Terminal, for example) under {where} > Screen Recording, then start the bot again.')
        if not accessibility_allowed():
            AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
            problems.append(f'macOS is not letting the bot press keys or click. Allow the app you started it from '
                            f'under {where} > Accessibility.')
    return problems


def create_controls():
    import pyautogui
    return pyautogui


def create_grabber():
    from fishbot.vision import ScreenGrabber
    return ScreenGrabber()
