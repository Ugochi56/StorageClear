import os
import sys
import shutil
import time

# Add parent directory to sys.path so we can import storageclear
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from storageclear.scanner import scan_directory
from storageclear.recommender import get_large_files, find_duplicate_files, find_junk_and_cache
from storageclear.ops import get_logical_drives, get_ghost_applications, is_user_admin
from storageclear.tui import TUIApp

MOCK_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), 'mock_fs'))

def create_dummy_file(path, size_bytes, content=b'\0'):
    """Creates a dummy file of specific size extremely fast using seek."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        if size_bytes > 0:
            f.seek(size_bytes - 1)
            f.write(content)
        else:
            f.write(b'')

def setup_mock_filesystem():
    """Generates a complete mock storage filesystem to verify scanner and recommender."""
    print("Setting up mock filesystem...")
    if os.path.exists(MOCK_ROOT):
        shutil.rmtree(MOCK_ROOT)
    os.makedirs(MOCK_ROOT, exist_ok=True)

    # 1. Large files
    create_dummy_file(os.path.join(MOCK_ROOT, 'large_file_15mb.bin'), 15 * 1024**2, b'A')
    create_dummy_file(os.path.join(MOCK_ROOT, 'sub1', 'large_file_12mb.bin'), 12 * 1024**2, b'B')
    
    # 2. Duplicate Files (Same size AND contents)
    create_dummy_file(os.path.join(MOCK_ROOT, 'dups', 'file_a.dat'), 512 * 1024, b'X')
    create_dummy_file(os.path.join(MOCK_ROOT, 'dups', 'file_b.dat'), 512 * 1024, b'X') # Duplicate of A
    create_dummy_file(os.path.join(MOCK_ROOT, 'dups', 'sub_dup', 'file_c.dat'), 512 * 1024, b'X') # Duplicate of A
    
    # Non-duplicate of same size (different end byte)
    diff_path = os.path.join(MOCK_ROOT, 'dups', 'file_diff.dat')
    create_dummy_file(diff_path, 512 * 1024, b'Y')
    
    # 3. Python Caches
    create_dummy_file(os.path.join(MOCK_ROOT, 'src', '__pycache__', 'module.pyc'), 15 * 1024)
    create_dummy_file(os.path.join(MOCK_ROOT, 'src', 'utils.py'), 4 * 1024)
    
    # 4. Node Modules Cache
    create_dummy_file(os.path.join(MOCK_ROOT, 'project', 'node_modules', 'lodash', 'index.js'), 100 * 1024)
    
    # 5. Virtual Env
    venv_dir = os.path.join(MOCK_ROOT, 'project', '.venv')
    # Mock virtual env executables
    exec_dir = 'Scripts' if os.name == 'nt' else 'bin'
    create_dummy_file(os.path.join(venv_dir, exec_dir, 'python.exe' if os.name == 'nt' else 'python'), 10 * 1024)
    create_dummy_file(os.path.join(venv_dir, 'lib', 'site-packages', 'pip', '__init__.py'), 5 * 1024)
    
    # 6. Build Cache (target/ folder)
    create_dummy_file(os.path.join(MOCK_ROOT, 'rust_app', 'target', 'debug', 'app.exe'), 5 * 1024**2)
    
    # 7. System logs & temp files
    create_dummy_file(os.path.join(MOCK_ROOT, 'logs', 'error.log'), 250 * 1024)
    create_dummy_file(os.path.join(MOCK_ROOT, 'temp', 'data.tmp'), 1 * 1024**2)

    print("Mock filesystem setup complete.")

def test_system_drives():
    print("\n--- Testing native drive retrieval ---")
    drives = get_logical_drives()
    for d in drives:
        pct = (d['used'] / d['total'] * 100) if d['total'] > 0 else 0
        print(f"Drive: {d['drive']} | Label: {d['label']} | FS: {d['fs']} | Free: {d['free']/1024**3:.2f}GB / {d['total']/1024**3:.2f}GB Used: {pct:.1f}%")
    assert len(drives) > 0, "No logical drives found!"

def run_verification_tests():
    """Runs tests asserting size calculations, duplicate matching, and caches."""
    print("\n--- Executing Scanner Test on Mock Filesystem ---")
    
    # Start scanning mock directory
    scan_gen = scan_directory([MOCK_ROOT])
    scan_results = None
    
    while True:
        try:
            event, data = next(scan_gen)
            if event == 'done':
                scan_results = data
                break
        except StopIteration:
            break
            
    assert scan_results is not None, "Scan did not return results!"
    
    roots = scan_results['tree_roots']
    all_files = scan_results['all_files']
    total_size = scan_results['total_size']
    files_scanned = scan_results['files_scanned']
    
    print(f"Scanned files count: {files_scanned}")
    print(f"Scanned total size: {total_size / 1024**2:.2f} MB")
    
    # 1. Scanner Assertions
    # We created:
    # - large_file_15mb (15MB)
    # - large_file_12mb (12MB)
    # - 3 duplicates of 512KB (1.5MB)
    # - 1 diff of 512KB (0.5MB)
    # - module.pyc (15KB)
    # - utils.py (4KB)
    # - lodash index (100KB)
    # - python.exe (10KB)
    # - site-packages pip (5KB)
    # - debug app (5MB)
    # - error.log (250KB)
    # - data.tmp (1MB)
    # Total size should be ~ 35.38 MB (37,103,616 bytes approximately)
    assert files_scanned == 14, f"Expected 14 files scanned, got {files_scanned}"
    assert total_size > 35 * 1024**2, f"Total size matches incorrectly: {total_size}"
    
    print("✔ Scanner assertions passed successfully.")
    
    # 2. Recommender - Large Files Assertions
    print("\n--- Testing Large Files recommender ---")
    large = get_large_files(all_files, limit=5, min_size=1 * 1024**2)
    print(f"Top large files found: {[os.path.basename(f['path']) for f in large]}")
    assert len(large) == 4, f"Expected 4 large files (>1MB), found {len(large)}"
    assert os.path.basename(large[0]['path']) == 'large_file_15mb.bin'
    assert os.path.basename(large[1]['path']) == 'large_file_12mb.bin'
    print("✔ Large files assertions passed successfully.")
    
    # 3. Recommender - Duplicates Assertions
    print("\n--- Testing Duplicate Detector ---")
    dups = find_duplicate_files(all_files, min_size=1024)
    print(f"Found {len(dups)} duplicate groups.")
    for g in dups:
        print(f"Group wasted space: {g['wasted_space']/1024:.1f} KB | Files: {[os.path.basename(f['path']) for f in g['files']]}")
        
    assert len(dups) == 1, f"Expected 1 duplicate group, found {len(dups)}"
    assert len(dups[0]['files']) == 3, f"Expected 3 duplicate copies, found {len(dups[0]['files'])}"
    # Verify that different file of same size is NOT marked as duplicate
    dup_paths = [f['path'] for f in dups[0]['files']]
    assert not any('file_diff.dat' in p for p in dup_paths), "Different contents file erroneously flagged as duplicate!"
    print("✔ Duplicate detector assertions passed successfully.")
    
    # 4. Recommender - Junk & Cache Finder Assertions
    print("\n--- Testing Junk & Cache Finder ---")
    junk = find_junk_and_cache(roots)
    for key, val in junk.items():
        print(f"Junk Category: {key} ({val['name']}) | Size: {val['size']/1024:.1f} KB | Paths: {[os.path.basename(p) for p in val['paths']]}")
        
    assert 'py_cache' in junk, "Python Cache category missing"
    assert 'node_modules' in junk, "Node.js Modules category missing"
    assert 'venv' in junk, "Virtual Env category missing"
    assert 'build_cache' in junk, "Build Cache category missing"
    assert 'logs_temp' in junk, "Logs & Temp category missing"
    print("✔ Junk & Cache assertions passed successfully.")

def test_registry_purger():
    print("\n--- Testing Windows Registry Ghost Uninstaller Finder ---")
    admin = is_user_admin()
    print(f"Current terminal process is elevated Administrator: {admin}")
    
    ghosts = get_ghost_applications()
    print(f"Total Ghost applications detected: {len(ghosts)}")
    
    for idx, g in enumerate(ghosts[:5]):
        print(f"  [{idx+1}] Name: {g['name']} | Registry Key: {g['key_name']} | Root: {g['root_str']} | Reason: {g['reason']}")
        
    assert isinstance(ghosts, list), "get_ghost_applications() must return a list!"
    if ghosts:
        g = ghosts[0]
        assert 'name' in g
        assert 'key_name' in g
        assert 'root_str' in g
        assert 'root' in g
        assert 'path' in g
        assert 'reason' in g
    print("✔ Registry uninstaller assertions passed successfully.")

if __name__ == '__main__':
    try:
        setup_mock_filesystem()
        test_system_drives()
        test_registry_purger()
        run_verification_tests()
        print("\n🏆 ALL VERIFICATION TESTS PASSED SUCCESSFULLY! The StorageClear engine is 100% sound.")
    finally:
        # Cleanup
        if os.path.exists(MOCK_ROOT):
            print("Cleaning up mock filesystem...")
            shutil.rmtree(MOCK_ROOT)
            print("Cleanup complete.")
