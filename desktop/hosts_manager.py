"""
Manages the Windows hosts file for DNS-level adult content blocking.
Requires admin rights (run install via install.bat which self-elevates).
"""
import os
import shutil
import logging
from datetime import datetime

log = logging.getLogger(__name__)

HOSTS_FILE = r'C:\Windows\System32\drivers\etc\hosts'
BACKUP_FILE = r'C:\Windows\System32\drivers\etc\hosts.bg_backup'

# Official SafeSearch enforcement IPs (Google/Bing/YouTube redirect to these)
_SAFE_SEARCH_ENTRIES = [
    '216.239.38.120 www.google.com',
    '216.239.38.120 google.com',
    '204.79.197.220 www.bing.com',
    '204.79.197.220 bing.com',
    '216.239.38.120 www.youtube.com',
    '216.239.38.120 youtube.com',
]

_MARKER_START = '# BEGIN browser_guardian_block'
_MARKER_END = '# END browser_guardian_block'


def backup():
    """Backup hosts file once — does not overwrite an existing backup."""
    if os.path.exists(BACKUP_FILE):
        return
    try:
        shutil.copy2(HOSTS_FILE, BACKUP_FILE)
        log.info('[hosts] backup saved to %s', BACKUP_FILE)
    except Exception as e:
        log.error('[hosts] backup failed: %s', e)
        raise


def restore():
    """Restore original hosts file from backup."""
    if not os.path.exists(BACKUP_FILE):
        log.warning('[hosts] no backup found — cannot restore')
        return False
    try:
        shutil.copy2(BACKUP_FILE, HOSTS_FILE)
        os.remove(BACKUP_FILE)
        log.info('[hosts] restored from backup')
        return True
    except Exception as e:
        log.error('[hosts] restore failed: %s', e)
        return False


def _read_hosts() -> str:
    with open(HOSTS_FILE, 'r', encoding='utf-8', errors='replace') as f:
        return f.read()


def _write_hosts(content: str):
    with open(HOSTS_FILE, 'w', encoding='utf-8') as f:
        f.write(content)


def _strip_our_block(content: str) -> str:
    lines = content.splitlines(keepends=True)
    out, in_block = [], False
    for line in lines:
        if _MARKER_START in line:
            in_block = True
        elif _MARKER_END in line:
            in_block = False
        elif not in_block:
            out.append(line)
    return ''.join(out)


def install(blocklist_path: str):
    """
    Install SafeSearch + blocklist entries into the system hosts file.
    blocklist_path: text file with one domain per line (# = comment).
    """
    backup()

    domains = []
    try:
        with open(blocklist_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    domains.append(line.lower())
    except Exception as e:
        log.warning('[hosts] could not load blocklist: %s', e)

    block = [f'\n{_MARKER_START} (added {datetime.now().strftime("%Y-%m-%d")})\n']
    for entry in _SAFE_SEARCH_ENTRIES:
        block.append(f'{entry}\n')
    for domain in domains:
        d = domain.lstrip('www.')
        block.append(f'0.0.0.0 {d}\n')
        block.append(f'0.0.0.0 www.{d}\n')
    block.append(f'{_MARKER_END}\n')

    content = _strip_our_block(_read_hosts())
    _write_hosts(content + ''.join(block))
    log.info('[hosts] installed %d SafeSearch + %d blocked domains',
             len(_SAFE_SEARCH_ENTRIES), len(domains))


def uninstall():
    """Remove browser_guardian block from hosts (restores backup if available)."""
    if os.path.exists(BACKUP_FILE):
        restore()
        return
    try:
        _write_hosts(_strip_our_block(_read_hosts()))
        log.info('[hosts] removed block from hosts file')
    except Exception as e:
        log.error('[hosts] uninstall failed: %s', e)


def is_installed() -> bool:
    """Return True if our block is currently in the hosts file."""
    try:
        return _MARKER_START in _read_hosts()
    except Exception:
        return False
