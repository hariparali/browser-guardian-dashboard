"""
Reads the currently active URL from Chrome and Edge address bars
using the Windows UI Automation API.
Polls every N seconds and calls a callback with new URLs.
Captures incognito and normal browsing alike.
"""
import time
import threading
from datetime import datetime
from urllib.parse import urlparse

try:
    import uiautomation as auto
    _AUTO_AVAILABLE = True
except ImportError:
    _AUTO_AVAILABLE = False
    print('[url_watcher] uiautomation not installed — address bar monitoring disabled')

# Chrome and Edge share the same window class
_BROWSER_CLASS = 'Chrome_WidgetWin_1'
_ADDRESS_BAR_NAMES = (
    'Address and search bar',   # Chrome
    'Address bar',              # Edge
)


def _get_domain(url: str) -> str:
    try:
        return urlparse(url).netloc
    except Exception:
        return ''


def _looks_like_url(text: str) -> bool:
    return text.startswith('http://') or text.startswith('https://')


def _read_active_url() -> str | None:
    """
    Walk all top-level Chrome/Edge windows and return the URL
    from the focused/first address bar found.
    """
    if not _AUTO_AVAILABLE:
        return None
    try:
        desktop = auto.GetRootControl()
        for win in desktop.GetChildren():
            if win.ClassName != _BROWSER_CLASS:
                continue
            for bar_name in _ADDRESS_BAR_NAMES:
                try:
                    edit = win.EditControl(Name=bar_name)
                    if not edit.Exists(0):
                        continue
                    val = edit.GetValuePattern().Value.strip()
                    if _looks_like_url(val):
                        return val
                except Exception:
                    continue
    except Exception as e:
        # -2147220991 = COM "event unable to invoke subscribers" — transient, ignore silently
        if '-2147220991' not in str(e):
            print(f'[url_watcher] read error: {e}')
    return None


class UrlWatcher:
    """
    Polls the browser address bar every `interval` seconds.
    Calls `on_new_url(url, domain, visited_at)` when a new URL is detected.
    """

    def __init__(self, on_new_url, interval=5):
        self._on_new_url = on_new_url
        self._interval = interval
        self._last_url = None
        self._running = False

    def start(self):
        if not _AUTO_AVAILABLE:
            return
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False

    def _loop(self):
        # CoInitialize must be called on the thread that uses UI Automation
        try:
            import ctypes
            ctypes.windll.ole32.CoInitialize(None)
        except Exception:
            pass
        while self._running:
            try:
                url = _read_active_url()
                if url and url != self._last_url:
                    self._last_url = url
                    domain = _get_domain(url)
                    visited_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    self._on_new_url(url, domain, visited_at)
            except Exception as e:
                print(f'[url_watcher] loop error: {e}')
            time.sleep(self._interval)
