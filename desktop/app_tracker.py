"""
Per-app usage tracking and enforcement for Browser Guardian.

Why windows and not raw processes
---------------------------------
A raw process list has 150+ entries on a normal PC and is almost all Windows
internals. We instead enumerate *visible top-level windows* and resolve the
process that owns each one, which yields the handful of apps the child is
actually using (Minecraft, Steam, a launcher, ...).

Counting model
--------------
Deliberately simpler than the Roblox TimerManager, which caused most of our
past bugs (extensions that didn't resume, reboots resetting time). Here we just
add POLL_SECS to each visible app's running total for today. "Over limit" means
total >= limit. Granting extra time adds to today's allowance. Midnight zeroes
everything. The number the dashboard shows is exactly the number enforced.

Store (UWP) apps
----------------
A packaged app's window often belongs to ApplicationFrameHost.exe rather than
the game. We walk that window's child processes to find the real executable, so
Minecraft Education is attributed to its own exe and not to the Windows host.
"""
import ctypes
import json
import logging
import os
import subprocess
import threading
import time
from ctypes import wintypes
from datetime import datetime, timezone

import psutil

log = logging.getLogger(__name__)

POLL_SECS = 15          # how often we sample visible windows
_user32 = ctypes.windll.user32
_CREATE_NO_WINDOW = 0x08000000

# Never track, never let a rule apply. Mirrors the Supabase trigger list so a
# bad rule can't reach the enforcement path even if the DB row somehow exists.
PROTECTED = {
    'explorer.exe', 'winlogon.exe', 'csrss.exe', 'services.exe', 'lsass.exe',
    'smss.exe', 'wininit.exe', 'svchost.exe', 'dwm.exe', 'taskhostw.exe',
    'ctfmon.exe', 'sihost.exe', 'fontdrvhost.exe', 'runtimebroker.exe',
    'searchhost.exe', 'startmenuexperiencehost.exe', 'shellexperiencehost.exe',
    'applicationframehost.exe', 'systemsettings.exe', 'userinit.exe',
    'browserguardian.exe', 'wscript.exe', 'cscript.exe', 'system',
    'registry', 'memory compression', 'textinputhost.exe', 'lockapp.exe',
    'searchindexer.exe', 'audiodg.exe', 'conhost.exe', 'backgroundtaskhost.exe',
    # ── Recovery tools — NEVER blockable ──────────────────────────────────────
    # Blocking any of these removes the ability to fix the PC remotely. We hit
    # this for real on 2026-10-04: a "Close now" on cmd.exe wrote a launch-block
    # that locked Command Prompt, which is exactly where the schtasks recovery
    # commands get typed. Non-negotiable.
    'cmd.exe', 'powershell.exe', 'pwsh.exe', 'taskmgr.exe', 'regedit.exe',
    'mmc.exe', 'control.exe', 'msconfig.exe', 'cmd', 'powershell',
}

# Handled by their own dedicated timers already — don't double-count or
# double-enforce. Roblox detection/enforcement stays exactly as it is today.
EXCLUDED = {
    'chrome.exe', 'msedge.exe', 'copilot.exe',
    'robloxplayerbeta.exe', 'robloxplayer.exe', 'robloxplayerlauncher.exe',
    'roblox.exe', 'robloxstudiobeta.exe', 'robloxcrashhandler.exe',
}

# Windows host processes whose real app lives in a child process.
_UWP_HOSTS = {'applicationframehost.exe'}


def _is_trackable(name: str) -> bool:
    n = (name or '').lower()
    if not n or n in PROTECTED or n in EXCLUDED:
        return False
    if 'roblox' in n:          # matches browser_monitor's broad Roblox rule
        return False
    return True


def _real_proc_for_window(pid: int):
    """Return the psutil.Process that should be credited for this window.

    For a UWP host (ApplicationFrameHost), the visible window belongs to the
    host but the actual app is a child process — walk one level down and pick
    the first child that isn't itself a host/system process.
    """
    try:
        proc = psutil.Process(pid)
        name = (proc.name() or '').lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None

    if name in _UWP_HOSTS:
        try:
            for child in proc.children(recursive=True):
                try:
                    cname = (child.name() or '').lower()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                if cname and cname not in _UWP_HOSTS and cname not in PROTECTED:
                    return child
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return None      # host with no resolvable child — skip it
    return proc


def visible_apps():
    """{exe_name_lower: {'name','path','pid','is_store'}} for on-screen apps."""
    found = {}
    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _cb(hwnd, _lparam):
        try:
            if not _user32.IsWindowVisible(hwnd):
                return True
            # Skip tool/child windows with no title — tray helpers, invisible hosts
            if _user32.GetWindowTextLengthW(hwnd) == 0:
                return True
            pid = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value:
                return True
            proc = _real_proc_for_window(pid.value)
            if proc is None:
                return True
            name = (proc.name() or '').lower()
            if not _is_trackable(name):
                return True
            try:
                path = proc.exe() or ''
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                path = ''
            if name not in found:
                found[name] = {
                    'name':     name,
                    'path':     path,
                    'pid':      proc.pid,
                    'is_store': 'windowsapps' in path.lower(),
                }
        except Exception:
            pass          # never let one bad window break the scan
        return True

    try:
        _user32.EnumWindows(EnumWindowsProc(_cb), 0)
    except Exception as e:
        log.warning('[app_tracker] EnumWindows failed: %s', e)
    return found


def friendly_name(exe_name: str, path: str = '') -> str:
    """Human-readable label for the dashboard, derived from the exe name."""
    base = (exe_name or '').lower()
    for suffix in ('.exe',):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    known = {
        'minecraft.windows':      'Minecraft Education',
        'minecraftedu':           'Minecraft Education',
        'javaw':                  'Minecraft (Java)',
        'steam':                  'Steam',
        'steamwebhelper':         'Steam',
        'epicgameslauncher':      'Epic Games',
        'fortniteclient-win64-shipping': 'Fortnite',
        'discord':                'Discord',
        'spotify':                'Spotify',
        'vlc':                    'VLC',
        'notepad':                'Notepad',
        'mspaint':                'Paint',
        'winword':                'Word',
        'excel':                  'Excel',
        'powerpnt':               'PowerPoint',
    }
    if base in known:
        return known[base]
    return base.replace('-', ' ').replace('_', ' ').title()


# ─────────────────────────────────────────────────────────────────────────────
# Usage counting + enforcement
# ─────────────────────────────────────────────────────────────────────────────
class UsageTracker:
    """Counts per-app seconds for today, persists them, and enforces rules.

    Callbacks are injected so this module never imports main.py:
      run_warning(label, secs) -> blocks for `secs` showing the save warning
      force_close(exe_name)    -> abruptly close every process with that name
      engage_block(exe_name)   -> stop it relaunching (IFEO); may be a no-op
      release_block(exe_name)  -> undo engage_block
    """

    def __init__(self, base_dir, get_config, device_id,
                 run_warning=None, force_close=None,
                 engage_block=None, release_block=None):
        self._base        = base_dir
        self._get_config  = get_config
        self._device_id   = device_id
        self._run_warning = run_warning
        self._force_close = force_close
        self._engage      = engage_block
        self._release     = release_block

        self._state_file  = os.path.join(base_dir, 'app_usage.json')
        self._rules_file  = os.path.join(base_dir, 'app_rules.json')

        self._date    = datetime.now().date().isoformat()
        self._counts  = {}      # exe_name -> seconds used today
        self._meta    = {}      # exe_name -> {'path','is_store','display'}
        self._rules   = {}      # exe_name -> {'action','daily_limit_mins','is_game'}
        self._bonus   = {}      # exe_name -> extra seconds granted today
        self._warned  = set()   # apps already given their warning today
        self._warning_active = set()   # apps mid-warning: do not kill yet
        self._known   = set()   # apps already reported to known_apps
        # Every app we have an active launch-block on. Tracked on disk and
        # INDEPENDENTLY of _rules, because a block can be applied to an app that
        # has no rule (the dashboard "Block" action). Previously the cleanup
        # paths only walked _rules, so such a block could never be released —
        # that is how cmd.exe ended up permanently blocked on 2026-10-04.
        self._blocked = set()
        # exe_name -> ISO timestamp when it was last actually ON SCREEN. Kept
        # separate from the upload time: previously every row was stamped with
        # "now" on each upload, so an app closed hours ago still looked live on
        # the dashboard (all rows shared one identical last_seen).
        self._seen_at = {}

        self._load_state()
        self._load_rules()

    # -- disk persistence ---------------------------------------------------
    def _load_state(self):
        try:
            with open(self._state_file) as f:
                data = json.load(f)
        except Exception:
            return
        if data.get('date') != self._date:
            # Stale day: today's counts start at zero, but any launch-block left
            # over from that older day must still be cleared. The registry block
            # survives reboots, so if we did not do this an app could stay
            # blocked indefinitely whenever the PC was off at midnight (or the
            # guardian failed to start for a few days).
            stale = set(data.get('blocked') or [])
            if stale:
                log.info('[app_tracker] clearing %d stale launch-block(s) from %s: %s',
                         len(stale), data.get('date'), sorted(stale))
                for exe in stale:
                    if self._release:
                        try:
                            self._release(exe)
                        except Exception as e:
                            log.warning('[app_tracker] stale release %s failed: %s', exe, e)
                self._blocked = set()
                self.save_state()
            return
        self._blocked = set(data.get('blocked') or [])
        self._seen_at = data.get('seen_at') or {}
        self._counts = {k: int(v) for k, v in (data.get('counts') or {}).items()}
        self._meta   = data.get('meta') or {}
        self._bonus  = {k: int(v) for k, v in (data.get('bonus') or {}).items()}
        self._warned = set(data.get('warned') or [])
        self._known  = set(data.get('known') or [])
        log.info('[app_tracker] restored usage for %d app(s) today', len(self._counts))

    def save_state(self):
        try:
            tmp = self._state_file + '.tmp'
            with open(tmp, 'w') as f:
                json.dump({
                    'date':   self._date,
                    'counts': self._counts,
                    'meta':   self._meta,
                    'bonus':  self._bonus,
                    'warned': sorted(self._warned),
                    'known':  sorted(self._known),
                    'blocked': sorted(self._blocked),
                    'seen_at': self._seen_at,
                }, f)
            os.replace(tmp, self._state_file)   # atomic; no truncated file on crash
        except Exception as e:
            log.debug('[app_tracker] save_state failed: %s', e)

    def _load_rules(self):
        """Local rule cache so limits still apply with no internet."""
        try:
            with open(self._rules_file) as f:
                self._rules = json.load(f) or {}
            log.info('[app_tracker] loaded %d cached rule(s)', len(self._rules))
        except Exception:
            self._rules = {}

    def _save_rules(self):
        try:
            tmp = self._rules_file + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(self._rules, f)
            os.replace(tmp, self._rules_file)
        except Exception as e:
            log.debug('[app_tracker] save_rules failed: %s', e)

    # -- day rollover -------------------------------------------------------
    def release_all_blocks(self):
        """Lift EVERY launch-block we applied. Walks the tracked block set (not
        _rules), so a block on an app with no rule is still released."""
        targets = sorted(self._blocked | set(self._rules))
        released = []
        for exe in targets:
            if self._release:
                try:
                    self._release(exe)
                    released.append(exe)
                except Exception as e:
                    log.warning('[app_tracker] release %s failed: %s', exe, e)
        self._blocked = set()
        self.save_state()
        if released:
            log.info('[app_tracker] released %d launch-block(s): %s',
                     len(released), released)
        return released

    def blocked_apps(self):
        return sorted(self._blocked)

    def reset_for_new_day(self):
        """Zero everything and lift every block this tracker applied."""
        self.release_all_blocks()
        self._date   = datetime.now().date().isoformat()
        self._counts = {}
        self._bonus  = {}
        self._warned = set()
        self._warning_active = set()
        self.save_state()
        log.info('[app_tracker] reset for new day (%s), blocks lifted', self._date)

    # -- queries ------------------------------------------------------------
    def seconds_used(self, exe_name):
        return int(self._counts.get(exe_name, 0))

    def limit_secs(self, exe_name):
        """Effective limit in seconds today, or None if unlimited."""
        rule = self._rules.get(exe_name) or {}
        if rule.get('action') != 'limit':
            return None
        mins = rule.get('daily_limit_mins')
        if not mins:
            return None
        return int(mins) * 60 + int(self._bonus.get(exe_name, 0))

    def is_over_limit(self, exe_name):
        lim = self.limit_secs(exe_name)
        return lim is not None and self.seconds_used(exe_name) >= lim

    def grant_extra(self, exe_name, secs):
        """Parent granted more time today: extend the allowance and unblock."""
        exe_name = (exe_name or '').lower()
        self._bonus[exe_name] = int(self._bonus.get(exe_name, 0)) + int(secs)
        self._warned.discard(exe_name)
        if self._release:
            try:
                self._release(exe_name)
            except Exception:
                pass
        self._blocked.discard(exe_name)
        self.save_state()
        log.info('[app_tracker] granted +%ds to %s (allowance %ss, used %ss)',
                 secs, exe_name, self.limit_secs(exe_name), self.seconds_used(exe_name))

    def snapshot(self):
        """List of per-app dicts for upload / display."""
        out = []
        for exe, secs in self._counts.items():
            meta = self._meta.get(exe) or {}
            out.append({
                'exe_name':     exe,
                'display_name': meta.get('display') or friendly_name(exe, meta.get('path', '')),
                'seconds_used': int(secs),
                'is_store':     bool(meta.get('is_store')),
                'path':         meta.get('path', ''),
                # When it was really last on screen (not when we last uploaded).
                'last_seen':    self._seen_at.get(exe),
                'is_blocked':   exe in self._blocked,
            })
        out.sort(key=lambda r: -r['seconds_used'])
        return out

    def new_apps_to_report(self):
        """Apps seen that we have not registered in known_apps yet."""
        pending = []
        for exe, meta in self._meta.items():
            if exe in self._known:
                continue
            pending.append({
                'exe_name':     exe,
                'display_name': meta.get('display') or friendly_name(exe, meta.get('path', '')),
                'exe_path':     (meta.get('path') or '')[:400],
                'is_store_app': bool(meta.get('is_store')),
            })
        return pending

    def mark_reported(self, exe_names):
        self._known.update(exe_names)
        self.save_state()

    def seed_known(self, exe_names):
        """First run: record what is already installed WITHOUT alerting, so the
        parent does not get a flood of emails on day one."""
        self._known.update(n.lower() for n in exe_names)
        self.save_state()

    # -- rules from the dashboard -------------------------------------------
    def apply_rules(self, rows):
        """Replace the rule cache from Supabase rows, ignoring protected apps."""
        rules = {}
        for r in rows or []:
            exe = (r.get('exe_name') or '').lower()
            if not exe or exe in PROTECTED:
                continue
            rules[exe] = {
                'action':           r.get('action') or 'allow',
                'daily_limit_mins': r.get('daily_limit_mins'),
                'is_game':          bool(r.get('is_game')),
            }
        self._rules = rules
        self._save_rules()

    def rules(self):
        return dict(self._rules)

    # -- sampling -----------------------------------------------------------
    def sample_once(self):
        """One poll: credit POLL_SECS to every visible app, then enforce.

        Called every POLL_SECS. Rolls the day over on its own so a PC left on
        past midnight still resets.
        """
        today = datetime.now().date().isoformat()
        if today != self._date:
            self.reset_for_new_day()

        now_iso = datetime.now(timezone.utc).isoformat()
        for exe, info in visible_apps().items():
            self._counts[exe] = int(self._counts.get(exe, 0)) + POLL_SECS
            self._seen_at[exe] = now_iso        # genuinely on screen right now
            meta = self._meta.setdefault(exe, {})
            meta['path']     = info.get('path') or meta.get('path', '')
            meta['is_store'] = bool(info.get('is_store'))
            meta.setdefault('display', friendly_name(exe, meta['path']))
            self._enforce(exe, info)

    def _enforce(self, exe, info):
        """Apply this app's rule. Never touches a protected process."""
        if exe in PROTECTED or exe in EXCLUDED:
            return
        rule = self._rules.get(exe)
        if not rule:
            return
        action = rule.get('action')
        label  = (self._meta.get(exe) or {}).get('display') or friendly_name(exe)

        # Outright block: close at once, no warning (the parent chose this).
        if action == 'block':
            log.info('[app_tracker] %s is blocked - closing immediately', exe)
            self._close_and_lock(exe)
            return

        if action != 'limit' or not self.is_over_limit(exe):
            return

        # Over a daily limit. First time today: give the save-progress warning,
        # then close. Afterwards: close on sight, no repeat warning.
        if exe in self._warning_active:
            return                      # warning already on screen for this app
        if exe in self._warned:
            log.info('[app_tracker] %s over limit and already warned - closing', exe)
            self._close_and_lock(exe)
            return

        warn_secs = int((self._get_config() or {}).get('roblox_warning_seconds', 60))
        self._warned.add(exe)
        self.save_state()
        log.info('[app_tracker] %s hit its %s min limit - %ss save warning',
                 exe, (rule.get('daily_limit_mins')), warn_secs)

        def warn_then_close():
            try:
                self._warning_active.add(exe)
                if warn_secs > 0 and self._run_warning:
                    self._run_warning(label, warn_secs)
            except Exception as e:
                log.error('[app_tracker] warning for %s failed: %s', exe, e)
            finally:
                self._warning_active.discard(exe)
            log.info('[app_tracker] warning elapsed for %s - closing + blocking', exe)
            self._close_and_lock(exe)

        threading.Thread(target=warn_then_close, daemon=True).start()

    def _close_and_lock(self, exe):
        """Block relaunch first, then force-close - same order as Roblox.

        Roblox taught us that closing first lets the app respawn in the gap
        before the block lands, so the block goes on first.
        """
        if exe in PROTECTED:
            log.warning('[app_tracker] refusing to block protected process %s', exe)
            return
        if self._engage:
            try:
                self._engage(exe)
                self._blocked.add(exe)   # remember, so it can always be released
                self.save_state()
            except Exception as e:
                log.warning('[app_tracker] engage_block %s failed: %s', exe, e)
        if self._force_close:
            try:
                self._force_close(exe)
            except Exception as e:
                log.warning('[app_tracker] force_close %s failed: %s', exe, e)

    def close_only(self, exe):
        """Close an app WITHOUT blocking relaunch (dashboard 'Close' action).

        Deliberately separate from blocking: a parent who just wants the game
        shut right now should not silently create a persistent launch-block.
        """
        exe = (exe or '').lower()
        if exe in PROTECTED:
            log.warning('[app_tracker] refusing to close protected process %s', exe)
            return 0
        log.info('[app_tracker] close-only requested for %s', exe)
        if self._force_close:
            try:
                return self._force_close(exe)
            except Exception as e:
                log.warning('[app_tracker] close_only %s failed: %s', exe, e)
        return 0

    def block_now(self, exe):
        """Close AND block relaunch (dashboard 'Block' action)."""
        exe = (exe or '').lower()
        if exe in PROTECTED:
            log.warning('[app_tracker] refusing to block protected process %s', exe)
            return
        log.info('[app_tracker] block requested for %s', exe)
        self._close_and_lock(exe)

    def unblock(self, exe):
        """Release one app's launch-block."""
        exe = (exe or '').lower()
        if self._release:
            try:
                self._release(exe)
            except Exception as e:
                log.warning('[app_tracker] unblock %s failed: %s', exe, e)
        self._blocked.discard(exe)
        self._warned.discard(exe)
        self.save_state()
        log.info('[app_tracker] unblocked %s', exe)

    def enforce_sweep(self):
        """Safety net, independent of the sampling loop.

        Catches a blocked/over-limit app that is running but produced no visible
        window this cycle (minimised oddly, relaunched between polls, or a
        partial kill). Mirrors the enforcement poll we added for Roblox.
        """
        for exe, rule in self._rules.items():
            if exe in PROTECTED or exe in EXCLUDED:
                continue
            action = rule.get('action')
            if action == 'block':
                over = True
            elif action == 'limit':
                over = self.is_over_limit(exe)
            else:
                continue
            if not over or exe in self._warning_active:
                continue
            if _is_running(exe):
                log.info('[app_tracker] sweep found %s running while restricted - closing', exe)
                self._close_and_lock(exe)


def _is_running(exe_name):
    """True if any process currently has this executable name."""
    target = (exe_name or '').lower()
    if not target:
        return False
    for proc in psutil.process_iter(['name']):
        try:
            if (proc.info.get('name') or '').lower() == target:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def force_close_by_name(exe_name):
    """Abruptly terminate every process with this name. Returns count killed.

    Hard kill only - no graceful WM_CLOSE - so the app cannot show a
    "save before quitting?" prompt that would hold the close open. Protected
    processes are refused outright.
    """
    target = (exe_name or '').lower()
    if not target or target in PROTECTED:
        log.warning('[app_tracker] refusing to close protected/empty name: %r', exe_name)
        return 0
    victims = []
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if (proc.info.get('name') or '').lower() == target:
                victims.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if not victims:
        return 0
    log.info('[app_tracker] force-closing %s: pids=%s',
             target, sorted(p.pid for p in victims))
    for proc in victims:
        try:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    try:
        subprocess.run(['taskkill', '/F', '/T', '/IM', target],
                       capture_output=True, creationflags=_CREATE_NO_WINDOW)
    except Exception:
        pass
    gone, alive = psutil.wait_procs(victims, timeout=3)
    if alive:
        log.error('[app_tracker] %s survived close (needs elevation?): %s',
                  target, sorted(p.pid for p in alive))
    return len(gone)
