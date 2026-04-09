import tkinter as tk
from tkinter import ttk, messagebox


class SettingsDialog:
    """Settings window for configuring timer, password, and Supabase credentials."""

    def __init__(self, config, on_save):
        self._config = config.copy()
        self._on_save = on_save

    def show(self):
        root = tk.Tk()
        root.title('Browser Guardian — Settings')
        root.geometry('460x360')
        root.resizable(False, False)
        root.attributes('-topmost', True)
        root.eval('tk::PlaceWindow . center')

        frame = ttk.Frame(root, padding=24)
        frame.pack(fill='both', expand=True)

        ttk.Label(frame, text='Settings', font=('Segoe UI', 13, 'bold')).grid(
            row=0, column=0, columnspan=2, pady=(0, 16), sticky='w'
        )

        def row(label, widget_factory, r):
            ttk.Label(frame, text=label).grid(row=r, column=0, sticky='w', pady=6, padx=(0, 12))
            w = widget_factory(frame)
            w.grid(row=r, column=1, sticky='w')
            return w

        timer_var = tk.IntVar(value=self._config.get('timer_minutes', 30))
        row('Session timer (minutes):', lambda f: ttk.Spinbox(f, from_=1, to=180,
            textvariable=timer_var, width=8), 1)

        close_var = tk.IntVar(value=self._config.get('auto_close_seconds', 30))
        row('Auto-close delay (seconds):', lambda f: ttk.Spinbox(f, from_=5, to=120,
            textvariable=close_var, width=8), 2)

        pwd_var = tk.StringVar(value=self._config.get('password', ''))
        row('Parent password:', lambda f: ttk.Entry(f, textvariable=pwd_var,
            show='*', width=22), 3)

        surl_var = tk.StringVar(value=self._config.get('supabase_url', ''))
        row('Supabase URL:', lambda f: ttk.Entry(f, textvariable=surl_var, width=34), 4)

        skey_var = tk.StringVar(value=self._config.get('supabase_key', ''))
        row('Supabase Anon Key:', lambda f: ttk.Entry(f, textvariable=skey_var,
            show='*', width=34), 5)

        gkey_var = tk.StringVar(value=self._config.get('gemini_api_key', ''))
        row('Gemini API Key (free):', lambda f: ttk.Entry(f, textvariable=gkey_var,
            show='*', width=34), 6)

        def save():
            if not pwd_var.get().strip():
                messagebox.showerror('Error', 'Password cannot be empty.')
                return
            self._on_save({
                'timer_minutes': timer_var.get(),
                'auto_close_seconds': close_var.get(),
                'password': pwd_var.get(),
                'supabase_url': surl_var.get().strip(),
                'supabase_key': skey_var.get().strip(),
                'gemini_api_key': gkey_var.get().strip(),
            })
            messagebox.showinfo('Saved', 'Settings saved successfully!')
            root.destroy()

        ttk.Button(frame, text='Save Settings', command=save).grid(
            row=7, column=0, pady=18
        )
        ttk.Button(frame, text='Cancel', command=root.destroy).grid(
            row=7, column=1, pady=18
        )
        root.protocol('WM_DELETE_WINDOW', root.destroy)
        root.after(100, root.focus_force)
        root.mainloop()
