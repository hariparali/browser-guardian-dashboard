import sqlite3
import shutil
import os
import tempfile
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

CHROME_HISTORY = os.path.expandvars(
    r'%LOCALAPPDATA%\Google\Chrome\User Data\Default\History'
)
EDGE_HISTORY = os.path.expandvars(
    r'%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\History'
)

# Chrome/Edge timestamps: microseconds since 1601-01-01 UTC
_CHROME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)


def _chrome_ts_to_str(chrome_time):
    try:
        dt = _CHROME_EPOCH + timedelta(microseconds=chrome_time)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _str_to_chrome_ts(dt_str):
    try:
        dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        return int((dt - _CHROME_EPOCH).total_seconds() * 1_000_000)
    except Exception:
        return 0


def _get_domain(url):
    try:
        return urlparse(url).netloc
    except Exception:
        return ''


def _read_history_file(db_path, since_chrome_ts=0):
    """Copy the locked SQLite file and read recent URLs from it."""
    if not os.path.exists(db_path):
        return []

    tmp = tempfile.mktemp(suffix='.db')
    try:
        shutil.copy2(db_path, tmp)
        conn = sqlite3.connect(tmp)
        c = conn.cursor()
        c.execute(
            'SELECT url, title, last_visit_time FROM urls '
            'WHERE last_visit_time > ? ORDER BY last_visit_time DESC LIMIT 500',
            (since_chrome_ts,)
        )
        rows = c.fetchall()
        conn.close()

        results = []
        for url, title, ts in rows:
            visited_at = _chrome_ts_to_str(ts)
            domain = _get_domain(url)
            results.append((url, title or '', domain, visited_at))
        return results
    except Exception as e:
        print(f'[history_reader] Error reading {db_path}: {e}')
        return []
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass


def get_new_history(since_dt_str=None):
    """
    Return new browser history from Chrome and Edge combined.
    since_dt_str: '2024-01-01 12:00:00' string or None for last 100 entries.
    """
    since_ts = _str_to_chrome_ts(since_dt_str) if since_dt_str else 0
    seen = set()
    results = []

    for path in (CHROME_HISTORY, EDGE_HISTORY):
        for entry in _read_history_file(path, since_ts):
            key = (entry[0], entry[3])  # url + visited_at
            if key not in seen:
                seen.add(key)
                results.append(entry)

    return results
