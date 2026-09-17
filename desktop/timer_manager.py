"""
Timer that counts down only while the browser is running.
States: IDLE → RUNNING → PAUSED → EXPIRED
A new session only starts when explicitly called (parent entered password).
"""
import threading


class TimerState:
    IDLE    = 'idle'
    RUNNING = 'running'
    PAUSED  = 'paused'
    EXPIRED = 'expired'


class TimerManager:

    def __init__(self, on_expired, get_config, timer_key='timer_minutes'):
        self._on_expired = on_expired
        self._get_config = get_config
        self._timer_key  = timer_key
        self._remaining = 0
        self._state = TimerState.IDLE
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        # When the tick thread exits into EXPIRED it normally fires on_expired
        # (the warning-then-kill flow). A remote force_block() does the kill
        # itself, so it suppresses that callback to avoid a spurious warning.
        self._fire_expired_cb = True

    # ── Public API ────────────────────────────────────────────────────────
    def start_new_session(self):
        """Start a brand-new session (called only when parent enters password)."""
        with self._lock:
            self._stop_event.set()          # stop any existing tick thread
        self._stop_event.wait(timeout=0.3)
        with self._lock:
            self._remaining = self._get_config()[self._timer_key] * 60
            self._state = TimerState.RUNNING
            self._fire_expired_cb = True
            self._stop_event.clear()
            threading.Thread(target=self._tick, daemon=True).start()

    def pause(self):
        """Pause the countdown (browser closed)."""
        with self._lock:
            if self._state == TimerState.RUNNING:
                self._state = TimerState.PAUSED
                self._stop_event.set()

    def resume(self):
        """Resume the countdown (browser reopened, time still remaining)."""
        with self._lock:
            if self._state == TimerState.PAUSED and self._remaining > 0:
                self._state = TimerState.RUNNING
                self._fire_expired_cb = True
                self._stop_event.clear()
                threading.Thread(target=self._tick, daemon=True).start()

    def add_time(self, seconds):
        """Add extra seconds to the current session (remote extend)."""
        with self._lock:
            if self._state in (TimerState.RUNNING, TimerState.PAUSED,
                               TimerState.EXPIRED):
                self._remaining += seconds
                if self._state == TimerState.EXPIRED:
                    # Will resume next time the app opens
                    self._state = TimerState.PAUSED

    def force_block(self):
        """Immediately expire the timer to zero (remote block command).

        Suppresses the on_expired callback — the remote-block handler performs
        its own kill/lock, so we must not also fire the natural-expiry warning.
        """
        with self._lock:
            self._fire_expired_cb = False
            self._stop_event.set()
            self._remaining = 0
            self._state = TimerState.EXPIRED

    def restore_state(self, state, remaining):
        """Restore persisted time on startup so a reboot can't hand out a fresh
        allowance. No tick is started here — the watch loop resumes ticking once
        it detects the app running (or the reopen/enforce path fires if expired).

        IDLE is preserved as-is (a not-yet-started day still gets its full
        allowance on first open) — importantly we do NOT treat IDLE's remaining=0
        as "expired".
        """
        with self._lock:
            self._stop_event.set()
            if state == TimerState.EXPIRED:
                self._remaining = 0
                self._state = TimerState.EXPIRED
            elif state in (TimerState.RUNNING, TimerState.PAUSED) and remaining > 0:
                self._remaining = remaining
                self._state = TimerState.PAUSED
            else:
                # IDLE or unknown → leave a fresh allowance for the first open.
                self._remaining = 0
                self._state = TimerState.IDLE

    def reset_to_idle(self):
        """Reset to full daily allowance, state=IDLE (nightly reset)."""
        with self._lock:
            self._stop_event.set()
        self._stop_event.wait(timeout=0.3)
        with self._lock:
            self._remaining = self._get_config()[self._timer_key] * 60
            self._state = TimerState.IDLE
            self._stop_event.clear()

    def stop(self):
        """Stop and reset to idle (app quitting)."""
        with self._lock:
            self._state = TimerState.IDLE
            self._stop_event.set()

    # ── Queries ───────────────────────────────────────────────────────────
    @property
    def state(self):
        return self._state

    def is_expired(self):
        return self._state == TimerState.EXPIRED

    def has_time(self):
        return self._remaining > 0 and self._state not in (
            TimerState.EXPIRED, TimerState.IDLE
        )

    def get_remaining(self):
        return max(0, self._remaining)

    def get_remaining_str(self):
        secs = self.get_remaining()
        m, s = divmod(secs, 60)
        state_label = {
            TimerState.PAUSED:  ' (paused)',
            TimerState.EXPIRED: ' (expired)',
            TimerState.IDLE:    ' (not started)',
        }.get(self._state, '')
        return f'{m:02d}:{s:02d}{state_label}'

    # ── Internal tick ─────────────────────────────────────────────────────
    def _tick(self):
        while not self._stop_event.wait(1):
            with self._lock:
                if self._state != TimerState.RUNNING:
                    break
                self._remaining -= 1
                if self._remaining <= 0:
                    self._remaining = 0
                    self._state = TimerState.EXPIRED
                    break
        # Fire callback outside the lock
        if self._state == TimerState.EXPIRED:
            self._on_expired()
