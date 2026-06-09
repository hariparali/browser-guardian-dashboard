"""
Reads the currently active URL from Chrome and Edge address bars
using the Windows UI Automation API.
Polls every N seconds and calls a callback with new URLs.
Captures incognito and normal browsing alike.
"""
import time
import logging
import threading
from datetime import datetime, timezone
from urllib.parse import urlparse

log = logging.getLogger(__name__)

try:
    import uiautomation as auto
    _AUTO_AVAILABLE = True
except ImportError:
    _AUTO_AVAILABLE = False
    log.warning('[url_watcher] uiautomation not installed — address bar monitoring disabled')

# Chrome and Edge share the same window class
_BROWSER_CLASS = 'Chrome_WidgetWin_1'
_ADDRESS_BAR_NAMES = (
    'Address and search bar',   # Chrome (normal + incognito)
    'Address bar',              # Edge (normal + InPrivate)
)
# Title substrings that identify private/incognito windows
_INCOGNITO_MARKERS = ('incognito', 'inprivate', 'private')


def _get_domain(url: str) -> str:
    try:
        return urlparse(url).netloc
    except Exception:
        return ''


def _looks_like_url(text: str) -> bool:
    return text.startswith('http://') or text.startswith('https://') or (
        '.' in text and ' ' not in text and not text.startswith('Search') and len(text) > 3
    )


def _normalise_url(text: str) -> str:
    """Add https:// if Chrome omitted it (modern Chrome hides the scheme)."""
    if text.startswith('http://') or text.startswith('https://'):
        return text
    return 'https://' + text


def _read_active_url() -> tuple[str, bool] | tuple[None, bool]:
    """
    Walk all top-level Chrome/Edge windows.
    Returns (url, is_incognito) for the first URL found, or (None, False).
    """
    if not _AUTO_AVAILABLE:
        return None, False
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
                        title_lower = win.Name.lower() if win.Name else ''
                        is_incognito = any(m in title_lower for m in _INCOGNITO_MARKERS)
                        return _normalise_url(val), is_incognito
                except Exception:
                    continue
    except Exception as e:
        # -2147220991 = COM "event unable to invoke subscribers" — transient, ignore silently
        if '-2147220991' not in str(e):
            log.debug('[url_watcher] read error: %s', e)
    return None, False


class UrlWatcher:
    """
    Polls the browser address bar every `interval` seconds.
    Calls `on_new_url(url, domain, visited_at, is_incognito)` when a new URL is detected.
    """

    def __init__(self, on_new_url, interval=1.5):
        self._on_new_url = on_new_url
        self._interval = interval
        self._last_url = None
        self._running = False

    def start(self):
        if not _AUTO_AVAILABLE:
            log.warning('[url_watcher] not starting — uiautomation unavailable')
            return
        self._running = True
        log.info('[url_watcher] started (interval=%.1fs)', self._interval)
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
                url, is_incognito = _read_active_url()
                if url and url != self._last_url:
                    self._last_url = url
                    domain = _get_domain(url)
                    visited_at = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
                    mode = 'incognito' if is_incognito else 'normal'
                    log.info('[url_watcher] captured (%s): %s', mode, domain)
                    self._on_new_url(url, domain, visited_at, is_incognito)
            except Exception as e:
                log.error('[url_watcher] loop error: %s', e)
            time.sleep(self._interval)
