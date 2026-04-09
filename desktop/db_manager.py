import sqlite3
import os
import sys

if getattr(sys, 'frozen', False):
    _BASE = os.path.dirname(sys.executable)
else:
    _BASE = os.path.dirname(os.path.abspath(__file__))

DB_FILE = os.path.join(_BASE, 'browsing_history.db')


def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS browsing_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            title TEXT,
            domain TEXT,
            visited_at TEXT NOT NULL,
            is_flagged INTEGER DEFAULT 0,
            category TEXT DEFAULT 'unclassified',
            reason TEXT DEFAULT '',
            severity TEXT DEFAULT 'low',
            is_synced INTEGER DEFAULT 0,
            UNIQUE(url, visited_at)
        )
    ''')
    conn.commit()
    conn.close()


def insert_urls(urls):
    """
    Insert classified history entries, ignore duplicates.
    Each entry: (url, title, domain, visited_at, is_flagged, category, reason, severity)
    """
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.executemany(
        '''INSERT OR IGNORE INTO browsing_history
           (url, title, domain, visited_at, is_flagged, category, reason, severity)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        urls
    )
    conn.commit()
    conn.close()


def get_unsynced(limit=200):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        '''SELECT id, url, title, domain, visited_at, is_flagged, category, reason, severity
           FROM browsing_history WHERE is_synced=0 LIMIT ?''',
        (limit,)
    )
    rows = c.fetchall()
    conn.close()
    return rows


def mark_synced(ids):
    if not ids:
        return
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.executemany('UPDATE browsing_history SET is_synced=1 WHERE id=?', [(i,) for i in ids])
    conn.commit()
    conn.close()
