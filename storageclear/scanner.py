import os
import sys
import time

class DirNode:
    """Represents a directory in the scanned file tree."""
    def __init__(self, name, path, parent=None):
        self.name = name
        self.path = path
        self.parent = parent
        self.files = []       # list of dictionaries: {'name': str, 'size': int, 'mtime': float, 'ext': str}
        self.subdirs = {}     # name -> DirNode
        self.size = 0         # Cumulative size of all files in this and child directories
        self.file_count = 0   # Cumulative file count
        self.dir_count = 0    # Cumulative directory count
        self.is_expanded = False
        self.is_selected = False

    def add_file(self, name, size, mtime, ext):
        self.files.append({
            'name': name,
            'size': size,
            'mtime': mtime,
            'ext': ext
        })
        # Propagate size and file count up the tree
        curr = self
        while curr is not None:
            curr.size += size
            curr.file_count += 1
            curr = curr.parent

    def get_subdir(self, name):
        if name not in self.subdirs:
            subdir_path = os.path.join(self.path, name)
            self.subdirs[name] = DirNode(name, subdir_path, parent=self)
            
            # Propagate directory count up
            curr = self
            while curr is not None:
                curr.dir_count += 1
                curr = curr.parent
        return self.subdirs[name]

def is_reparse_point(entry):
    """Detects if an entry is a Windows symlink or directory junction."""
    if entry.is_symlink():
        return True
    try:
        # Check FILE_ATTRIBUTE_REPARSE_POINT (0x400 = 1024)
        stat_val = entry.stat(follow_symlinks=False)
        attrs = getattr(stat_val, 'st_file_attributes', 0)
        if attrs & 0x400:
            return True
    except Exception:
        pass
    return False

def scan_directory(root_paths, exclusions=None):
    """
    Generator that scans the given root paths and yields stats periodically.
    Yields: ('progress', {
        'current_path': str,
        'files_scanned': int,
        'dirs_scanned': int,
        'total_size': int,
        'elapsed': float
    })
    At completion, yields: ('done', {
        'tree_roots': list of DirNode,
        'all_files': list of dictionaries (path, size, mtime, ext),
        'files_scanned': int,
        'dirs_scanned': int,
        'total_size': int,
        'skipped_count': int
    })
    """
    if exclusions is None:
        exclusions = {
            'c:\\windows',
            'system volume information',
            '$recycle.bin',
            '$winreagent',
            'config.msi',
            'msocache',
            'recovery',
            'documents and settings'  # Windows junction loop
        }
    else:
        exclusions = {e.lower() for e in exclusions}

    tree_roots = []
    all_files = []
    
    total_files = 0
    total_dirs = 0
    total_size = 0
    skipped_count = 0
    
    start_time = time.time()
    last_yield_time = start_time

    for root_path in root_paths:
        root_path = os.path.abspath(root_path)
        if not os.path.exists(root_path):
            continue

        root_name = os.path.basename(root_path.rstrip('\\/')) or root_path
        root_node = DirNode(root_name, root_path)
        tree_roots.append(root_node)

        # We'll use a stack for iterative depth-first traversal to avoid stack overflow in deep systems
        stack = [(root_path, root_node)]
        
        while stack:
            # Yield stats to the TUI periodically (every 50ms) to maintain high responsiveness
            now = time.time()
            if now - last_yield_time > 0.05:
                yield 'progress', {
                    'current_path': stack[-1][0] if stack else "",
                    'files_scanned': total_files,
                    'dirs_scanned': total_dirs,
                    'total_size': total_size,
                    'elapsed': now - start_time
                }
                last_yield_time = now

            curr_path, curr_node = stack.pop()
            
            # Check exclusions
            path_lower = curr_path.lower()
            if any(exc in path_lower for exc in exclusions):
                skipped_count += 1
                continue

            try:
                with os.scandir(curr_path) as it:
                    for entry in it:
                        try:
                            # Skip symlinks, junctions, and reparse points to avoid infinite loops
                            if is_reparse_point(entry):
                                skipped_count += 1
                                continue
                            
                            if entry.is_file(follow_symlinks=False):
                                stat_res = entry.stat(follow_symlinks=False)
                                fsize = stat_res.st_size
                                mtime = stat_res.st_mtime
                                name = entry.name
                                ext = os.path.splitext(name)[1].lower()
                                
                                curr_node.add_file(name, fsize, mtime, ext)
                                all_files.append({
                                    'path': entry.path,
                                    'size': fsize,
                                    'mtime': mtime,
                                    'ext': ext
                                })
                                
                                total_files += 1
                                total_size += fsize
                                
                            elif entry.is_dir(follow_symlinks=False):
                                subdir_node = curr_node.get_subdir(entry.name)
                                stack.append((entry.path, subdir_node))
                                total_dirs += 1
                                
                        except (PermissionError, FileNotFoundError, OSError):
                            skipped_count += 1
                            continue
            except (PermissionError, FileNotFoundError, OSError):
                skipped_count += 1
                continue

    # Final yield
    yield 'done', {
        'tree_roots': tree_roots,
        'all_files': all_files,
        'files_scanned': total_files,
        'dirs_scanned': total_dirs,
        'total_size': total_size,
        'skipped_count': skipped_count
    }
