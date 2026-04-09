import json
import os
import sys

# When frozen by PyInstaller, write config next to the .exe, not in the temp bundle dir
if getattr(sys, 'frozen', False):
    _BASE = os.path.dirname(sys.executable)
else:
    _BASE = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(_BASE, 'config.json')

DEFAULT_CONFIG = {
    'timer_minutes': 30,
    'password': 'parent123',
    'auto_close_seconds': 30,
    'supabase_url': '',
    'supabase_key': '',
    'gemini_api_key': '',
}


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
        for key, val in DEFAULT_CONFIG.items():
            if key not in config:
                config[key] = val
        return config
    return DEFAULT_CONFIG.copy()


def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)
