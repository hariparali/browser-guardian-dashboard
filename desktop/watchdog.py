"""
Browser Guardian Watchdog
Runs as a separate process (scheduled task, ONLOGON for son's account).
Checks every 2 seconds if BrowserGuardian.exe is running; restarts it if not.
"""
import os
import sys
import time
import logging
import subprocess

if getattr(sys, 'frozen', False):
    _BASE = os.path.dirname(sys.executable)
else:
    _BASE = os.path.dirname(os.path.abspath(__file__))

logging.basicConfig(
    filename=os.path.join(_BASE, 'watchdog.log'),
    level=logging.INFO,
    format='%(asctime)s [watchdog] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
log = logging.getLogger(__name__)

_EXE_NAME = 'BrowserGuardian.exe'
_EXE_PATH = os.path.join(_BASE, _EXE_NAME)


def _is_running() -> bool:
    try:
        result = subprocess.run(
            ['tasklist', '/FI', f'IMAGENAME eq {_EXE_NAME}'],
            capture_output=True, text=True, timeout=5,
        )
        return _EXE_NAME.lower() in result.stdout.lower()
    except Exception:
        return False


def _start():
    try:
        subprocess.Popen(
            [_EXE_PATH],
            creationflags=0x00000008,  # DETACHED_PROCESS
        )
        log.info('restarted %s', _EXE_NAME)
    except Exception as e:
        log.error('failed to restart: %s', e)


def main():
    log.info('watchdog started — monitoring %s', _EXE_PATH)
    if not os.path.exists(_EXE_PATH):
        log.error('EXE not found at %s — watchdog exiting', _EXE_PATH)
        return
    while True:
        if not _is_running():
            log.warning('%s not running — restarting', _EXE_NAME)
            _start()
        time.sleep(2)


if __name__ == '__main__':
    main()
