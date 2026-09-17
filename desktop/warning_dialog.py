import tkinter as tk
from tkinter import ttk


class WarningDialog:
    """
    Non-dismissible countdown shown BEFORE Roblox is force-closed, so the child
    can save their progress. No password, no early close — it just counts down
    from `countdown_secs` and then closes itself (the parent process does the
    actual kill once this window exits).
    """

    def __init__(self, countdown_secs=60, subject='Roblox'):
        self._total = countdown_secs
        self._remaining = countdown_secs
        self._subject = subject
        self._after_id = None
        self.root = None

    def show(self):
        self.root = tk.Tk()
        self.root.title(f'{self._subject} — Time is up')
        self.root.geometry('460x230')
        self.root.resizable(False, False)
        self.root.attributes('-topmost', True)
        # Block the close button — the child cannot dismiss this early.
        self.root.protocol('WM_DELETE_WINDOW', lambda: None)
        self.root.eval('tk::PlaceWindow . center')

        frame = ttk.Frame(self.root, padding=24)
        frame.pack(fill='both', expand=True)

        ttk.Label(
            frame, text=f'⏰  {self._subject} time is over for today',
            font=('Segoe UI', 14, 'bold'), foreground='#c62828',
        ).pack(pady=(0, 8))

        ttk.Label(
            frame,
            text='Please save your progress now. It will close automatically:',
            font=('Segoe UI', 10), wraplength=400, justify='center',
        ).pack()

        self._countdown_var = tk.StringVar()
        ttk.Label(
            frame, textvariable=self._countdown_var,
            font=('Segoe UI', 32, 'bold'), foreground='#1565c0',
        ).pack(pady=12)

        ttk.Label(
            frame, text='A parent can grant more time from the Browser Guardian tray.',
            font=('Segoe UI', 8), foreground='#888', wraplength=400, justify='center',
        ).pack()

        self._tick()
        self.root.after(100, self.root.focus_force)
        self.root.mainloop()

    def _tick(self):
        m, s = divmod(max(0, self._remaining), 60)
        self._countdown_var.set(f'{m:01d}:{s:02d}')
        if self._remaining <= 0:
            try:
                self.root.destroy()
            except Exception:
                pass
            return
        self._remaining -= 1
        self._after_id = self.root.after(1000, self._tick)
