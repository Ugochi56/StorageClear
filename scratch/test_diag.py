import sys
import os

# Adjust paths to import package correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from storageclear.ops import get_startup_applications, get_memory_status

def test_diagnostics():
    print("=== Testing System physical/virtual Memory ctypes queries ===")
    mem = get_memory_status()
    print(f"RAM Load Percentage: {mem['ram_load']}%")
    print(f"Total Physical RAM:  {mem['total_phys'] / (1024**3):.2f} GB")
    print(f"Available RAM:       {mem['avail_phys'] / (1024**3):.2f} GB")
    print(f"Total Pagefile Size: {mem['total_page'] / (1024**3):.2f} GB")
    print(f"Available Pagefile:  {mem['avail_page'] / (1024**3):.2f} GB")
    
    print("\n=== Testing Startup Registry Applications enumerator ===")
    apps = get_startup_applications()
    print(f"Total detected Startup Keys: {len(apps)}")
    for i, app in enumerate(apps[:5]):
         print(f"[{i+1}] Name: {app['name']}")
         print(f"    Hive: {app['root']}")
         print(f"    Cmd:  {app['command']}")
    if len(apps) > 5:
         print(f"... and {len(apps) - 5} more.")

if __name__ == "__main__":
    test_diagnostics()
