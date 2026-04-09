# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Browser Guardian.
Run:  pyinstaller browser_guardian.spec
Output: dist\BrowserGuardian\BrowserGuardian.exe
"""

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[
        'pystray._win32',
        'PIL._tkinter_finder',
        'uiautomation',
        'uiautomation.uiautomation',
        'tkinter',
        'tkinter.ttk',
        'tkinter.messagebox',
        'win32com.client',
        'win32con',
        'comtypes',
        'comtypes.client',
        'psutil',
        'requests',
        'sqlite3',
        'winreg',
        'json',
        'threading',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BrowserGuardian',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,        # No terminal window — same as pythonw.exe
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='BrowserGuardian',
)
