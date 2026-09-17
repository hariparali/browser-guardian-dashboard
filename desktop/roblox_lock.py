"""
Roblox launch-block via Image File Execution Options (IFEO).

Setting a "Debugger" value under
    HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Image File Execution Options\\<exe>
makes Windows launch that debugger command INSTEAD of the exe — so Roblox never
starts (the anti-cheat never even loads). We point the debugger at our own frozen
exe in `--blocked-launch` mode, which shows a short "locked" popup and exits.

Requires elevation (HKLM writes). All functions degrade gracefully and log when
elevation is missing, so the app still runs (falling back to kill-on-sight).
"""
import ctypes
import logging
import os
import sys
import winreg

log = logging.getLogger(__name__)

_IFEO = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options'


def is_elevated():
    """True if this process is running with administrator rights."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _debugger_cmd():
    """Command Windows runs in place of a blocked Roblox exe."""
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}" --blocked-launch'
    # Dev/source mode: no frozen exe to show a popup — use a harmless no-op so
    # the launch is still blocked (systray.exe just exits without a window).
    win = os.environ.get('SystemRoot', r'C:\Windows')
    return f'"{win}\\System32\\systray.exe"'


def engage_lock(names):
    """Block each exe `name` from launching. Returns True if any block was set.

    `names` is an iterable of process/exe names (e.g. 'robloxplayerbeta.exe').
    Needs admin; returns False (and logs) if not elevated.
    """
    dbg = _debugger_cmd()
    targets = sorted({(n or '').lower() for n in names if n})
    ok = 0
    for name in targets:
        try:
            key = winreg.CreateKeyEx(
                winreg.HKEY_LOCAL_MACHINE, _IFEO + '\\' + name, 0,
                winreg.KEY_SET_VALUE,
            )
            winreg.SetValueEx(key, 'Debugger', 0, winreg.REG_SZ, dbg)
            winreg.CloseKey(key)
            ok += 1
        except PermissionError:
            log.warning('[roblox_lock] IFEO launch-block needs elevation (HKLM) — '
                        'falling back to kill-on-sight')
            return False
        except Exception as e:
            log.warning('[roblox_lock] engage %s failed: %s', name, e)
    if ok:
        log.info('[roblox_lock] IFEO launch-block ENGAGED for %d name(s): %s', ok, targets)
    return ok > 0


def release_lock(names=None):
    """Remove the IFEO Debugger blocks so Roblox can launch again.

    If `names` is None, clears every known Roblox exe name. Safe to call when
    nothing is locked. Returns False (and logs) if not elevated.
    """
    from browser_monitor import _ROBLOX_NAMES
    targets = sorted({(n or '').lower() for n in (names or _ROBLOX_NAMES) if n})
    released = 0
    for name in targets:
        path = _IFEO + '\\' + name
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0,
                                 winreg.KEY_SET_VALUE | winreg.KEY_READ)
            try:
                winreg.DeleteValue(key, 'Debugger')
                released += 1
            except FileNotFoundError:
                pass
            winreg.CloseKey(key)
            # Remove the now-empty subkey (ignore if it still has other values).
            try:
                winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, path)
            except OSError:
                pass
        except FileNotFoundError:
            pass  # Not locked — nothing to do
        except PermissionError:
            log.warning('[roblox_lock] release needs elevation (HKLM) — skipped %s', name)
            return False
        except Exception as e:
            log.warning('[roblox_lock] release %s failed: %s', name, e)
    if released:
        log.info('[roblox_lock] IFEO launch-block RELEASED (%d name(s))', released)
    return True


def is_locked():
    """True if any known Roblox exe currently has an IFEO Debugger block set."""
    from browser_monitor import _ROBLOX_NAMES
    for name in _ROBLOX_NAMES:
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 _IFEO + '\\' + name.lower(), 0, winreg.KEY_READ)
            try:
                winreg.QueryValueEx(key, 'Debugger')
                return True
            finally:
                winreg.CloseKey(key)
        except FileNotFoundError:
            continue
        except Exception:
            continue
    return False
