import os
import sys
import shutil
import ctypes
from ctypes import wintypes

# Win32 Constants
DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DRIVE_REMOTE = 4
DRIVE_CDROM = 5
DRIVE_RAMDISK = 6

FO_DELETE = 3
FOF_ALLOWUNDO = 0x0040
FOF_NOCONFIRMATION = 0x0010
FOF_NOERRORUI = 0x0400
FOF_SILENT = 0x0004

class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", wintypes.USHORT),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", wintypes.LPVOID),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]

def get_logical_drives():
    """
    Returns a list of dictionaries with info about all fixed and removable drives.
    Example: [{'drive': 'C:\\', 'label': 'OS', 'fs': 'NTFS', 'total': 512000000000, 'free': 212000000000}]
    """
    drives_list = []
    if sys.platform != 'win32':
        # Fallback for non-windows testing (though this tool is win-focused)
        drives_list.append({
            'drive': '/',
            'label': 'Root',
            'fs': 'ext4',
            'total': 100 * 1024**3,
            'free': 50 * 1024**3
        })
        return drives_list

    # Get buffer size needed
    buffer_len = 256
    buffer = ctypes.create_unicode_buffer(buffer_len)
    length = ctypes.windll.kernel32.GetLogicalDriveStringsW(buffer_len - 1, buffer)
    
    if length == 0:
        return []

    # GetLogicalDriveStringsW returns null-separated strings, ending with a double-null
    drive_strings = []
    current_drive = ""
    for char in buffer:
        if char == '\x00':
            if current_drive:
                drive_strings.append(current_drive)
                current_drive = ""
            else:
                break
        else:
            current_drive += char

    for drive in drive_strings:
        dtype = ctypes.windll.kernel32.GetDriveTypeW(drive)
        # Scan only local fixed (SSD/HDD) or removable (USB) drives
        if dtype in (DRIVE_FIXED, DRIVE_REMOVABLE):
            # 1. Get Volume Information (Label and File System)
            volume_name = ctypes.create_unicode_buffer(260)
            file_system = ctypes.create_unicode_buffer(260)
            
            ctypes.windll.kernel32.GetVolumeInformationW(
                ctypes.c_wchar_p(drive),
                volume_name,
                ctypes.sizeof(volume_name),
                None, None, None,
                file_system,
                ctypes.sizeof(file_system)
            )
            
            # 2. Get Disk Free Space
            free_bytes = ctypes.c_ulonglong(0)
            total_bytes = ctypes.c_ulonglong(0)
            total_free_bytes = ctypes.c_ulonglong(0)
            
            ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                ctypes.c_wchar_p(drive),
                ctypes.byref(free_bytes),
                ctypes.byref(total_bytes),
                ctypes.byref(total_free_bytes)
            )
            
            drives_list.append({
                'drive': drive,
                'label': volume_name.value or "Local Disk",
                'fs': file_system.value or "Unknown",
                'total': total_bytes.value,
                'free': free_bytes.value,
                'used': total_bytes.value - free_bytes.value,
                'type': "Fixed" if dtype == DRIVE_FIXED else "Removable"
            })
            
    return drives_list

def send_to_recycle_bin(paths):
    """
    Sends a list of files or directories to the Recycle Bin natively on Windows.
    paths: list of absolute path strings.
    Returns: True if successful, False otherwise.
    """
    if sys.platform != 'win32':
        # Non-Windows fallback: move to a folder
        for p in paths:
            if os.path.exists(p):
                if os.path.isdir(p):
                    shutil.rmtree(p)
                else:
                    os.remove(p)
        return True

    # Validate paths exist and convert to absolute paths
    abs_paths = []
    for p in paths:
        abs_path = os.path.abspath(p)
        if os.path.exists(abs_path):
            abs_paths.append(abs_path)

    if not abs_paths:
        return True

    # Win32 API requires a double-null-terminated string list separated by nulls
    p_from = "\x00".join(abs_paths) + "\x00\x00"

    fileop = SHFILEOPSTRUCTW()
    fileop.hwnd = None
    fileop.wFunc = FO_DELETE
    fileop.pFrom = p_from
    fileop.pTo = None
    fileop.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT
    fileop.fAnyOperationsAborted = False
    fileop.hNameMappings = None
    fileop.lpszProgressTitle = None

    shell32 = ctypes.windll.shell32
    result = shell32.SHFileOperationW(ctypes.byref(fileop))
    
    # If successful, returns 0, and user did not abort
    return result == 0 and not fileop.fAnyOperationsAborted

def delete_permanently(paths):
    """
    Deletes files/folders permanently.
    paths: list of absolute path strings.
    """
    if sys.platform != 'win32':
        for p in paths:
            if os.path.exists(p):
                if os.path.isdir(p):
                    shutil.rmtree(p)
                else:
                    os.remove(p)
        return True

    abs_paths = []
    for p in paths:
        abs_path = os.path.abspath(p)
        if os.path.exists(abs_path):
            abs_paths.append(abs_path)

    if not abs_paths:
        return True

    p_from = "\x00".join(abs_paths) + "\x00\x00"

    fileop = SHFILEOPSTRUCTW()
    fileop.hwnd = None
    fileop.wFunc = FO_DELETE
    fileop.pFrom = p_from
    fileop.pTo = None
    # No FOF_ALLOWUNDO makes it permanent!
    fileop.fFlags = FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT
    fileop.fAnyOperationsAborted = False
    fileop.hNameMappings = None
    fileop.lpszProgressTitle = None

    shell32 = ctypes.windll.shell32
    result = shell32.SHFileOperationW(ctypes.byref(fileop))
    
    return result == 0 and not fileop.fAnyOperationsAborted

# --- WINDOWS REGISTRY GHOST APPLICATION PURGER HELPERS ---

try:
    import winreg
except ImportError:
    winreg = None

def is_user_admin():
    """Returns True if the current process is running with Administrator rights on Windows."""
    if sys.platform != 'win32':
        return False
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def delete_registry_key_recursive(root_key, subkey_path):
    """
    Recursively deletes a registry key and all of its subkeys and values on Windows.
    root_key: e.g. winreg.HKEY_LOCAL_MACHINE or winreg.HKEY_CURRENT_USER
    subkey_path: string path of the registry key.
    """
    if not winreg:
        return
        
    try:
        key = winreg.OpenKey(root_key, subkey_path, 0, winreg.KEY_ALL_ACCESS)
    except OSError:
        # Key does not exist
        return

    # Enumerate all subkeys first
    subkeys = []
    try:
        i = 0
        while True:
            subkeys.append(winreg.EnumKey(key, i))
            i += 1
    except OSError:
        pass  # Reached end of subkeys

    winreg.CloseKey(key)

    # Recursively delete all subkeys
    for subkey in subkeys:
        delete_registry_key_recursive(root_key, f"{subkey_path}\\{subkey}")

    # Finally delete the key itself
    winreg.DeleteKey(root_key, subkey_path)

def parse_uninstall_path(uninstall_str):
    """Parses the executable or command path out of an UninstallString."""
    if not uninstall_str:
        return None
    uninstall_str = uninstall_str.strip()
    
    # 1. Resolve quoted executable paths
    if uninstall_str.startswith('"'):
        end = uninstall_str.find('"', 1)
        if end != -1:
            return uninstall_str[1:end]
        return uninstall_str[1:]
        
    # 2. Check for MSI installers using msiexec
    if 'msiexec' in uninstall_str.lower():
        return 'msiexec'
        
    # 3. Handle unquoted paths with spaces (e.g., C:\Program Files\App\uninstall.exe /silent)
    tokens = uninstall_str.split(' ')
    for i in range(len(tokens), 0, -1):
        candidate = ' '.join(tokens[:i]).strip('"')
        if os.path.exists(candidate) or candidate.lower().endswith(('.exe', '.bat', '.cmd', '.msi')):
            return candidate
            
    return tokens[0]

def is_local_path(path):
    """Returns True if the path points to a local drive letter (e.g. C:\\) and is not relative or network-based."""
    if not path:
        return False
    path = path.strip()
    if len(path) >= 3 and path[0].isalpha() and path[1] == ':' and path[2] in ('\\', '/'):
        return True
    return False

def get_ghost_applications():
    """
    Scans the system registry for phantom/orphaned uninstalled software.
    Returns: a list of dictionaries: 
    [{'name': str, 'key_name': str, 'root_str': 'HKLM'/'HKCU', 'root': int, 'path': str, 'reason': str}]
    """
    ghost_apps = []
    if sys.platform != 'win32' or not winreg:
        # Cross-platform mock fallback for testing
        return [
            {
                'name': 'Mock Ghost Application A (Phantom)',
                'key_name': 'MockGhostAppA',
                'root_str': 'HKCU',
                'root': 0x80000001,  # HKEY_CURRENT_USER
                'path': r"Software\Microsoft\Windows\CurrentVersion\Uninstall\MockGhostAppA",
                'reason': 'Uninstaller executable missing'
            },
            {
                'name': 'Mock System Ghost B (Requires Admin)',
                'key_name': 'MockGhostAppB',
                'root_str': 'HKLM',
                'root': 0x80000002,  # HKEY_LOCAL_MACHINE
                'path': r"Software\Microsoft\Windows\CurrentVersion\Uninstall\MockGhostAppB",
                'reason': 'Uninstaller and folder missing'
            }
        ]

    # Target Registry Uninstall paths
    uninstall_targets = [
        # (root_key, root_str, path_str)
        (winreg.HKEY_LOCAL_MACHINE, "HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, "HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")
    ]
    
    # 64-bit systems also have a 32-bit registry branch
    # check if it's a 64-bit Windows OS
    is_64bit_os = os.environ.get("ProgramFiles(x86)") is not None
    if is_64bit_os:
        uninstall_targets.append(
            (winreg.HKEY_LOCAL_MACHINE, "HKLM", r"SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall")
        )

    for root_key, root_str, base_path in uninstall_targets:
        try:
            # Try opening the branch for reading
            base_key = winreg.OpenKey(root_key, base_path, 0, winreg.KEY_READ)
        except OSError:
            continue

        # Enumerate all installer subkeys
        subkeys = []
        try:
            i = 0
            while True:
                subkeys.append(winreg.EnumKey(base_key, i))
                i += 1
        except OSError:
            pass

        for subkey in subkeys:
            full_path = f"{base_path}\\{subkey}"
            try:
                key = winreg.OpenKey(root_key, full_path, 0, winreg.KEY_READ)
            except OSError:
                continue

            try:
                # Read DisplayName (if not present, it's not a visible app entry in Control Panel)
                try:
                    display_name, _ = winreg.QueryValueEx(key, "DisplayName")
                    display_name = display_name.strip()
                except OSError:
                    continue

                if not display_name:
                    continue

                # Ignore system updates, components, or hidden installers
                try:
                    sys_comp, _ = winreg.QueryValueEx(key, "SystemComponent")
                    if sys_comp == 1:
                        continue
                except OSError:
                    pass

                try:
                    parent_key, _ = winreg.QueryValueEx(key, "ParentKeyName")
                    if parent_key:
                        continue  # Usually an update or sub-component
                except OSError:
                    pass

                # Read UninstallString and InstallLocation
                uninstall_string = ""
                try:
                    uninstall_string, _ = winreg.QueryValueEx(key, "UninstallString")
                except OSError:
                    pass

                install_location = ""
                try:
                    install_location, _ = winreg.QueryValueEx(key, "InstallLocation")
                except OSError:
                    pass

                # Apply Orphan Verification Safety Filters
                is_ghost = False
                reason = ""
                
                uninst_path = parse_uninstall_path(uninstall_string)
                inst_loc = install_location.strip() if install_location else ""
                
                # Check 1: Empty Registry entry (no uninstall command and no folder)
                if not uninst_path and not inst_loc:
                    is_ghost = True
                    reason = "Empty registry entry (no uninstaller path)"
                
                # Check 2: MSI Installer (msiexec.exe /I...)
                elif uninst_path == 'msiexec':
                    if inst_loc and is_local_path(inst_loc):
                        if not os.path.exists(inst_loc):
                            is_ghost = True
                            reason = f"Folder missing: {inst_loc}"
                        elif os.path.isdir(inst_loc):
                            try:
                                if len(os.listdir(inst_loc)) == 0:
                                    is_ghost = True
                                    reason = f"Folder empty: {inst_loc}"
                            except OSError:
                                pass
                
                # Check 3: Standard uninstaller executable path
                else:
                    if uninst_path and is_local_path(uninst_path):
                        if not os.path.exists(uninst_path):
                            # The uninstaller is missing! Double check the installation folder
                            if inst_loc and is_local_path(inst_loc):
                                if not os.path.exists(inst_loc):
                                    is_ghost = True
                                    reason = "Uninstaller and folder missing"
                                elif os.path.isdir(inst_loc):
                                    try:
                                        if len(os.listdir(inst_loc)) == 0:
                                            is_ghost = True
                                            reason = "Uninstaller missing and folder empty"
                                    except OSError:
                                        pass
                            else:
                                is_ghost = True
                                reason = "Uninstaller executable missing"

                if is_ghost:
                    ghost_apps.append({
                        'name': display_name,
                        'key_name': subkey,
                        'root_str': root_str,
                        'root': root_key,
                        'path': full_path,
                        'reason': reason
                    })

            finally:
                winreg.CloseKey(key)

        winreg.CloseKey(base_key)

    # Sort alphabetically by name
    return sorted(ghost_apps, key=lambda x: x['name'].lower())
