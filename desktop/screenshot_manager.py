"""
Silent screenshot capture for incognito/InPrivate browser sessions.
Saves compressed JPEGs to a screenshots/ folder next to the EXE.
Keeps the last 30 days only.
"""
import os
import sys
import socket
import logging
import threading
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)

if getattr(sys, 'frozen', False):
    _BASE = os.path.dirname(sys.executable)
else:
    _BASE = os.path.dirname(os.path.abspath(__file__))

_SCREENSHOTS_DIR = os.path.join(_BASE, 'screenshots')
_DEVICE = socket.gethostname()
_KEEP_DAYS = 30
_JPEG_QUALITY = 60
_RESIZE_FACTOR = 0.5


def _ensure_dir():
    os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)


def _cleanup_old():
    """Delete screenshot files older than _KEEP_DAYS days."""
    try:
        cutoff = datetime.now() - timedelta(days=_KEEP_DAYS)
        for fname in os.listdir(_SCREENSHOTS_DIR):
            if not fname.endswith('.jpg'):
                continue
            fpath = os.path.join(_SCREENSHOTS_DIR, fname)
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
                if mtime < cutoff:
                    os.remove(fpath)
            except Exception:
                pass
    except Exception as e:
        log.warning('[screenshot] cleanup error: %s', e)


def capture(label: str = '') -> str | None:
    """
    Take a screenshot, save it, return the filename (not full path).
    Returns None if PIL is unavailable or capture fails.
    label: short tag appended to filename (e.g. 'incognito')
    """
    try:
        from PIL import ImageGrab
    except ImportError:
        log.warning('[screenshot] Pillow not available — screenshot skipped')
        return None

    try:
        _ensure_dir()
        img = ImageGrab.grab()
        w, h = img.size
        img = img.resize((int(w * _RESIZE_FACTOR), int(h * _RESIZE_FACTOR)))
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%d_%H-%M-%S')
        tag = f'_{label}' if label else ''
        fname = f'{ts}_{_DEVICE}{tag}.jpg'
        fpath = os.path.join(_SCREENSHOTS_DIR, fname)
        img.save(fpath, 'JPEG', quality=_JPEG_QUALITY)
        log.info('[screenshot] saved: %s', fname)
        threading.Thread(target=_cleanup_old, daemon=True).start()
        return fname
    except Exception as e:
        log.error('[screenshot] capture failed: %s', e)
        return None
