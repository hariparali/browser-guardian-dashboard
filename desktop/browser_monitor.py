import psutil

_BROWSER_NAMES = {'chrome.exe', 'msedge.exe'}


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
