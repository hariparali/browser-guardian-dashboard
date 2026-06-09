"""Helper script called by uninstall.bat to restore hosts file."""
import sys
sys.path.insert(0, __import__('os').path.dirname(__file__))
from hosts_manager import uninstall
uninstall()
print('Hosts file restored.')
