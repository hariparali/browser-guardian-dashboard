import tkinter as tk
from tkinter import ttk


class MessageDialog:
    """
    Always-on-top popup that displays a message from the parent.
    Kid must click OK to dismiss it.
    """

    def __init__(self, message):
        self._message = message

    def show(self):
        root = tk.Tk()
        root.title('Message from Parent')
        root.geometry('460x220')
        root.resizable(False, False)
        root.attributes('-topmost', True)
        root.eval('tk::PlaceWindow . center')
        root.protocol('WM_DELETE_WINDOW', root.destroy)

        frame = ttk.Frame(root, padding=28)
        frame.pack(fill='both', expand=True)

        ttk.Label(
            frame,
            text='📬 Message from Parent',
            font=('Segoe UI', 11, 'bold'),
            foreground='#1a237e',
        ).pack(anchor='w', pady=(0, 12))

        ttk.Label(
            frame,
            text=self._message,
            font=('Segoe UI', 13),
            wraplength=400,
            foreground='#2c2c3a',
            justify='left',
        ).pack(anchor='w', pady=(0, 20))

        ttk.Button(frame, text='OK', width=12, command=root.destroy).pack()

        root.after(100, root.focus_force)
        root.mainloop()
