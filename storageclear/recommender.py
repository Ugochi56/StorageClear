import os
import hashlib
from collections import defaultdict

def get_large_files(all_files, limit=200, min_size=10 * 1024**2):
    """
    Returns files sorted by size in descending order.
    Only includes files larger than min_size (default 10MB).
    """
    large_files = [f for f in all_files if f['size'] >= min_size]
    large_files.sort(key=lambda x: x['size'], reverse=True)
    return large_files[:limit]

def calculate_sparse_hash(filepath, filesize):
    """
    Quickly hashes a file by reading the first, middle, and last 10KB.
    Very fast, avoids reading large files entirely if they differ in content.
    """
    chunk_size = 10 * 1024
    hasher = hashlib.md5()
    
    try:
        with open(filepath, 'rb') as f:
            if filesize <= chunk_size * 3:
                # File is small, hash the whole thing
                hasher.update(f.read())
            else:
                # Read first chunk
                hasher.update(f.read(chunk_size))
                
                # Read middle chunk
                f.seek(filesize // 2 - chunk_size // 2)
                hasher.update(f.read(chunk_size))
                
                # Read last chunk
                f.seek(filesize - chunk_size)
                hasher.update(f.read(chunk_size))
        return hasher.hexdigest()
    except (PermissionError, FileNotFoundError, OSError):
        return None

def calculate_full_hash(filepath, filesize=None):
    """
    Calculates MD5 hash of a file. For huge files (>50MB), uses a heavy multi-point 
    sparse hash (first, middle, and last 2MB) to avoid blocking disk bottlenecks.
    """
    if filesize is None:
        try:
            filesize = os.path.getsize(filepath)
        except OSError:
            return None
            
    # For files <= 10MB, do full hash
    if filesize <= 10 * 1024 * 1024:
        hasher = hashlib.md5()
        chunk_size = 64 * 1024
        try:
            with open(filepath, 'rb') as f:
                while True:
                    data = f.read(chunk_size)
                    if not data:
                        break
                    hasher.update(data)
            return hasher.hexdigest()
        except (PermissionError, FileNotFoundError, OSError):
            return None
    else:
        # For huge files, do a heavy multi-point sparse hash (6MB total read)
        # Hash first 2MB, middle 2MB, last 2MB
        hasher = hashlib.md5()
        chunk_size = 2 * 1024 * 1024
        try:
            with open(filepath, 'rb') as f:
                # First chunk
                hasher.update(f.read(chunk_size))
                
                # Middle chunk
                f.seek(filesize // 2 - chunk_size // 2)
                hasher.update(f.read(chunk_size))
                
                # Last chunk
                f.seek(filesize - chunk_size)
                hasher.update(f.read(chunk_size))
            return hasher.hexdigest()
        except (PermissionError, FileNotFoundError, OSError):
            return None

def find_duplicate_files(all_files, min_size=10 * 1024 * 1024):
    """
    Finds duplicate files using a highly optimized multi-stage filter:
    1. Group by file size (only check sizes with 2+ files).
    2. Group by sparse hash (first, middle, last 10KB).
    3. Group by full hash of matching files.
    
    Returns: List of lists, where each sublist contains dictionaries of duplicate files.
    Sorted by total size wasted (size * (count - 1)) descending.
    """
    # 1. Group by size
    size_groups = defaultdict(list)
    for f in all_files:
        if f['size'] >= min_size:
            size_groups[f['size']].append(f)
            
    # Keep only groups with multiple files
    size_candidates = {size: files for size, files in size_groups.items() if len(files) > 1}
    
    # 2. Sparse Hashing
    sparse_groups = defaultdict(list)
    for size, files in size_candidates.items():
        for f in files:
            shash = calculate_sparse_hash(f['path'], size)
            if shash:
                sparse_groups[(size, shash)].append(f)
                
    # Keep only groups with multiple files after sparse hash
    sparse_candidates = {key: files for key, files in sparse_groups.items() if len(files) > 1}
    
    # 3. Full Hashing
    duplicates_map = defaultdict(list)
    for (size, _), files in sparse_candidates.items():
        for f in files:
            fhash = calculate_full_hash(f['path'], size)
            if fhash:
                duplicates_map[(size, fhash)].append(f)
                
    # Format and sort result
    duplicate_groups = []
    for (size, fhash), files in duplicates_map.items():
        if len(files) > 1:
            # Sort files so that oldest or shortest path is first (acts as primary)
            files.sort(key=lambda x: (len(x['path']), x['mtime']))
            duplicate_groups.append({
                'size': size,
                'hash': fhash,
                'files': files,
                'wasted_space': size * (len(files) - 1)
            })
            
    # Sort duplicate groups by wasted space descending
    duplicate_groups.sort(key=lambda x: x['wasted_space'], reverse=True)
    return duplicate_groups

def find_junk_and_cache(tree_roots):
    """
    Recursively searches the DirNode tree to find common development caches,
    build folders, system temp files, and logs.
    Returns: Dict of categories, each containing:
      {
         'name': str,
         'size': int,
         'folders': list of DirNode/paths,
         'files': list of file paths
      }
    """
    categories = {
        'py_cache': {
            'name': 'Python Cache & Compiled Bytecode (__pycache__, .pytest_cache)',
            'size': 0,
            'paths': [], # list of paths to delete (can be folder or file)
            'is_safe': True
        },
        'node_modules': {
            'name': 'Node.js Dependency Modules (node_modules)',
            'size': 0,
            'paths': [],
            'is_safe': False
        },
        'venv': {
            'name': 'Python Virtual Environments (.venv, venv, env)',
            'size': 0,
            'paths': [],
            'is_safe': False
        },
        'build_cache': {
            'name': 'IDE, Compiler & Package Caches (.gradle, .npm, target/, .sass-cache)',
            'size': 0,
            'paths': [],
            'is_safe': True
        },
        'logs_temp': {
            'name': 'System & Application Logs/Temp Files (*.log, *.tmp)',
            'size': 0,
            'paths': [],
            'is_safe': True
        }
    }

    # Helper recursive function
    def traverse(node):
        node_name_lower = node.name.lower()
        
        # 1. Match Junk/Cache directories
        if node_name_lower in ('__pycache__', '.pytest_cache'):
            categories['py_cache']['size'] += node.size
            categories['py_cache']['paths'].append(node.path)
            return  # Stop traversal of subdirs inside cache
            
        elif node_name_lower == 'node_modules':
            categories['node_modules']['size'] += node.size
            categories['node_modules']['paths'].append(node.path)
            return
            
        elif node_name_lower in ('.venv', 'venv', 'env') and os.path.exists(os.path.join(node.path, 'Scripts' if os.name == 'nt' else 'bin')):
            # Verify it's a virtual env by checking for python executables
            categories['venv']['size'] += node.size
            categories['venv']['paths'].append(node.path)
            return
            
        elif node_name_lower in ('.gradle', '.npm', '.sass-cache', 'target', '.cache'):
            categories['build_cache']['size'] += node.size
            categories['build_cache']['paths'].append(node.path)
            return
            
        # 2. Inspect files inside this node
        for f in node.files:
            fname = f['name'].lower()
            fext = f['ext']
            fpath = os.path.join(node.path, f['name'])
            
            if fext in ('.tmp', '.temp') or fname.endswith('.log') or fname == 'thumbs.db' or fname == '.ds_store':
                categories['logs_temp']['size'] += f['size']
                categories['logs_temp']['paths'].append(fpath)
            elif fext in ('.pyc', '.pyo'):
                categories['py_cache']['size'] += f['size']
                categories['py_cache']['paths'].append(fpath)

        # 3. Recursively check child directories
        for subdir in list(node.subdirs.values()):
            traverse(subdir)

    for root in tree_roots:
        traverse(root)
        
    # Filter categories that actually have contents
    return {k: v for k, v in categories.items() if v['paths']}
