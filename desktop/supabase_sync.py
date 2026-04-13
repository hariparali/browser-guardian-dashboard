"""
Supabase remote sync for Browser Guardian.
- Pushes device timer state every 5 seconds (upsert into device_status).
- Polls for pending remote commands every 5 seconds and executes them.
"""
import socket
import threading
import logging
from datetime import datetime, timezone

import requests

log = logging.getLogger(__name__)

DEVICE_ID = socket.gethostname()


class SupabaseSync:

    def __init__(self, get_config, get_browser_state, get_roblox_state):
        """
        get_browser_state() → (state_str, remaining_secs)
        get_roblox_state()  → (state_str, remaining_secs)
        """
        self._get_config        = get_config
        self._get_browser_state = get_browser_state
        self._get_roblox_state  = get_roblox_state
        self._extend_browser_cb = None
        self._extend_roblox_cb  = None
        self._stop              = threading.Event()
        self._offline_count     = 0   # consecutive network failures

    def set_extend_callbacks(self, extend_browser, extend_roblox):
        """Set callbacks invoked when a remote extend command arrives."""
        self._extend_browser_cb = extend_browser
        self._extend_roblox_cb  = extend_roblox

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()
        log.info('[supabase_sync] started for device %s', DEVICE_ID)

    def stop(self):
        self._stop.set()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _cfg(self):
        return self._get_config()

    def _headers(self):
        key = self._cfg().get('supabase_key', '')
        return {
            'apikey': key,
            'Authorization': f'Bearer {key}',
            'Content-Type': 'application/json',
        }

    def _url(self, table):
        return self._cfg().get('supabase_url', '').rstrip('/') + f'/rest/v1/{table}'

    def _is_configured(self):
        cfg = self._cfg()
        return bool(cfg.get('supabase_url') and cfg.get('supabase_key'))

    # ── Push device status ────────────────────────────────────────────────────

    def _push_status(self):
        b_state, b_rem = self._get_browser_state()
        r_state, r_rem = self._get_roblox_state()
        payload = {
            'device_id':              DEVICE_ID,
            'device_name':            DEVICE_ID,
            'browser_state':          b_state,
            'browser_remaining_secs': b_rem,
            'roblox_state':           r_state,
            'roblox_remaining_secs':  r_rem,
            'last_updated':           datetime.now(timezone.utc).isoformat(),
        }
        hdrs = self._headers()
        hdrs['Prefer'] = 'resolution=merge-duplicates,return=minimal'
        resp = requests.post(self._url('device_status'), json=payload,
                             headers=hdrs, timeout=5)
        if resp.status_code not in (200, 201):
            log.warning('[supabase_sync] push_status HTTP %s', resp.status_code)

    # ── Poll and execute commands ─────────────────────────────────────────────

    def _poll_commands(self):
        hdrs = self._headers()
        resp = requests.get(
            self._url('remote_commands'),
            params={
                'device_id': f'eq.{DEVICE_ID}',
                'status':    'eq.pending',
                'order':     'created_at.asc',
                'limit':     '10',
            },
            headers=hdrs,
            timeout=5,
        )
        if resp.status_code != 200:
            return
        for cmd in resp.json():
            self._execute(cmd)

    def _execute(self, cmd):
        command = cmd.get('command', '')
        params  = cmd.get('params') or {}
        cmd_id  = cmd.get('id')
        try:
            minutes = int(params.get('minutes', 30))
            if command == 'extend_browser' and self._extend_browser_cb:
                self._extend_browser_cb(minutes * 60)
                log.info('[supabase_sync] extend_browser +%dm', minutes)
            elif command == 'extend_roblox' and self._extend_roblox_cb:
                self._extend_roblox_cb(minutes * 60)
                log.info('[supabase_sync] extend_roblox +%dm', minutes)
        except Exception as e:
            log.error('[supabase_sync] execute error: %s', e)
        finally:
            self._mark_done(cmd_id)

    def _mark_done(self, cmd_id):
        hdrs = self._headers()
        hdrs['Prefer'] = 'return=minimal'
        requests.patch(
            self._url('remote_commands'),
            json={'status': 'executed'},
            params={'id': f'eq.{cmd_id}'},
            headers=hdrs,
            timeout=5,
        )

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _loop(self):
        while not self._stop.wait(5):
            if not self._is_configured():
                continue
            failed = False
            try:
                self._push_status()
            except Exception as e:
                failed = True
                self._offline_count += 1
                # Log first failure and then every ~12th (~1 min) to avoid spam
                if self._offline_count == 1 or self._offline_count % 12 == 0:
                    log.warning('[supabase_sync] push: %s', e)
            try:
                self._poll_commands()
            except Exception as e:
                failed = True
                if self._offline_count == 1 or self._offline_count % 12 == 0:
                    log.warning('[supabase_sync] poll: %s', e)
            if not failed:
                self._offline_count = 0
