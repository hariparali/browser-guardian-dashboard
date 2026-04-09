import tkinter as tk
from tkinter import ttk


class PasswordDialog:
    """
    Modal dialog shown when the session timer expires.
    Counts down from countdown_secs; closes browser on timeout.
    """

    def __init__(self, countdown_secs, on_correct, on_timeout, get_password, subject='Browser'):
        self._countdown_secs = countdown_secs
        self._on_correct = on_correct
        self._on_timeout = on_timeout
        self._get_password = get_password
        self._subject = subject
        self._remaining = countdown_secs
        self._after_id = None
        self.root = None

    def show(self):
        self.root = tk.Tk()
        self.root.title(f'{self._subject} Time Limit Reached')
        self.root.geometry('420x230')
        self.root.resizable(False, False)
        self.root.attributes('-topmost', True)
        self.root.protocol('WM_DELETE_WINDOW', self._timeout)
        # Center on screen
        self.root.eval('tk::PlaceWindow . center')

        frame = ttk.Frame(self.root, padding=24)
        frame.pack(fill='both', expand=True)

        ttk.Label(
            frame, text=f'{self._subject} Time Limit Reached!',
            font=('Segoe UI', 13, 'bold')
        ).pack(pady=(0, 6))

        ttk.Label(
            frame, text='Enter the parent password to continue for 30 more minutes:',
            font=('Segoe UI', 10), wraplength=360
        ).pack()

        self._pwd_var = tk.StringVar()
        entry = ttk.Entry(frame, textvariable=self._pwd_var, show='*',
                          font=('Segoe UI', 12), width=24)
        entry.pack(pady=10)
        entry.focus_set()
        entry.bind('<Return>', lambda _: self._check())

        self._status_var = tk.StringVar()
        ttk.Label(frame, textvariable=self._status_var,
                  foreground='red', font=('Segoe UI', 9)).pack()

        self._countdown_var = tk.StringVar()
        ttk.Label(frame, textvariable=self._countdown_var,
                  foreground='#888', font=('Segoe UI', 9)).pack()

        ttk.Button(frame, text='Unlock (30 more minutes)',
                   command=self._check).pack(pady=10)

        self._tick()
        self.root.after(100, self.root.focus_force)
        self.root.mainloop()

    def _tick(self):
        self._countdown_var.set(
            f'Browser will close automatically in {self._remaining}s'
        )
        if self._remaining <= 0:
            self._timeout()
            return
        self._remaining -= 1
        self._after_id = self.root.after(1000, self._tick)

    def _check(self):
        if self._pwd_var.get() == self._get_password():
            self._cancel_timer()
            self.root.destroy()
            self._on_correct()
        else:
            self._status_var.set('Incorrect password — try again.')
            self._pwd_var.set('')

    def _timeout(self):
        self._cancel_timer()
        if self.root:
            try:
                self.root.destroy()
            except Exception:
                pass
        self._on_timeout()

    def _cancel_timer(self):
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
