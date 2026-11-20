"""Key names the bot can press, and the function keys it can watch as hotkeys.

Names follow pyautogui. Only keys that pyautogui can press on the given system are offered,
because pyautogui silently ignores a name it does not know.
"""
import string

HOTKEYS = [f'f{number}' for number in range(1, 13)]

_COMMON = (list(string.ascii_lowercase) + list(string.digits) + HOTKEYS
           + ['space', 'tab'] + list("-=[]\\;',./`"))
_WINDOWS_ONLY = [f'num{number}' for number in range(10)]

# Virtual key codes for polling the hotkeys.
WINDOWS_VK = {f'f{number}': 0x6F + number for number in range(1, 13)}
MAC_KEYCODES = {'f1': 0x7A, 'f2': 0x78, 'f3': 0x63, 'f4': 0x76, 'f5': 0x60, 'f6': 0x61,
                'f7': 0x62, 'f8': 0x64, 'f9': 0x65, 'f10': 0x6D, 'f11': 0x67, 'f12': 0x6F}


def pressable_keys(system):
    """Key names that can be bound to fishing or the lure on ``system`` ('windows', 'macos', ...)."""
    return _COMMON + _WINDOWS_ONLY if system == 'windows' else list(_COMMON)
