"""
Supabase remote sync for Browser Guardian.
- Pushes device timer state every 5 seconds (upsert into device_status).
- Polls for pending remote commands every 5 seconds and executes them.
"""
import socket
import threading
import logging
from datetime import datetime, timezone, timedelta

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
        self._block_browser_cb  = None
        self._block_roblox_cb   = None
        self._show_message_cb   = None
        self._extend_app_cb     = None
        self._block_app_cb      = None
        self._close_app_cb      = None
        self._unblock_app_cb    = None
        self._unblock_all_cb    = None
        self._tracker           = None   # UsageTracker, set via set_app_tracker
        self._app_tick          = 0      # counts 5s loops, for the ~60s app cycle
        self._stop              = threading.Event()
        self._offline_count     = 0   # consecutive network failures

    def set_extend_callbacks(self, extend_browser, extend_roblox):
        """Set callbacks invoked when a remote extend command arrives."""
        self._extend_browser_cb = extend_browser
        self._extend_roblox_cb  = extend_roblox

    def set_action_callbacks(self, block_browser, block_roblox, show_message):
        """Set callbacks for block and message commands."""
        self._block_browser_cb = block_browser
        self._block_roblox_cb  = block_roblox
        self._show_message_cb  = show_message

    def set_app_callbacks(self, extend_app=None, block_app=None,
                          close_app=None, unblock_app=None, unblock_all=None):
        """Per-app remote commands from the dashboard.
        extend_app(exe_name, secs) → grant more time today
        block_app(exe_name)        → close it AND stop it relaunching
        close_app(exe_name)        → close it only, no launch-block
        unblock_app(exe_name)      → lift one launch-block
        unblock_all()              → lift every launch-block on this device
        """
        self._extend_app_cb  = extend_app
        self._block_app_cb   = block_app
        self._close_app_cb   = close_app
        self._unblock_app_cb = unblock_app
        self._unblock_all_cb = unblock_all

    def set_app_tracker(self, tracker):
        """Attach the UsageTracker so the sync loop can upload its totals and
        feed it the per-app rules from the dashboard."""
        self._tracker = tracker

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
            if command == 'extend_browser' and self._extend_browser_cb:
                minutes = int(params.get('minutes', 30))
                self._extend_browser_cb(minutes * 60)
                log.info('[supabase_sync] extend_browser +%dm', minutes)
            elif command == 'extend_roblox' and self._extend_roblox_cb:
                minutes = int(params.get('minutes', 30))
                self._extend_roblox_cb(minutes * 60)
                log.info('[supabase_sync] extend_roblox +%dm', minutes)
            elif command == 'block_browser' and self._block_browser_cb:
                self._block_browser_cb()
                log.info('[supabase_sync] block_browser executed')
            elif command == 'block_roblox' and self._block_roblox_cb:
                self._block_roblox_cb()
                log.info('[supabase_sync] block_roblox executed')
            elif command == 'show_message' and self._show_message_cb:
                message = str(params.get('message', ''))[:500]
                self._show_message_cb(message)
                log.info('[supabase_sync] show_message: %s', message[:60])
            elif command == 'extend_app' and self._extend_app_cb:
                exe     = str(params.get('exe_name', '')).lower()[:120]
                minutes = int(params.get('minutes', 15))
                if exe:
                    self._extend_app_cb(exe, minutes * 60)
                    log.info('[supabase_sync] extend_app %s +%dm', exe, minutes)
            elif command == 'block_app' and self._block_app_cb:
                exe = str(params.get('exe_name', '')).lower()[:120]
                if exe:
                    self._block_app_cb(exe)
                    log.info('[supabase_sync] block_app %s', exe)
            elif command == 'close_app' and self._close_app_cb:
                exe = str(params.get('exe_name', '')).lower()[:120]
                if exe:
                    self._close_app_cb(exe)
                    log.info('[supabase_sync] close_app %s', exe)
            elif command == 'unblock_app' and self._unblock_app_cb:
                exe = str(params.get('exe_name', '')).lower()[:120]
                if exe:
                    self._unblock_app_cb(exe)
                    log.info('[supabase_sync] unblock_app %s', exe)
            elif command == 'unblock_all_apps' and self._unblock_all_cb:
                self._unblock_all_cb()
                log.info('[supabase_sync] unblock_all_apps executed')
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

    # ── Push blocked attempt ──────────────────────────────────────────────────

    def push_blocked_attempt(self, domain: str, url: str, reason: str):
        """Log a blocked adult URL to the blocked_attempts Supabase table."""
        if not self._is_configured():
            return
        try:
            payload = {
                'device_id': DEVICE_ID,
                'domain':    domain,
                'url':       url[:500],
                'reason':    reason[:200],
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }
            hdrs = self._headers()
            hdrs['Prefer'] = 'return=minimal'
            resp = requests.post(self._url('blocked_attempts'), json=payload,
                                 headers=hdrs, timeout=5)
            if resp.status_code not in (200, 201):
                log.warning('[supabase_sync] push_blocked HTTP %s', resp.status_code)
        except Exception as e:
            log.warning('[supabase_sync] push_blocked error: %s', e)

    # ── Per-app usage upload + rule download ─────────────────────────────────

    def _push_app_usage(self):
        """Upsert today's running totals. Re-sending the full total each cycle
        means a dropped upload self-heals next time instead of losing minutes."""
        rows = self._tracker.snapshot()
        if not rows:
            return
        today = datetime.now().date().isoformat()
        now   = datetime.now(timezone.utc).isoformat()
        # last_seen must be when the app was really on screen, NOT upload time —
        # stamping every row with "now" made closed apps look permanently live.
        payload = [{
            'device_id':    DEVICE_ID,
            'exe_name':     r['exe_name'],
            'display_name': r['display_name'][:120],
            'usage_date':   today,
            'seconds_used': r['seconds_used'],
            'last_seen':    r.get('last_seen') or now,
        } for r in rows]
        hdrs = self._headers()
        hdrs['Prefer'] = 'resolution=merge-duplicates,return=minimal'
        resp = requests.post(self._url('app_usage'), json=payload,
                             headers=hdrs, timeout=8)
        if resp.status_code not in (200, 201):
            log.warning('[supabase_sync] push_app_usage HTTP %s: %s',
                        resp.status_code, resp.text[:200])

    def _push_known_apps(self):
        """Register apps we have not reported yet — this is what triggers the
        'new app' email. Only sent once per app per device."""
        pending = self._tracker.new_apps_to_report()
        if not pending:
            return
        now = datetime.now(timezone.utc).isoformat()
        payload = [{
            'device_id':    DEVICE_ID,
            'exe_name':     a['exe_name'],
            'display_name': (a['display_name'] or '')[:120],
            'exe_path':     a['exe_path'],
            'is_store_app': a['is_store_app'],
            'last_seen':    now,
        } for a in pending]
        hdrs = self._headers()
        hdrs['Prefer'] = 'resolution=merge-duplicates,return=minimal'
        resp = requests.post(self._url('known_apps'), json=payload,
                             headers=hdrs, timeout=8)
        if resp.status_code in (200, 201):
            self._tracker.mark_reported([a['exe_name'] for a in pending])
            log.info('[supabase_sync] registered %d new app(s): %s',
                     len(pending), [a['exe_name'] for a in pending])
        else:
            log.warning('[supabase_sync] push_known_apps HTTP %s', resp.status_code)

    def _pull_app_rules(self):
        """Fetch this device's per-app rules and hand them to the tracker."""
        resp = requests.get(
            self._url('app_rules'),
            params={'device_id': f'eq.{DEVICE_ID}', 'limit': '200'},
            headers=self._headers(), timeout=8,
        )
        if resp.status_code != 200:
            return
        self._tracker.apply_rules(resp.json())

    def _app_cycle(self):
        """Runs about once a minute (every 12th 5s loop)."""
        if self._tracker is None or not self._is_configured():
            return
        try:
            self._pull_app_rules()
        except Exception as e:
            if self._offline_count == 0:
                log.warning('[supabase_sync] pull_app_rules: %s', e)
        try:
            self._push_app_usage()
        except Exception as e:
            if self._offline_count == 0:
                log.warning('[supabase_sync] push_app_usage: %s', e)
        try:
            self._push_known_apps()
        except Exception as e:
            if self._offline_count == 0:
                log.warning('[supabase_sync] push_known_apps: %s', e)

    # ── Log cleanup ───────────────────────────────────────────────────────────

    def cleanup_old_logs(self, days: int = 14):
        """Delete this device's device_logs rows older than `days` days."""
        if not self._is_configured():
            return
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            hdrs = self._headers()
            hdrs['Prefer'] = 'return=minimal'
            requests.delete(
                self._url('device_logs'),
                params={'device_id': f'eq.{DEVICE_ID}', 'ts': f'lt.{cutoff}'},
                headers=hdrs, timeout=10,
            )
        except Exception as e:
            log.warning('[supabase_sync] cleanup_old_logs error: %s', e)

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
            # Per-app usage/rules are far less time-critical than the 5s timer
            # push, so run them about once a minute to keep traffic light.
            self._app_tick += 1
            if self._app_tick >= 12:
                self._app_tick = 0
                self._app_cycle()
