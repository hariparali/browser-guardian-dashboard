import ctypes
import logging
import subprocess
from ctypes import wintypes

import psutil

log = logging.getLogger(__name__)

_BROWSER_NAMES = {'chrome.exe', 'msedge.exe', 'copilot.exe'}
# Exact names still used for taskkill /F fallback. Detection is broader (below).
_ROBLOX_NAMES  = {'robloxplayerbeta.exe', 'robloxplayer.exe', 'robloxplayerlauncher.exe',
                  'roblox.exe', 'robloxstudiobeta.exe'}
# Roblox ships client updates that occasionally rename the player exe, which
# used to silently break exact-name detection. Match instead on the substring
# "roblox" in the process NAME or its EXECUTABLE PATH — Roblox always lives
# under a ...\Roblox\... (or WindowsApps\ROBLOXCORPORATION.ROBLOX...) path, so
# this catches every variant, including Microsoft Store / renamed builds.
_ROBLOX_MATCH = 'roblox'

_CREATE_NO_WINDOW = 0x08000000


def get_browser_procs():
    procs = []
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if proc.info['name'] and proc.info['name'].lower() in _BROWSER_NAMES:
                procs.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return procs


def is_browser_running():
    return bool(get_browser_procs())


def kill_browsers():
    """Terminate all Chrome and Edge processes. Returns count killed."""
    killed = 0
    for proc in get_browser_procs():
        try:
            proc.terminate()
            killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return killed


def get_roblox_procs():
    procs = []
    for proc in psutil.process_iter(['pid', 'name', 'exe']):
        try:
            info = proc.info
            name = (info.get('name') or '').lower()
            exe  = (info.get('exe') or '').lower()
            if _ROBLOX_MATCH in name or _ROBLOX_MATCH in exe:
                procs.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return procs


def roblox_proc_names(procs):
    """Best-effort set of process names for logging (never raises)."""
    names = set()
    for p in procs:
        try:
            names.add(p.info.get('name') or '?')
        except Exception:
            names.add('?')
    return sorted(names)


def is_roblox_running():
    return bool(get_roblox_procs())


def _post_wm_close_to_pids(pids):
    """Send WM_CLOSE to every visible top-level window owned by `pids`.

    This mimics the user clicking the window's X. Roblox's Byfron/Hyperion
    anti-cheat permits this even from a non-elevated process, unlike
    TerminateProcess — so it's our most reliable close path without elevation.
    Returns the number of windows messaged.
    """
    WM_CLOSE = 0x0010
    user32 = ctypes.windll.user32
    closed = 0

    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _cb(hwnd, _lparam):
        nonlocal closed
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and user32.IsWindowVisible(hwnd):
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            closed += 1
        return True

    user32.EnumWindows(EnumWindowsProc(_cb), 0)
    return closed


def kill_roblox():
    """Force Roblox to close. Returns the number of processes that ended.

    Modern Roblox ships the Byfron/Hyperion anti-cheat, which blocks
    TerminateProcess from a non-elevated caller (proc.terminate()/kill() raise
    AccessDenied). We therefore try, in order, logging each step so remote logs
    show what actually happened:
      1. graceful WM_CLOSE to Roblox windows (allowed even when non-elevated),
      2. proc.kill() / terminate(),
      3. taskkill /F as a last resort.
    """
    procs = get_roblox_procs()
    if not procs:
        return 0

    pids = {p.pid for p in procs}
    log.info('[kill_roblox] found %d roblox process(es): %s names=%s',
             len(procs), sorted(pids), roblox_proc_names(procs))

    # 1. Graceful window close — works around Byfron without elevation.
    try:
        closed = _post_wm_close_to_pids(pids)
        if closed:
            log.info('[kill_roblox] sent WM_CLOSE to %d window(s)', closed)
    except Exception as e:
        log.warning('[kill_roblox] WM_CLOSE failed: %s', e)

    gone, alive = psutil.wait_procs(procs, timeout=3)
    if not alive:
        log.info('[kill_roblox] all roblox processes closed via WM_CLOSE')
        return len(gone)

    # 2. terminate / kill (TerminateProcess).
    for proc in alive:
        try:
            proc.kill()
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied as e:
            log.warning('[kill_roblox] AccessDenied killing pid %s (Byfron?) — %s', proc.pid, e)

    gone2, alive2 = psutil.wait_procs(alive, timeout=3)
    if not alive2:
        log.info('[kill_roblox] roblox closed via terminate/kill')
        return len(procs)

    # 3. taskkill /F fallback.
    log.warning('[kill_roblox] %d process(es) still alive: %s — trying taskkill /F',
                len(alive2), sorted(p.pid for p in alive2))
    for name in _ROBLOX_NAMES:
        try:
            subprocess.run(['taskkill', '/F', '/T', '/IM', name],
                           capture_output=True, creationflags=_CREATE_NO_WINDOW)
        except Exception as e:
            log.warning('[kill_roblox] taskkill %s failed: %s', name, e)

    gone3, alive3 = psutil.wait_procs(alive2, timeout=3)
    if alive3:
        log.error('[kill_roblox] FAILED to kill %d roblox process(es): %s — '
                  'likely needs elevation (Byfron anti-cheat)',
                  len(alive3), sorted(p.pid for p in alive3))
    return len(procs) - len(alive3)


def force_kill_roblox():
    """Abruptly terminate Roblox — NO graceful WM_CLOSE, so Roblox never shows
    its in-game "are you sure you want to leave?" confirmation.

    Hard-kills first (proc.kill() + taskkill /F). This defeats Byfron only when
    the caller is ELEVATED; if not elevated the hard kill is blocked, so we fall
    back to WM_CLOSE (which may pop the in-game dialog) as a last resort rather
    than leaving Roblox running. Returns (killed_count, names).
    """
    procs = get_roblox_procs()
    names = roblox_proc_names(procs)
    if not procs:
        return 0, names

    log.info('[force_kill_roblox] killing %d roblox proc(es) names=%s pids=%s',
             len(procs), names, sorted(p.pid for p in procs))

    # 1. Hard kill — TerminateProcess. Instant, no confirmation dialog.
    for proc in procs:
        try:
            proc.kill()
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied:
            pass  # Byfron blocks non-elevated kill; handled by fallback below
    for name in {(n or '').lower() for n in names if n} | _ROBLOX_NAMES:
        try:
            subprocess.run(['taskkill', '/F', '/T', '/IM', name],
                           capture_output=True, creationflags=_CREATE_NO_WINDOW)
        except Exception:
            pass

    gone, alive = psutil.wait_procs(procs, timeout=3)
    if not alive:
        log.info('[force_kill_roblox] roblox force-killed (no dialog)')
        return len(gone), names

    # 2. Not elevated — hard kill blocked by Byfron. Fall back to WM_CLOSE so we
    #    at least close it (this is the path that can show the in-game dialog).
    log.warning('[force_kill_roblox] %d proc(es) survived hard kill (Byfron/non-elevated) '
                '— WM_CLOSE fallback', len(alive))
    try:
        _post_wm_close_to_pids({p.pid for p in alive})
    except Exception as e:
        log.warning('[force_kill_roblox] WM_CLOSE fallback failed: %s', e)

    gone2, alive2 = psutil.wait_procs(alive, timeout=3)
    if alive2:
        log.error('[force_kill_roblox] FAILED to kill %s — needs elevation',
                  sorted(p.pid for p in alive2))
    return len(procs) - len(alive2), names
