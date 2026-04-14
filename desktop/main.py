"""
Browser Guardian — System Tray App
Monitors browser usage time and captures browsing history.

Timer rules:
- Timer only ticks while the browser is actually running.
- If the browser is closed manually → timer pauses.
- If the browser is reopened and time remains → timer resumes.
- If the browser is reopened with 0 time → password dialog shown immediately.
- Timer NEVER auto-restarts; only resets when the parent enters the correct password.
"""
import threading
import time
import os
import sys
import winreg
import logging
import traceback
from datetime import datetime, timedelta

import pystray
from PIL import Image, ImageDraw

# ── Logging setup ─────────────────────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    _BASE = os.path.dirname(sys.executable)
else:
    _BASE = os.path.dirname(os.path.abspath(__file__))

logging.basicConfig(
    filename=os.path.join(_BASE, 'browser_guardian.log'),
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
# Also mirror to stdout when running from terminal
logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))
log = logging.getLogger(__name__)


def _log_exception(exc_type, exc_value, exc_tb):
    """Log unhandled exceptions to file before the process dies."""
    log.critical('UNHANDLED EXCEPTION:\n%s',
                 ''.join(traceback.format_exception(exc_type, exc_value, exc_tb)))


sys.excepthook = _log_exception
threading.excepthook = lambda args: log.critical(
    'UNHANDLED THREAD EXCEPTION (thread=%s):\n%s',
    args.thread.name if args.thread else '?',
    ''.join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)),
)

from config import load_config, save_config
from db_manager import init_db, insert_urls, get_unsynced, mark_synced
from history_reader import get_new_history
from browser_monitor import is_browser_running, kill_browsers, is_roblox_running, kill_roblox
from timer_manager import TimerManager, TimerState
from password_dialog import PasswordDialog
from settings_dialog import SettingsDialog
from cloud_sync import CloudSync
from classifier import classify
from url_watcher import UrlWatcher
from supabase_sync import SupabaseSync
from message_dialog import MessageDialog

# ── State ─────────────────────────────────────────────────────────────────────
config = load_config()
if config.get('gemini_api_key'):
    os.environ['GEMINI_API_KEY'] = config['gemini_api_key']
cloud_sync = CloudSync(lambda: config)
last_history_check = None
tray_icon = None
_dialog_open = False
_dialog_lock = threading.Lock()

_STARTUP_REG_KEY  = r'Software\Microsoft\Windows\CurrentVersion\Run'
_STARTUP_APP_NAME = 'BrowserGuardian'


# ── Icon helpers ──────────────────────────────────────────────────────────────
def _make_icon(color):
    img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fill = {
        'green':  (30, 180, 30),
        'orange': (220, 140, 0),
        'red':    (200, 40, 40),
    }.get(color, (30, 180, 30))
    d.ellipse([4, 4, 60, 60], fill=fill)
    d.line([32, 32, 32, 16], fill='white', width=3)
    d.line([32, 32, 44, 38], fill='white', width=3)
    return img


def _set_icon(color):
    try:
        tray_icon.icon = _make_icon(color)
    except Exception:
        pass


# ── Startup registration helpers ──────────────────────────────────────────────
def _get_startup_cmd():
    """Return the command used to launch this script silently (no terminal window)."""
    if getattr(sys, 'frozen', False):
        # Running as compiled EXE — register the EXE itself
        return f'"{sys.executable}"'
    # Running from source — always prefer the compiled EXE if it exists,
    # so the startup entry is stable and self-contained.
    _src_dir = os.path.dirname(os.path.abspath(__file__))
    _exe = os.path.join(_src_dir, 'dist', 'BrowserGuardian', 'BrowserGuardian.exe')
    if os.path.exists(_exe):
        return f'"{_exe}"'
    # Fallback: run source via pythonw (no console window)
    pythonw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    return f'"{pythonw}" "{os.path.abspath(__file__)}"'


def is_registered_at_startup():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_REG_KEY, 0,
                             winreg.KEY_READ)
        winreg.QueryValueEx(key, _STARTUP_APP_NAME)
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        return False


def register_startup():
    """Add app to Windows startup via registry (HKCU — no admin needed)."""
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_REG_KEY, 0,
                         winreg.KEY_SET_VALUE)
    winreg.SetValueEx(key, _STARTUP_APP_NAME, 0, winreg.REG_SZ,
                      _get_startup_cmd())
    winreg.CloseKey(key)


def remove_startup():
    """Remove app from Windows startup registry."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_REG_KEY, 0,
                             winreg.KEY_SET_VALUE)
        winreg.DeleteValue(key, _STARTUP_APP_NAME)
        winreg.CloseKey(key)
    except FileNotFoundError:
        pass  # Already removed


# ── Password dialog helpers ───────────────────────────────────────────────────
def _show_password_dialog(subject='Browser', on_correct=None, on_timeout=None):
    """Show the lock password dialog; guard against duplicates."""
    global _dialog_open
    with _dialog_lock:
        if _dialog_open:
            return
        _dialog_open = True

    def run():
        global _dialog_open
        try:
            dialog = PasswordDialog(
                countdown_secs=config['auto_close_seconds'],
                on_correct=on_correct,
                on_timeout=on_timeout,
                get_password=lambda: config['password'],
                subject=subject,
            )
            dialog.show()
        finally:
            with _dialog_lock:
                _dialog_open = False

    threading.Thread(target=run, daemon=True).start()


# ── Timer / browser event callbacks ──────────────────────────────────────────
def _on_timer_expired():
    _set_icon('red')
    _show_password_dialog(
        subject='Browser',
        on_correct=_on_password_correct,
        on_timeout=_on_password_timeout,
    )


def _on_password_correct():
    timer_mgr.start_new_session()
    _set_icon('green')


def _on_password_timeout():
    kill_browsers()
    _set_icon('red')


# ── Roblox timer callbacks ────────────────────────────────────────────────────
def _on_roblox_timer_expired():
    _show_password_dialog(
        subject='Roblox',
        on_correct=_on_roblox_password_correct,
        on_timeout=_on_roblox_password_timeout,
    )


def _on_roblox_password_correct():
    roblox_timer_mgr.start_new_session()


def _on_roblox_password_timeout():
    kill_roblox()


# ── Browser state watcher ─────────────────────────────────────────────────────
def _browser_watch_loop():
    was_running = False
    while True:
        try:
            now_running = is_browser_running()
            if now_running and not was_running:
                if timer_mgr.state == TimerState.IDLE:
                    # Very first launch — start fresh session
                    timer_mgr.start_new_session()
                    _set_icon('green')
                elif timer_mgr.state == TimerState.PAUSED and timer_mgr.get_remaining() > 0:
                    timer_mgr.resume()
                    _set_icon('green')
                elif timer_mgr.is_expired():
                    _set_icon('red')
                    _show_password_dialog(
                        subject='Browser',
                        on_correct=_on_password_correct,
                        on_timeout=_on_password_timeout,
                    )
            elif not now_running and was_running:
                if timer_mgr.state == TimerState.RUNNING:
                    timer_mgr.pause()
                    _set_icon('orange')
            was_running = now_running
        except Exception as e:
            log.error('[browser_watch] %s', e)
        time.sleep(2)


# ── Roblox state watcher ─────────────────────────────────────────────────────
def _roblox_watch_loop():
    was_running = False
    while True:
        try:
            now_running = is_roblox_running()
            if now_running and not was_running:
                if roblox_timer_mgr.state == TimerState.IDLE:
                    roblox_timer_mgr.start_new_session()
                elif roblox_timer_mgr.state == TimerState.PAUSED and roblox_timer_mgr.get_remaining() > 0:
                    roblox_timer_mgr.resume()
                elif roblox_timer_mgr.is_expired():
                    kill_roblox()
            elif not now_running and was_running:
                if roblox_timer_mgr.state == TimerState.RUNNING:
                    roblox_timer_mgr.pause()
            was_running = now_running
        except Exception as e:
            log.error('[roblox_watch] %s', e)
        time.sleep(2)


# ── UI Automation URL watcher ─────────────────────────────────────────────────
def _on_url_from_watcher(url: str, domain: str, visited_at: str):
    try:
        result = classify(url, '', domain)
        insert_urls([(
            url, '', domain, visited_at,
            1 if result.get('is_flagged') else 0,
            result.get('category', 'unclassified'),
            result.get('reason', ''),
            result.get('severity', 'low'),
        )])
    except Exception as e:
        log.error('[url_watcher_cb] %s', e)


url_watcher = UrlWatcher(_on_url_from_watcher, interval=5)

# ── Supabase remote sync ──────────────────────────────────────────────────────
def _browser_state():
    return timer_mgr.state, timer_mgr.get_remaining()

def _roblox_state():
    return roblox_timer_mgr.state, roblox_timer_mgr.get_remaining()

def _remote_block_browser():
    kill_browsers()
    timer_mgr.force_block()

def _remote_block_roblox():
    kill_roblox()
    roblox_timer_mgr.force_block()

def _remote_show_message(message):
    threading.Thread(target=lambda: MessageDialog(message).show(), daemon=True).start()

supabase_sync = SupabaseSync(lambda: config, _browser_state, _roblox_state)
supabase_sync.set_extend_callbacks(
    extend_browser=lambda secs: timer_mgr.add_time(secs),
    extend_roblox=lambda secs: roblox_timer_mgr.add_time(secs),
)
supabase_sync.set_action_callbacks(
    block_browser=_remote_block_browser,
    block_roblox=_remote_block_roblox,
    show_message=_remote_show_message,
)


# ── Background history sync ───────────────────────────────────────────────────
def _history_sync_loop():
    global last_history_check
    while True:
        try:
            raw_entries = get_new_history(last_history_check)
            if raw_entries:
                classified = []
                for url, title, domain, visited_at in raw_entries:
                    result = classify(url, title, domain)
                    classified.append((
                        url, title, domain, visited_at,
                        1 if result.get('is_flagged') else 0,
                        result.get('category', 'unclassified'),
                        result.get('reason', ''),
                        result.get('severity', 'low'),
                    ))
                insert_urls(classified)
                from datetime import datetime
                last_history_check = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            unsynced = get_unsynced()
            if unsynced:
                ok, msg = cloud_sync.sync(unsynced)
                if ok:
                    mark_synced([r[0] for r in unsynced])
                else:
                    log.warning('[sync] Upload failed: %s', msg)
        except Exception as e:
            log.error('[history_sync] %s', e)
        time.sleep(30)


# ── Nightly reset ────────────────────────────────────────────────────────────
_RESET_FILE = os.path.join(_BASE, 'last_reset.txt')

def _midnight_reset_loop():
    """
    Reset both timers to daily allowance at midnight.
    On startup, if the last recorded reset was before today (laptop was off
    at midnight), do a catch-up reset immediately so each day starts fresh.
    """
    def _do_reset():
        timer_mgr.reset_to_idle()
        roblox_timer_mgr.reset_to_idle()
        today_str = datetime.now().date().isoformat()
        try:
            with open(_RESET_FILE, 'w') as f:
                f.write(today_str)
        except Exception:
            pass
        log.info('[midnight_reset] timers reset (%s)', today_str)

    # ── Catch-up: did we miss midnight while the laptop was off? ──────────
    today = datetime.now().date()
    last_reset = None
    try:
        with open(_RESET_FILE) as f:
            last_reset = datetime.strptime(f.read().strip(), '%Y-%m-%d').date()
    except Exception:
        pass

    if last_reset is None or last_reset < today:
        log.info('[midnight_reset] catch-up reset (last=%s, today=%s)', last_reset, today)
        _do_reset()

    # ── Then sleep until each midnight ────────────────────────────────────
    while True:
        now = datetime.now()
        midnight = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=5, microsecond=0
        )
        sleep_secs = (midnight - now).total_seconds()
        log.info('[midnight_reset] next midnight reset in %.0f seconds', sleep_secs)
        time.sleep(sleep_secs)
        _do_reset()


# ── Kill switch ───────────────────────────────────────────────────────────────
def _do_kill_switch(remove_from_startup: bool):
    """
    Stops all monitoring, optionally removes from Windows startup, then exits.
    Called only after password has been verified.
    """
    import tkinter as tk
    from tkinter import messagebox

    # 1. Stop all background activity
    timer_mgr.stop()
    url_watcher.stop()
    supabase_sync.stop()

    # 2. Remove from Windows startup registry if requested
    if remove_from_startup:
        remove_startup()

    # 3. Hide the tray icon
    try:
        tray_icon.stop()
    except Exception:
        pass

    # 4. Show confirmation then exit
    root = tk.Tk()
    root.withdraw()
    msg = 'Browser Guardian has been stopped.'
    if remove_from_startup:
        msg += '\nIt will NOT restart on next login.'
    else:
        msg += '\nIt will restart automatically on next login.'
    messagebox.showinfo('Browser Guardian — Stopped', msg)
    root.destroy()

    os._exit(0)


def action_kill_switch(icon, item):
    """Tray menu: Kill Switch — asks for password, then shows options."""
    import tkinter as tk
    from tkinter import ttk, messagebox

    def run():
        root = tk.Tk()
        root.title('Browser Guardian — Kill Switch')
        root.geometry('400x260')
        root.resizable(False, False)
        root.attributes('-topmost', True)
        root.eval('tk::PlaceWindow . center')

        frame = ttk.Frame(root, padding=24)
        frame.pack(fill='both', expand=True)

        ttk.Label(frame, text='Kill Switch', font=('Segoe UI', 13, 'bold'),
                  foreground='#c62828').pack(anchor='w')
        ttk.Label(frame,
                  text='Enter the parent password to stop all monitoring.',
                  font=('Segoe UI', 9), wraplength=340).pack(anchor='w', pady=(4, 12))

        pwd_var = tk.StringVar()
        entry = ttk.Entry(frame, textvariable=pwd_var, show='*',
                          font=('Segoe UI', 12), width=26)
        entry.pack(pady=(0, 8))
        entry.focus_set()

        remove_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frame,
            text='Also remove from Windows startup\n(app will not restart on next login)',
            variable=remove_var,
        ).pack(anchor='w', pady=(0, 12))

        status_var = tk.StringVar()
        ttk.Label(frame, textvariable=status_var,
                  foreground='red', font=('Segoe UI', 9)).pack()

        def confirm():
            if pwd_var.get() == config['password']:
                root.destroy()
                _do_kill_switch(remove_from_startup=remove_var.get())
            else:
                status_var.set('Incorrect password.')
                pwd_var.set('')

        entry.bind('<Return>', lambda _: confirm())
        btn_frame = tk.Frame(frame)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text='Stop Browser Guardian', command=confirm).pack(side='left', padx=6)
        ttk.Button(btn_frame, text='Cancel', command=root.destroy).pack(side='left', padx=6)
        root.protocol('WM_DELETE_WINDOW', root.destroy)
        root.after(100, root.focus_force)
        root.mainloop()

    threading.Thread(target=run, daemon=True).start()


# ── Other tray menu actions ───────────────────────────────────────────────────
def action_status(icon, item):
    def run():
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        startup = 'Yes' if is_registered_at_startup() else 'No'
        messagebox.showinfo(
            'Browser Guardian',
            f'--- Browser ---\n'
            f'State:     {timer_mgr.state}\n'
            f'Remaining: {timer_mgr.get_remaining_str()}\n\n'
            f'--- Roblox ---\n'
            f'State:     {roblox_timer_mgr.state}\n'
            f'Remaining: {roblox_timer_mgr.get_remaining_str()}\n\n'
            f'Run at startup: {startup}'
        )
        root.destroy()
    threading.Thread(target=run, daemon=True).start()


def action_toggle_startup(icon, item):
    def run():
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        if is_registered_at_startup():
            remove_startup()
            messagebox.showinfo('Startup', 'Removed from Windows startup.')
        else:
            register_startup()
            messagebox.showinfo('Startup', 'Added to Windows startup.')
        root.destroy()
    threading.Thread(target=run, daemon=True).start()


def action_settings(icon, item):
    def on_save(new_cfg):
        global config
        config.update(new_cfg)
        save_config(config)

    dialog = SettingsDialog(config, on_save)
    threading.Thread(target=dialog.show, daemon=True).start()


# ── Tray setup ────────────────────────────────────────────────────────────────
def on_tray_ready(icon):
    icon.visible = True
    init_db()
    threading.Thread(target=_browser_watch_loop,   daemon=True).start()
    threading.Thread(target=_roblox_watch_loop,    daemon=True).start()
    threading.Thread(target=_history_sync_loop,    daemon=True).start()
    threading.Thread(target=_midnight_reset_loop,  daemon=True).start()
    url_watcher.start()
    supabase_sync.start()


# ── Boot ──────────────────────────────────────────────────────────────────────
timer_mgr        = TimerManager(_on_timer_expired,        lambda: config, timer_key='timer_minutes')
roblox_timer_mgr = TimerManager(_on_roblox_timer_expired, lambda: config, timer_key='roblox_timer_minutes')

menu = pystray.Menu(
    pystray.MenuItem('Status / Time Remaining', action_status),
    pystray.MenuItem('Settings',                action_settings),
    pystray.MenuItem(
        lambda item: 'Disable Startup' if is_registered_at_startup() else 'Enable Startup',
        action_toggle_startup,
    ),
    pystray.Menu.SEPARATOR,
    pystray.MenuItem('Kill Switch (Stop Everything)', action_kill_switch),
)

tray_icon = pystray.Icon(
    name='BrowserGuardian',
    icon=_make_icon('green'),
    title='Browser Guardian',
    menu=menu,
)

tray_icon.run(on_tray_ready)
