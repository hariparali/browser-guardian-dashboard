"""Helper script called by install.bat to install hosts file blocking."""
import sys
sys.path.insert(0, __import__('os').path.dirname(__file__))
from hosts_manager import install
if len(sys.argv) < 2:
    print('Usage: run_hosts_install.py <blocklist.txt>')
    sys.exit(1)
install(sys.argv[1])
print('Hosts file updated successfully.')
