import os
import sys
import time
import msvcrt
import ctypes
from ctypes import wintypes
import shutil

from storageclear.ops import get_logical_drives, send_to_recycle_bin, delete_permanently, get_ghost_applications, delete_registry_key_recursive, is_user_admin, get_startup_applications, get_memory_status
from storageclear.scanner import scan_directory, DirNode
from storageclear.recommender import get_large_files, find_duplicate_files, find_junk_and_cache

# ANSI Formatting Constants (TrueColor/RGB)
RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
UNDERLINE = "\x1b[4m"

# Text Colors
COLOR_PRIMARY = "\x1b[38;2;99;102;241m"    # Indigo
COLOR_SUCCESS = "\x1b[38;2;16;185;129m"    # Emerald Green
COLOR_WARNING = "\x1b[38;2;245;158;11m"    # Amber Yellow
COLOR_DANGER = "\x1b[38;2;239;68;68m"      # Rose Red
COLOR_CYAN = "\x1b[38;2;6;182;212m"        # Cyan
COLOR_GRAY = "\x1b[38;2;156;163;175m"      # Gray
COLOR_DARK_GRAY = "\x1b[38;2;75;85;99m"    # Charcoal Gray

# Backgrounds
BG_HEADER = "\x1b[48;2;31;41;55m"          # Dark Gray BG
BG_HIGHLIGHT = "\x1b[48;2;55;65;81m"       # Medium Gray BG for active item

def enable_windows_ansi():
    """Enables Virtual Terminal (ANSI escape sequences) in Windows Console."""
    if sys.platform != 'win32':
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        h_stdout = kernel32.GetStdHandle(-11) # STD_OUTPUT_HANDLE
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(h_stdout, ctypes.byref(mode)):
            return False
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        # DISABLE_NEWLINE_AUTO_RETURN = 0x0008
        new_mode = mode.value | 0x0004 | 0x0008
        return kernel32.SetConsoleMode(h_stdout, new_mode) != 0
    except Exception:
        return False

def format_size(size_bytes):
    """Formats size in bytes into human readable format (GB, MB, etc.)."""
    if size_bytes == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    i = 0
    while size_bytes >= 1024 and i < len(units) - 1:
        size_bytes /= 1024
        i += 1
    return f"{size_bytes:.2f} {units[i]}"

def get_selection_state(node):
    """
    Computes selection state of a DirNode.
    Returns 'all' (fully selected), 'partial' (some children selected), or 'none' (none selected).
    """
    # Base case: empty leaf directory
    if not node.files and not node.subdirs:
        return 'all' if node.is_selected else 'none'

    all_selected = True
    any_selected = False

    for f in node.files:
        if f.get('is_selected', False):
            any_selected = True
        else:
            all_selected = False

    for s in node.subdirs.values():
        s_state = get_selection_state(s)
        if s_state == 'all':
            any_selected = True
        elif s_state == 'partial':
            any_selected = True
            all_selected = False
        else:
            all_selected = False

    if all_selected:
        return 'all'
    elif any_selected:
        return 'partial'
    else:
        return 'none'

def set_node_selection(node, is_selected):
    """Recursively sets selection on a DirNode and all its contents."""
    node.is_selected = is_selected
    for f in node.files:
        f['is_selected'] = is_selected
    for s in node.subdirs.values():
        set_node_selection(s, is_selected)

def get_console_size():
    """Returns (columns, rows) of terminal, handling OS errors."""
    try:
        size = shutil.get_terminal_size((80, 24))
        return size.columns, size.lines
    except Exception:
        return 80, 24

def clear_screen():
    """Clears terminal and moves cursor to home position."""
    sys.stdout.write("\x1b[2J\x1b[H")
    sys.stdout.flush()

class TUIApp:
    def __init__(self, start_paths=None):
        self.start_paths = start_paths
        self.drives = []
        self.selected_drives = set()
        
        # Scanned data
        self.tree_roots = []
        self.all_files = []
        self.total_size = 0
        self.files_scanned = 0
        self.dirs_scanned = 0
        
        # UI State
        self.state = "drive_selector" # drive_selector, scanning, dashboard, confirmation, deleting, done
        self.current_tab = 0 # 0: Tree Explorer, 1: Duplicates, 2: Large Files, 3: Junk/Cache, 4: Ghost Apps
        self.active_index = 0
        self.scroll_top = 0
        
        # View Data Models
        self.visible_items = [] # Stores flat list of items rendered in current tab
        self.duplicates = []
        self.large_files = []
        self.junk_categories = {}
        self.ghost_apps = []
        
        # Selected items to delete
        self.selected_to_delete = [] # list of dicts: {'type': 'file'/'folder', 'path': str, 'size': int}
        
        # PC Performance Diagnostics Feature
        self.run_diagnostics_opt = False
        self.perf_diagnostics = []
        
    def run(self):
        """Main TUI Loop."""
        if sys.platform == 'win32':
            sys.stdout.reconfigure(encoding='utf-8')

        if not enable_windows_ansi():
            print("Warning: Could not enable ANSI virtual terminal processing on this console.")
        
        # Enter alternate screen buffer & hide cursor
        sys.stdout.write("\x1b[?1049h\x1b[?25l")
        sys.stdout.flush()
        
        try:
            self.load_drives()
            
            # If start paths are passed via CLI, skip drive selector
            if self.start_paths:
                self.selected_drives = set(self.start_paths)
                self.run_scan()
            
            while True:
                self.render()
                if self.handle_input():
                    break
        finally:
            # Exit alternate screen buffer, show cursor, and restore color
            sys.stdout.write("\x1b[?1049l\x1b[?25h" + RESET)
            sys.stdout.flush()

    def load_drives(self):
        """Loads drive letter configurations from ops.py."""
        self.drives = get_logical_drives()
        if self.drives:
            # Auto-select the first drive
            self.selected_drives.add(self.drives[0]['drive'])
        self.active_index = 0

    def render(self):
        """Router for screen renders."""
        cols, rows = get_console_size()
        
        # Move cursor to home without clearing to avoid flickering
        sys.stdout.write("\x1b[H")
        
        if self.state == "drive_selector":
            self.render_drive_selector(cols, rows)
        elif self.state == "scanning":
            self.render_scanning(cols, rows)
        elif self.state == "dashboard":
            self.render_dashboard(cols, rows)
        elif self.state == "confirmation":
            self.render_confirmation(cols, rows)
        elif self.state == "deleting":
            self.render_deleting(cols, rows)
        elif self.state == "done":
            self.render_done(cols, rows)

        sys.stdout.flush()

    # --- SCREEN RENDERING ---

    def render_header(self, title, cols):
        """Helper to draw a premium header card."""
        banner_text = " STORAGE CLEAR  ::  Deep Disk Mapper & Space Reclaim System "
        padding = (cols - len(banner_text)) // 2
        header_line = BG_HEADER + BOLD + COLOR_PRIMARY + " " * padding + banner_text + " " * (cols - len(banner_text) - padding) + RESET + "\n"
        
        title_line = BOLD + f"  » {title} " + RESET
        title_fill = cols - len(f"  » {title} ") - 2
        border_line = COLOR_PRIMARY + title_line + COLOR_DARK_GRAY + "─" * title_fill + RESET + "\n"
        
        return header_line + border_line

    def render_drive_selector(self, cols, rows):
        """Draws the drive letters checkbox selector."""
        lines = []
        lines.append(self.render_header("SELECT PARTITIONS TO SCAN", cols))
        lines.append(COLOR_GRAY + " Use [UP/DOWN] to navigate, [SPACE] to select/deselect, and [ENTER] to start scanning.\n" + RESET)
        
        # Render table headers
        table_hdr = f"  {'[x]':5} {'Drive':8} {'Volume Label':15} {'FS':8} {'Used / Total Capacity':30} {'Free Space':12}"
        lines.append(BOLD + COLOR_PRIMARY + table_hdr + RESET + "\n")
        lines.append(COLOR_DARK_GRAY + "  " + "─" * (cols - 4) + RESET + "\n")
        
        max_visible_drives = rows - 9
        for i, drive in enumerate(self.drives):
            if i >= max_visible_drives:
                break
                
            drive_letter = drive['drive']
            is_active = (i == self.active_index)
            is_sel = drive_letter in self.selected_drives
            
            check = "[x]" if is_sel else "[ ]"
            check_color = COLOR_SUCCESS if is_sel else COLOR_GRAY
            
            # Progress bar calculations
            used = drive['used']
            total = drive['total']
            pct = (used / total * 100) if total > 0 else 0
            
            bar_width = 12
            filled = int(bar_width * pct / 100)
            bar_color = COLOR_DANGER if pct > 85 else (COLOR_WARNING if pct > 60 else COLOR_SUCCESS)
            bar_str = bar_color + "█" * filled + COLOR_DARK_GRAY + "░" * (bar_width - filled) + RESET
            
            pct_str = f"{pct:5.1f}%"
            used_total_str = f"{format_size(used)} / {format_size(total)}"
            space_bar = f"{bar_str} {pct_str} ({used_total_str})"
            
            line_str = f"  {check_color}{check:5}{RESET} {BOLD}{drive_letter:8}{RESET} {drive['label'][:15]:15} {drive['fs']:8} {space_bar:30} {COLOR_SUCCESS}{format_size(drive['free']):12}{RESET}"
            
            if is_active:
                lines.append(BG_HIGHLIGHT + line_str + " " * (cols - len(line_str) + 21) + RESET + "\n") # Adjust padding for ANSI codes
            else:
                lines.append(line_str + "\n")
                
        # Draw dynamic diagnostics option row below drives table
        opt_idx = len(self.drives)
        is_opt_active = (self.active_index == opt_idx)
        opt_check = "[x]" if self.run_diagnostics_opt else "[ ]"
        opt_check_color = COLOR_SUCCESS if self.run_diagnostics_opt else COLOR_GRAY
        
        opt_line = f"  {opt_check_color}{opt_check}{RESET} {BOLD}Diagnose PC Performance & Boot Bottlenecks (Safely Check RAM, Startup, Drives & Caches){RESET}"
        
        lines.append("\n") # Spacer
        if is_opt_active:
            lines.append(BG_HIGHLIGHT + opt_line + " " * max(1, cols - len(opt_line) + 21) + RESET + "\n")
        else:
            lines.append(opt_line + "\n")

        # Fill empty rows
        for _ in range(rows - len(lines) - 2):
            lines.append("\n")
            
        # Draw status help bar
        footer = BG_HEADER + COLOR_PRIMARY + BOLD + " [Space] Toggle | [Enter] Start Deep Scan | [Q] Quit " + RESET
        lines.append(footer + " " * (cols - len(" [Space] Toggle | [Enter] Start Deep Scan | [Q] Quit ")))
        
        sys.stdout.write("".join(lines).rstrip('\n'))

    def render_scanning(self, cols, rows):
        """Draws the live scanning progress card with a clean, stable progress bar."""
        lines = []
        lines.append(self.render_header("DYNAMIC PARTITION TRAVERSAL IN PROGRESS", cols))
        lines.append("\n\n")
        
        # Calculate used space of selected drives for percentage bar
        total_used_space = 0
        for drive in self.drives:
            if drive['drive'] in self.selected_drives:
                total_used_space += drive['used']
                
        # Draw clean border card
        card_width = min(cols - 8, 72)
        lines.append("   " + COLOR_PRIMARY + "┌" + "─" * card_width + "┐" + RESET + "\x1b[K\n")
        
        # Check if we are in post-scan analysis phase
        is_analyzing = getattr(self, 'is_analyzing', False)
        
        # Draw spinner + scanning status
        spinners = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        spin_char = spinners[int(time.time() * 10) % len(spinners)]
        if is_analyzing:
            status_text = " ⌛  Analyzing files & matching duplicates... "
        else:
            status_text = f" {spin_char}  Indexing files & directories... "
        lines.append("   " + COLOR_PRIMARY + "│ " + RESET + BOLD + COLOR_PRIMARY + status_text + RESET + " " * (card_width - len(status_text) - 1) + COLOR_PRIMARY + "│" + RESET + "\x1b[K\n")
        
        lines.append("   " + COLOR_PRIMARY + "│" + " " * card_width + "│" + RESET + "\x1b[K\n")
        
        # Build progress bar
        bar_width = card_width - 16
        bar_width = max(10, bar_width)
        
        if is_analyzing:
            bar_str = COLOR_SUCCESS + "█" * bar_width + RESET
            pct_str = " 100% "
        elif total_used_space > 0:
            pct = (self.total_size / total_used_space * 100) if total_used_space > 0 else 0
            pct = min(99.9, pct)
            filled = int(bar_width * pct / 100)
            bar_color = COLOR_SUCCESS if pct > 75 else (COLOR_WARNING if pct > 40 else COLOR_PRIMARY)
            bar_str = bar_color + "█" * filled + COLOR_DARK_GRAY + "░" * (bar_width - filled) + RESET
            pct_str = f"{pct:5.1f}%"
        else:
            # Indeterminate progress bar (bouncing loader)
            pos = int(time.time() * 15) % (bar_width * 2)
            block_size = min(bar_width // 4 + 1, 6)
            if pos >= bar_width:
                pos = bar_width * 2 - 1 - pos
            # Keep bounds
            pos = min(pos, bar_width - block_size)
            pos = max(0, pos)
            
            bar_str = COLOR_DARK_GRAY + "░" * pos + COLOR_PRIMARY + "█" * block_size + COLOR_DARK_GRAY + "░" * (bar_width - block_size - pos) + RESET
            pct_str = " SCAN "
            
        bar_line = f"  Progress:  [{bar_str}]  {BOLD}{pct_str}{RESET} "
        # Stripped length (excluding ANSI formatting)
        raw_len = 14 + bar_width + len(pct_str)
        lines.append("   " + COLOR_PRIMARY + "│" + RESET + bar_line + " " * (card_width - raw_len - 1) + COLOR_PRIMARY + "│" + RESET + "\x1b[K\n")
        
        lines.append("   " + COLOR_PRIMARY + "│" + " " * card_width + "│" + RESET + "\x1b[K\n")
        
        # Stats lines inside card
        stats_line = f"  Dirs: {self.dirs_scanned:,}  |  Files: {self.files_scanned:,}  |  Indexed: {format_size(self.total_size)} "
        lines.append("   " + COLOR_PRIMARY + "│" + RESET + COLOR_GRAY + stats_line + RESET + " " * (card_width - len(stats_line) - 1) + COLOR_PRIMARY + "│" + RESET + "\x1b[K\n")
        
        lines.append("   " + COLOR_PRIMARY + "└" + "─" * card_width + "┘" + RESET + "\x1b[K\n")
        
        # Fill rest cleanly with ANSI clear-to-end-of-line to prevent ghosting or scrolling
        for _ in range(rows - len(lines) - 2):
            lines.append("\x1b[K\n")
            
        footer = BG_HEADER + COLOR_WARNING + BOLD + " [Esc] Cancel Scan " + RESET
        lines.append(footer + " " * (cols - len(" [Esc] Cancel Scan ")) + "\x1b[K")
        
        sys.stdout.write("".join(lines).rstrip('\n'))

    def render_dashboard(self, cols, rows):
        """Draws the main interactive multi-tab directory mapper dashboard."""
        lines = []
        
        # Tab Header Labels
        tab_names = ["1. Disk Tree Explorer", "2. Duplicate Finder", "3. Large Files (>10MB)", "4. Junk & Cache Finder", "5. Ghost App Cleaner"]
        if getattr(self, 'run_diagnostics_opt', False):
            tab_names.append("6. Performance Boost")
        tab_line = " "
        for i, name in enumerate(tab_names):
            is_active_tab = (i == self.current_tab)
            if is_active_tab:
                tab_line += BG_HIGHLIGHT + COLOR_PRIMARY + BOLD + f"  {name}  " + RESET + "  "
            else:
                tab_line += BG_HEADER + COLOR_GRAY + f"  {name}  " + RESET + "  "
        
        lines.append(self.render_header("STORAGE RECOMMENDATIONS DASHBOARD", cols))
        lines.append(tab_line + "\n")
        lines.append(COLOR_DARK_GRAY + "─" * cols + RESET + "\n")
        
        # Calculate viewport constraints
        # 1 Header, 1 Title border, 1 Tab line, 1 Border, 1 Spacer, 1 Status Bar, 2 Reclaim footer lines
        header_height = 8
        view_height = rows - header_height - 3
        
        # Load View data based on tab
        self.update_visible_items()
        
        # Adjust scrolling window
        if self.active_index < self.scroll_top:
            self.scroll_top = self.active_index
        elif self.active_index >= self.scroll_top + view_height:
            self.scroll_top = self.active_index - view_height + 1
            
        # Check boundary
        self.scroll_top = max(0, min(self.scroll_top, len(self.visible_items) - view_height))
        
        # Render Viewport rows
        visible_range = self.visible_items[self.scroll_top : self.scroll_top + view_height]
        
        for idx, item in enumerate(visible_range):
            actual_idx = self.scroll_top + idx
            is_cursor_row = (actual_idx == self.active_index)
            
            row_str = self.format_row_item(item, cols)
            
            if is_cursor_row:
                # Add highlighting background
                lines.append(BG_HIGHLIGHT + row_str + RESET + "\n")
            else:
                lines.append(row_str + "\n")
                
        # Fill viewport with blanks if list is short
        for _ in range(view_height - len(visible_range)):
            lines.append("\n")
            
        # Draw status bars
        lines.append(COLOR_DARK_GRAY + "─" * cols + RESET + "\n")
        
        # Calculate reclaimable total size (using pre-cached values!)
        if not hasattr(self, 'reclaim_size'):
            self.calculate_reclaim_stats()
            
        reclaim_size = self.reclaim_size
        reclaim_files = self.reclaim_files
        reclaim_folders = self.reclaim_folders
        reclaim_registry = self.reclaim_registry
                
        reclaim_parts = []
        if reclaim_files > 0 or (reclaim_folders == 0 and reclaim_registry == 0):
            reclaim_parts.append(f"{reclaim_files} files")
        if reclaim_folders > 0:
            reclaim_parts.append(f"{reclaim_folders} folders")
        if reclaim_registry > 0:
            reclaim_parts.append(f"{reclaim_registry} registry keys")
            
        reclaim_str = f" Queue: {COLOR_WARNING}{format_size(reclaim_size)}{RESET} ({', '.join(reclaim_parts)}) "
        reclaim_bar = BOLD + "Selected Reclaim" + COLOR_DARK_GRAY + " » " + reclaim_str
        
        # Calculate stripped text length to pad the status line correctly
        stripped_len = len("Selected Reclaim »  Queue: ") + len(format_size(reclaim_size)) + len(f" ({', '.join(reclaim_parts)})")
        lines.append(reclaim_bar + " " * max(1, cols - stripped_len - 10) + "\n")
        
        # Actions bar
        footer_help = BG_HEADER + COLOR_PRIMARY + BOLD + " [Tab] Switch Tab | [Arrows] Navigate | [Space] Select | [Enter] Expand/Collapse | [D] Clean Checked | [Q] Quit " + RESET
        lines.append(footer_help + " " * (cols - len(" [Tab] Switch Tab | [Arrows] Navigate | [Space] Select | [Enter] Expand/Collapse | [D] Clean Checked | [Q] Quit ") + 8))
        
        sys.stdout.write("".join(lines).rstrip('\n'))

    def render_confirmation(self, cols, rows):
        """Draws the deletion summary screen before executing."""
        lines = []
        lines.append(self.render_header("CONFIRM RECLAIM DELETION QUEUE", cols))
        lines.append("\n")
        
        reclaim_size = sum(item['size'] for item in self.selected_to_delete)
        reclaim_files = sum(1 for item in self.selected_to_delete if item['type'] == 'file')
        reclaim_folders = sum(1 for item in self.selected_to_delete if item['type'] == 'folder')
        reclaim_registry = sum(1 for item in self.selected_to_delete if item['type'] == 'ghost_app')
        
        lines.append(f"  {COLOR_WARNING}{BOLD}You are about to delete:{RESET}\n")
        lines.append(f"    Total Space:  {COLOR_DANGER}{BOLD}{format_size(reclaim_size)}{RESET}\n")
        lines.append(f"    Directories:  {COLOR_CYAN}{reclaim_folders}{RESET}\n")
        lines.append(f"    Files:        {COLOR_CYAN}{reclaim_files}{RESET}\n")
        if reclaim_registry > 0:
            lines.append(f"    Registry Keys:{COLOR_CYAN}{reclaim_registry}{RESET}\n")
        lines.append("\n")
        
        lines.append(f"  {COLOR_GRAY}Items to be deleted (top 15 shown below):{RESET}\n")
        lines.append(COLOR_DARK_GRAY + "  " + "─" * (cols - 4) + RESET + "\n")
        
        # Show some items
        for item in self.selected_to_delete[:15]:
            if item['type'] == 'ghost_app':
                itype = "[REG] "
                icolor = COLOR_WARNING
                size_str = "0 Bytes"
            else:
                itype = "[DIR] " if item['type'] == 'folder' else "[FILE]"
                icolor = COLOR_CYAN if item['type'] == 'folder' else COLOR_GRAY
                size_str = format_size(item['size'])
            path_str = item['path']
            if len(path_str) > cols - 30:
                path_str = "..." + path_str[-(cols - 33):]
            lines.append(f"    {icolor}{itype:6}{RESET} {size_str:10} {path_str}\n")
            
        if len(self.selected_to_delete) > 15:
            lines.append(f"    {COLOR_GRAY}... and {len(self.selected_to_delete) - 15} more items.{RESET}\n")
            
        # Draw Warnings
        lines.append("\n")
        lines.append(f"  {BG_HIGHLIGHT}{COLOR_WARNING} WARNING: {RESET} Windows Recycle Bin is used by default for files. Large items might be permanently deleted.\n")
        if reclaim_registry > 0:
            lines.append(f"  {BG_HIGHLIGHT}{COLOR_DANGER} CAUTION: {RESET} Registry keys cannot be sent to the Recycle Bin and are deleted permanently.\n")
        
        # Fill rest
        for _ in range(rows - len(lines) - 2):
            lines.append("\n")
            
        footer = BG_HEADER + COLOR_DANGER + BOLD + " [R] Send to Recycle Bin (Safe) | [P] Delete Permanently (Caution!) | [Esc] Cancel " + RESET
        lines.append(footer + " " * (cols - len(" [R] Send to Recycle Bin (Safe) | [P] Delete Permanently (Caution!) | [Esc] Cancel ") + 20))
        
        sys.stdout.write("".join(lines).rstrip('\n'))

    def render_deleting(self, cols, rows):
        """Draws screen during deletion process."""
        lines = []
        lines.append(self.render_header("EXECUTING CLEANUP OPERATIONS", cols))
        lines.append("\n\n")
        lines.append(f"   {COLOR_DANGER}{BOLD}Deleting selected folders and files natively...{RESET}\n\n")
        lines.append(f"   Deleting item: {COLOR_GRAY}{self.visible_items[0] if self.visible_items else 'Starting...'}{RESET}\n")
        
        for _ in range(rows - len(lines) - 1):
            lines.append("\n")
        sys.stdout.write("".join(lines).rstrip('\n'))

    def render_done(self, cols, rows):
        """Draws the final success summary screen."""
        lines = []
        lines.append(self.render_header("CLEANUP COMPLETED SUCCESSFULLY", cols))
        lines.append("\n\n")
        
        reclaim_size = sum(item['size'] for item in self.selected_to_delete)
        reclaim_deleted = len(self.selected_to_delete)
        failed_count = len(getattr(self, 'failed_registry_permissions', []))
        successful_deleted = reclaim_deleted - failed_count
        
        lines.append(f"   {COLOR_SUCCESS}{BOLD}✔ Reclamation complete!{RESET}\n\n")
        lines.append(f"   Total Space Reclaimed: {COLOR_SUCCESS}{BOLD}{format_size(reclaim_size)}{RESET}\n")
        lines.append(f"   Items Cleaned:         {COLOR_CYAN}{successful_deleted} successful{RESET}\n\n")
        lines.append("   Your drive was updated in real time. Press [R] to re-scan for fresh results.\n")
        
        if failed_count > 0:
            lines.append("\n")
            lines.append(f"   {BG_HIGHLIGHT}{COLOR_DANGER} WARNING: {RESET} {failed_count} registry keys could not be purged due to missing permissions.\n")
            lines.append(f"   They belong to HKEY_LOCAL_MACHINE (HKLM). To delete system-level software\n")
            lines.append(f"   uninstall listings, please run your Command Prompt / Terminal as {BOLD}Administrator{RESET}.\n")
        
        for _ in range(rows - len(lines) - 2):
            lines.append("\n")
            
        footer = BG_HEADER + COLOR_PRIMARY + BOLD + " [Enter] Back to Dashboard | [R] Re-Scan Drive | [Q] Quit " + RESET
        lines.append(footer + " " * (cols - len(" [Enter] Back to Dashboard | [R] Re-Scan Drive | [Q] Quit ")))
        
        sys.stdout.write("".join(lines).rstrip('\n'))

    # --- ROW FORMATTING SCHEME ---

    def format_row_item(self, item, cols):
        """Formats single line item with correct checkbox symbols and colors depending on active tab."""
        # Width configurations
        checkbox_width = 6
        size_width = 12
        
        if self.current_tab == 0: # 1. Directory Tree
            node_type = item['type'] # 'folder' or 'file'
            indent = "  " * item['depth']
            
            # Checkbox state
            if node_type == 'folder':
                state = get_selection_state(item['node'])
                if state == 'all':
                    check = "[x]"
                    check_color = COLOR_SUCCESS
                elif state == 'partial':
                    check = "[~]"
                    check_color = COLOR_WARNING
                else:
                    check = "[ ]"
                    check_color = COLOR_GRAY
            else:
                is_sel = item['file'].get('is_selected', False)
                check = "[x]" if is_sel else "[ ]"
                check_color = COLOR_SUCCESS if is_sel else COLOR_GRAY
                
            # Type Icons & colors
            if node_type == 'folder':
                folder = item['node']
                expand_icon = "▼" if folder.is_expanded else "►"
                icon = f"{COLOR_CYAN}📁 {expand_icon}{RESET}"
                
                # Dynamic folder size coloring
                if folder.size > 5 * 1024**3: # > 5GB
                    name_color = COLOR_DANGER + BOLD
                elif folder.size > 1024**3: # > 1GB
                    name_color = COLOR_WARNING
                else:
                    name_color = COLOR_CYAN
                name_str = name_color + folder.name + RESET
                size_str = COLOR_CYAN + format_size(folder.size) + RESET
            else:
                icon = f"{COLOR_GRAY}📄{RESET}"
                name_str = COLOR_GRAY + item['file']['name'] + RESET
                size_str = COLOR_GRAY + format_size(item['file']['size']) + RESET
                
            # Truncate row nicely
            text_part = f" {check_color}{check}{RESET} {indent}{icon} {name_str}"
            # Stripped width calculation for formatting spaces
            raw_len = checkbox_width + len(indent) + 4 + len(item['node'].name if node_type == 'folder' else item['file']['name'])
            spaces_to_add = max(2, cols - raw_len - size_width - 4)
            
            return f"{text_part}{' ' * spaces_to_add}{size_str:>{size_width}}"

        elif self.current_tab == 1: # 2. Duplicate Finder
            # Item can be: {'type': 'header', 'group': group} or {'type': 'item', 'file': file, 'group': group}
            if item['type'] == 'header':
                group = item['group']
                wasted_str = COLOR_DANGER + f"Wasted: {format_size(group['wasted_space'])}" + RESET
                filename = os.path.basename(group['files'][0]['path'])
                header_str = f"  📁 Group: {COLOR_WARNING}{filename}{RESET}  (Size: {format_size(group['size'])}, {len(group['files'])} copies)"
                
                raw_len = len(filename) + len(format_size(group['size'])) + 28
                spaces = max(2, cols - raw_len - 25)
                return f"{header_str}{' ' * spaces}{wasted_str:>20}"
            else:
                f = item['file']
                is_sel = f.get('is_selected', False)
                check = "[x]" if is_sel else "[ ]"
                check_color = COLOR_SUCCESS if is_sel else COLOR_GRAY
                
                is_primary = (item['index'] == 0)
                tag = f" {COLOR_SUCCESS}(Original Keep){RESET}" if is_primary else f" {COLOR_WARNING}(Duplicate Delete){RESET}"
                
                path_str = f['path']
                if len(path_str) > cols - 35:
                    path_str = "..." + path_str[-(cols - 38):]
                    
                path_color = COLOR_CYAN if is_primary else COLOR_GRAY
                return f"    {check_color}{check}{RESET} {path_color}{path_str}{RESET}{tag}"

        elif self.current_tab == 2: # 3. Large Files
            f = item['file']
            is_sel = f.get('is_selected', False)
            check = "[x]" if is_sel else "[ ]"
            check_color = COLOR_SUCCESS if is_sel else COLOR_GRAY
            
            path_str = f['path']
            if len(path_str) > cols - size_width - 15:
                path_str = "..." + path_str[-(cols - size_width - 18):]
                
            size_str = COLOR_DANGER if f['size'] > 500 * 1024**2 else COLOR_WARNING
            formatted_size = size_str + format_size(f['size']) + RESET
            
            raw_len = checkbox_width + len(f['path'])
            spaces = max(2, cols - raw_len - size_width - 10)
            return f"  {check_color}{check}{RESET}  {COLOR_GRAY}{path_str}{RESET}{' ' * spaces}{formatted_size:>{size_width}}"

        elif self.current_tab == 3: # 4. Junk & Cache Finder
            # Item can be: {'type': 'header', 'cat_key': key} or {'type': 'item', 'path': path, 'cat_key': key}
            if item['type'] == 'header':
                cat = self.junk_categories[item['cat_key']]
                # Determine if all items in category are selected
                all_sel = all(self.is_path_selected(p) for p in cat['paths'])
                any_sel = any(self.is_path_selected(p) for p in cat['paths'])
                
                check = "[x]" if all_sel else ("[~]" if any_sel else "[ ]")
                check_color = COLOR_SUCCESS if all_sel else (COLOR_WARNING if any_sel else COLOR_GRAY)
                
                size_str = COLOR_DANGER + format_size(cat['size']) + RESET
                title = f"  {check_color}{check}{RESET}  📁 {BOLD}{COLOR_WARNING}{cat['name']}{RESET}"
                
                raw_len = len(cat['name']) + 16
                spaces = max(2, cols - raw_len - size_width - 4)
                return f"{title}{' ' * spaces}{size_str:>{size_width}}"
            else:
                path = item['path']
                is_sel = self.is_path_selected(path)
                check = "[x]" if is_sel else "[ ]"
                check_color = COLOR_SUCCESS if is_sel else COLOR_GRAY
                
                size = item['size']
                path_disp = path
                if len(path_disp) > cols - size_width - 18:
                    path_disp = "..." + path_disp[-(cols - size_width - 21):]
                    
                raw_len = checkbox_width + 4 + len(path)
                spaces = max(2, cols - raw_len - size_width - 10)
                
                return f"      {check_color}{check}{RESET}  {COLOR_GRAY}{path_disp}{RESET}{' ' * spaces}{COLOR_CYAN}{format_size(size):>{size_width}}{RESET}"
                
        elif self.current_tab == 4: # 5. Ghost App Cleaner
            app = item['app']
            is_sel = app.get('is_selected', False)
            check = "[x]" if is_sel else "[ ]"
            check_color = COLOR_SUCCESS if is_sel else COLOR_GRAY
            
            app_name = app['name']
            reason = app['reason']
            root_str = app['root_str']
            
            # Display name and reason nicely
            display_text = f"  {check_color}{check}{RESET}  {COLOR_CYAN}{app_name}{RESET}  {COLOR_GRAY}({reason}){RESET}"
            
            # Right side displays HKLM or HKCU with warning color if HKLM
            root_color = COLOR_DANGER if root_str == "HKLM" else COLOR_WARNING
            root_display = f"{root_color}{root_str}{RESET}"
            
            # Width formatting
            raw_len = checkbox_width + len(app_name) + len(reason) + 8
            spaces = max(2, cols - raw_len - len(root_str) - 4)
            
            return f"{display_text}{' ' * spaces}{root_display}"
            
        elif self.current_tab == 5: # 6. PC Performance Boost
            diag = item['diag']
            status = diag['status']
            
            # Status colors & icons
            if status == "HEALTHY":
                status_str = f"{COLOR_SUCCESS}✔ HEALTHY{RESET}"
            elif status == "WARNING":
                status_str = f"{COLOR_DANGER}✖ WARNING{RESET}"
            else: # NOTICE
                status_str = f"{COLOR_WARNING}⚠ NOTICE{RESET}"
                
            if item['type'] == 'perf_header':
                title = f"  📁 Category: {BOLD}{COLOR_PRIMARY}{diag['category']}{RESET}"
                raw_len = 15 + len(diag['category'])
                spaces = max(2, cols - raw_len - 15)
                return f"{title}{' ' * spaces}{status_str}"
                
            elif item['type'] == 'perf_details':
                details_text = f"    {COLOR_GRAY}ℹ Details: {diag['details']}{RESET}"
                if len(details_text) > cols - 2:
                    details_text = details_text[:cols - 5] + "..."
                return details_text
                
            elif item['type'] == 'perf_recommend':
                tip_text = f"    {COLOR_CYAN}💡 Speed-up Tip: {diag['recommendation']}{RESET}"
                # Safely wrap or truncate
                if len(tip_text) > cols - 2:
                    tip_text = tip_text[:cols - 5] + "..."
                return tip_text
                
            elif item['type'] == 'perf_spacer':
                return f"  {COLOR_DARK_GRAY}{'─' * (cols - 4)}{RESET}"
            
        return ""

    # --- LOGICAL CORE CALCULATIONS ---

    def calculate_reclaim_stats(self):
        """Walks all models to compile exact queue list of selected-to-delete files/folders."""
        self.selected_to_delete = []
        
        # 1. Check Directory Tree
        def traverse_tree(node):
            state = get_selection_state(node)
            if state == 'all':
                self.selected_to_delete.append({
                    'type': 'folder',
                    'path': node.path,
                    'size': node.size
                })
                return # Don't traverse deeper as the whole folder is deleted
                
            for f in node.files:
                if f.get('is_selected', False):
                    self.selected_to_delete.append({
                        'type': 'file',
                        'path': os.path.join(node.path, f['name']),
                        'size': f['size']
                    })
            for s in node.subdirs.values():
                traverse_tree(s)

        for root in self.tree_roots:
            traverse_tree(root)
            
        # 2. Check Duplicates (only if not already caught in tree explorer)
        existing_paths = {x['path'] for x in self.selected_to_delete}
        for group in self.duplicates:
            for f in group['files']:
                if f.get('is_selected', False) and f['path'] not in existing_paths:
                    self.selected_to_delete.append({
                        'type': 'file',
                        'path': f['path'],
                        'size': f['size']
                    })
                    existing_paths.add(f['path'])
                    
        # 3. Check Large Files
        for f in self.large_files:
            if f.get('is_selected', False) and f['path'] not in existing_paths:
                self.selected_to_delete.append({
                    'type': 'file',
                    'path': f['path'],
                    'size': f['size']
                })
                existing_paths.add(f['path'])
                
        # 4. Check Junk & Caches
        # For Junk tab, paths are stored in categories. Some are files, some are folders.
        for cat_key, cat in self.junk_categories.items():
            for path in cat['paths']:
                if self.is_path_selected(path) and path not in existing_paths:
                    # Determine type
                    itype = 'folder' if os.path.isdir(path) else 'file'
                    # Get size
                    isize = 0
                    if itype == 'folder':
                        # Find matching DirNode to get calculated size
                        isize = self.find_folder_size_in_tree(path)
                    else:
                        try:
                            isize = os.path.getsize(path)
                        except OSError:
                            pass
                            
                    self.selected_to_delete.append({
                        'type': itype,
                        'path': path,
                        'size': isize
                    })
                    existing_paths.add(path)
                    
        # 5. Check Ghost Apps
        for app in self.ghost_apps:
            if app.get('is_selected', False):
                self.selected_to_delete.append({
                    'type': 'ghost_app',
                    'app': app,
                    'path': f"{app['root_str']}\\{app['path']}",
                    'size': 0
                })

        # Cache aggregated statistics to completely avoid duplicate recalculations on simple cursor movement
        self.reclaim_size = 0
        self.reclaim_files = 0
        self.reclaim_folders = 0
        self.reclaim_registry = 0
        for item in self.selected_to_delete:
            self.reclaim_size += item['size']
            if item['type'] == 'folder':
                self.reclaim_folders += 1
            elif item['type'] == 'ghost_app':
                self.reclaim_registry += 1
            else:
                self.reclaim_files += 1

    def diagnose_performance(self):
        """Runs read-only Win32 performance checkups to isolate background and disk lag bottlenecks safely."""
        self.perf_diagnostics = []
        
        # 1. RAM Utilization Diagnostic
        mem = get_memory_status()
        ram_load = mem['ram_load']
        total_ram_gb = mem['total_phys'] / (1024**3)
        avail_ram_gb = mem['avail_phys'] / (1024**3)
        
        ram_status = "HEALTHY"
        ram_details = f"RAM Load: {ram_load}% | Free: {avail_ram_gb:.2f} GB of {total_ram_gb:.2f} GB total"
        ram_recommend = "No action required. Your physical RAM has ample head-room for running intensive tasks."
        
        if ram_load > 85:
            ram_status = "WARNING"
            ram_recommend = "High RAM load can cause severe page swapping lag. Close active background applications (e.g. Chrome tabs, gaming launchers, IDEs) using Task Manager."
        elif ram_load > 70:
            ram_status = "NOTICE"
            ram_recommend = "Moderate background memory footprint. Consider keeping unused background programs closed to maintain quick game/app loading times."
            
        self.perf_diagnostics.append({
            'category': 'Physical RAM Load',
            'status': ram_status,
            'details': ram_details,
            'recommendation': ram_recommend
        })
        
        # 2. Windows Virtual Memory Swap Space
        total_page_gb = mem['total_page'] / (1024**3)
        avail_page_gb = mem['avail_page'] / (1024**3)
        if total_page_gb > 0:
            page_load = (1.0 - avail_page_gb / total_page_gb) * 100
            page_status = "HEALTHY"
            page_details = f"Virtual Memory Load: {page_load:.1f}% | Free Swap: {avail_page_gb:.2f} GB of {total_page_gb:.2f} GB"
            page_recommend = "Windows virtual swap file allocation is optimally managing memory overflow."
            
            if page_load > 85:
                page_status = "WARNING"
                page_recommend = "Your virtual pagefile is near exhaustion! If physical RAM fills up, Windows will freeze or crash. Open Advanced System Settings and set Virtual Memory to 'Automatically manage paging file size'."
                
            self.perf_diagnostics.append({
                'category': 'Virtual Swap Space',
                'status': page_status,
                'details': page_details,
                'recommendation': page_recommend
            })
            
        # 3. High-Impact Startup Apps
        startup_apps = get_startup_applications()
        startup_count = len(startup_apps)
        
        start_status = "HEALTHY"
        start_details = f"{startup_count} apps configured to launch automatically on Windows boot."
        start_recommend = "Excellent! Your startup load is minimal, keeping boot latency short and background memory lean."
        
        if startup_count > 10:
            start_status = "WARNING"
            start_recommend = f"Too many startup applications ({startup_count}) are configured to run automatically. This severely degrades boot speed and wastes CPU/RAM. Press [Ctrl + Shift + Esc], switch to 'Startup Apps', and disable non-essential programs."
        elif startup_count > 5:
            start_status = "NOTICE"
            start_recommend = f"Moderate startup impact ({startup_count} apps). You can shave seconds off your boot times by disabling non-essential apps in Task Manager."
            
        if startup_apps:
            app_list = ", ".join(app['name'] for app in startup_apps[:6])
            if len(startup_apps) > 6:
                app_list += f" (+ {len(startup_apps) - 6} more)"
            start_details += f" Detected: {app_list}"
            
        self.perf_diagnostics.append({
            'category': 'Boot Startup Apps',
            'status': start_status,
            'details': start_details,
            'recommendation': start_recommend
        })
        
        # 4. Storage Space Capacity Limits
        storage_warnings = []
        sys_drive_letter = os.environ.get('SystemDrive', 'C:').lower()
        if not sys_drive_letter.endswith('\\'):
            sys_drive_letter += '\\'
            
        checked_drives = set()
        for root_node in self.tree_roots:
            # Check capacity in bytes
            for drive in self.drives:
                d_lower = drive['drive'].lower()
                if d_lower == root_node.path.lower() or root_node.path.lower().startswith(d_lower):
                    if d_lower not in checked_drives:
                        checked_drives.add(d_lower)
                        used = drive['used']
                        total = drive['total']
                        pct = (used / total * 100) if total > 0 else 0
                        if pct > 85:
                            storage_warnings.append(f"{drive['drive']} ({pct:.1f}% full)")
                            
        # Always evaluate the system drive capacity as a whole!
        if sys_drive_letter not in checked_drives:
            for drive in self.drives:
                if drive['drive'].lower() == sys_drive_letter:
                    used = drive['used']
                    total = drive['total']
                    pct = (used / total * 100) if total > 0 else 0
                    if pct > 85:
                        storage_warnings.append(f"{drive['drive']} ({pct:.1f}% full)")
                        
        store_status = "HEALTHY"
        store_details = "All scanned storage partitions have healthy headroom."
        store_recommend = "Your drives have plenty of block space, ensuring optimal SSD garbage collection and write speeds."
        
        if storage_warnings:
            store_status = "WARNING"
            store_details = f"High capacity warning on: {', '.join(storage_warnings)}."
            store_recommend = "Solid State Drives (SSDs) lose substantial read/write speed when filled past 85% capacity. Clear out large files or delete detected duplicate groups using StorageClear to restore speed."
            
        self.perf_diagnostics.append({
            'category': 'Storage Capacities',
            'status': store_status,
            'details': store_details,
            'recommendation': store_recommend
        })
        
        # 5. Developer Caches & Temp Junk Footprint
        reclaim_junk_size = 0
        for cat in self.junk_categories.values():
            reclaim_junk_size += cat['size']
            
        junk_status = "HEALTHY"
        junk_details = f"Obsolete caches & logs accumulate to only {format_size(reclaim_junk_size)}."
        junk_recommend = "Excellent cache hygiene. Your drive has no major compiled target bloat."
        
        if reclaim_junk_size > 5 * 1024**3: # 5GB
            junk_status = "WARNING"
            junk_recommend = "Massive compilation target/cache bloat! Deleting these obsolete items in Tab 4 will free up significant gigabytes and speed up drive search/index indexing."
        elif reclaim_junk_size > 1 * 1024**3: # 1GB
            junk_status = "NOTICE"
            junk_recommend = "Consider clearing out these cache targets (Tab 4) to free up storage space and keep your search index highly responsive."
            
        self.perf_diagnostics.append({
            'category': 'Junk & Cache Bloat',
            'status': junk_status,
            'details': junk_details,
            'recommendation': junk_recommend
        })

    def is_path_selected(self, path):
        """Helper to determine if a specific path is selected on the system."""
        # 1. Check Large Files
        if hasattr(self, 'path_to_large_file') and path in self.path_to_large_file:
            return self.path_to_large_file[path].get('is_selected', False)
        else:
            for f in self.large_files:
                if f['path'] == path:
                    return f.get('is_selected', False)
                
        # 2. Check Duplicates
        if hasattr(self, 'path_to_dup_file') and path in self.path_to_dup_file:
            return self.path_to_dup_file[path].get('is_selected', False)
        else:
            for group in self.duplicates:
                for f in group['files']:
                    if f['path'] == path:
                        return f.get('is_selected', False)
                    
        # 3. Check Tree Node or File via O(1) dictionary
        if hasattr(self, 'path_to_node') and path in self.path_to_node:
            return get_selection_state(self.path_to_node[path]) == 'all'
        elif hasattr(self, 'path_to_tree_file') and path in self.path_to_tree_file:
            return self.path_to_tree_file[path].get('is_selected', False)
            
        return False

    def toggle_path_selection(self, path, is_selected):
        """Sets selection state for a specific file or folder path across all views."""
        # 1. Update Large Files
        if hasattr(self, 'path_to_large_file') and path in self.path_to_large_file:
            self.path_to_large_file[path]['is_selected'] = is_selected
        else:
            for f in self.large_files:
                if f['path'] == path:
                    f['is_selected'] = is_selected
                
        # 2. Update Duplicates
        if hasattr(self, 'path_to_dup_file') and path in self.path_to_dup_file:
            self.path_to_dup_file[path]['is_selected'] = is_selected
        else:
            for group in self.duplicates:
                for f in group['files']:
                    if f['path'] == path:
                        f['is_selected'] = is_selected
                    
        # 3. Update Tree via O(1) dictionary
        if hasattr(self, 'path_to_node') and path in self.path_to_node:
            set_node_selection(self.path_to_node[path], is_selected)
        elif hasattr(self, 'path_to_tree_file') and path in self.path_to_tree_file:
            self.path_to_tree_file[path]['is_selected'] = is_selected

    def find_folder_size_in_tree(self, path):
        """Finds the aggregated size of a folder path from pre-scanned Tree Nodes."""
        if hasattr(self, 'path_to_node') and path in self.path_to_node:
            return self.path_to_node[path].size
            
        def find(node):
            if node.path == path:
                return node.size
            for s in node.subdirs.values():
                res = find(s)
                if res:
                    return res
            return 0
        for root in self.tree_roots:
            res = find(root)
            if res:
                return res
        return 0

    def update_visible_items(self):
        """Reconstructs flat visible list corresponding to active tab."""
        self.visible_items = []
        
        if self.current_tab == 0: # 1. Directory Tree
            def add_node(node, depth):
                self.visible_items.append({
                    'type': 'folder',
                    'node': node,
                    'depth': depth
                })
                if node.is_expanded:
                    # Show files in folder
                    for f in node.files:
                        self.visible_items.append({
                            'type': 'file',
                            'file': f,
                            'node': node,
                            'depth': depth + 1
                        })
                    # Show subdirs sorted by size descending
                    sorted_subdirs = sorted(node.subdirs.values(), key=lambda x: x.size, reverse=True)
                    for s in sorted_subdirs:
                        add_node(s, depth + 1)

            # Sort roots
            sorted_roots = sorted(self.tree_roots, key=lambda x: x.size, reverse=True)
            for r in sorted_roots:
                add_node(r, 0)
                
        elif self.current_tab == 1: # 2. Duplicates
            for group in self.duplicates:
                self.visible_items.append({
                    'type': 'header',
                    'group': group
                })
                for idx, f in enumerate(group['files']):
                    self.visible_items.append({
                        'type': 'item',
                        'file': f,
                        'index': idx,
                        'group': group
                    })
                    
        elif self.current_tab == 2: # 3. Large Files
            for f in self.large_files:
                self.visible_items.append({
                    'type': 'file',
                    'file': f
                })
                
        elif self.current_tab == 3: # 4. Junk/Caches
            for cat_key, cat in self.junk_categories.items():
                self.visible_items.append({
                    'type': 'header',
                    'cat_key': cat_key
                })
                # Show individual paths
                for p in cat['paths']:
                    # Try to fetch size
                    size = 0
                    if os.path.isdir(p):
                        size = self.find_folder_size_in_tree(p)
                    else:
                        try:
                            size = os.path.getsize(p)
                        except OSError:
                            pass
                    self.visible_items.append({
                        'type': 'item',
                        'path': p,
                        'size': size,
                        'cat_key': cat_key
                    })
                    
        elif self.current_tab == 4: # 5. Ghost App Cleaner
            for app in self.ghost_apps:
                self.visible_items.append({
                    'type': 'ghost_app',
                    'app': app
                })
                
        elif self.current_tab == 5: # 6. PC Performance Boost
            for item in self.perf_diagnostics:
                self.visible_items.append({
                    'type': 'perf_header',
                    'diag': item
                })
                self.visible_items.append({
                    'type': 'perf_details',
                    'diag': item
                })
                self.visible_items.append({
                    'type': 'perf_recommend',
                    'diag': item
                })
                self.visible_items.append({
                    'type': 'perf_spacer',
                    'diag': item
                })

    # --- ACTIONS & OPERATIONS ---

    def run_scan(self):
        """Launches the recursive scanner generator, feeding live results into scanning screen."""
        self.state = "scanning"
        clear_screen()
        self.render()
        
        # Build clean scan list
        scan_paths = list(self.selected_drives)
        if getattr(self, 'run_diagnostics_opt', False):
            sys_drive = os.environ.get('SystemDrive', 'C:')
            if not sys_drive.endswith('\\'):
                sys_drive += '\\'
            if sys_drive not in scan_paths:
                scan_paths.append(sys_drive)
                
        scan_gen = scan_directory(scan_paths)
        
        while True:
            # Check for Esc key to abort scan
            if msvcrt.kbhit():
                char = msvcrt.getch()
                if char == b'\x1b': # Esc key
                    self.state = "drive_selector"
                    self.active_index = 0
                    clear_screen()
                    return
            
            try:
                event, data = next(scan_gen)
                if event == 'progress':
                    self.dirs_scanned = data['dirs_scanned']
                    self.files_scanned = data['files_scanned']
                    self.total_size = data['total_size']
                    # Use visible_items as a quick cache to pass current scanning directory path to renderer
                    self.visible_items = [data['current_path']]
                    self.render()
                elif event == 'done':
                    self.tree_roots = data['tree_roots']
                    self.all_files = data['all_files']
                    self.total_size = data['total_size']
                    
                    # Expand roots by default
                    for r in self.tree_roots:
                        r.is_expanded = True
                        
                    # Set is_analyzing to trigger final phase redraw
                    self.is_analyzing = True
                    self.render()
                    
                    # Build fast O(1) path mapping for the tree nodes and files
                    self.path_to_node = {}
                    self.path_to_tree_file = {}
                    
                    def index_tree(node):
                        self.path_to_node[node.path] = node
                        for f in node.files:
                            self.path_to_tree_file[os.path.join(node.path, f['name'])] = f
                        for s in node.subdirs.values():
                            index_tree(s)
                            
                    for root in self.tree_roots:
                        index_tree(root)
                        
                    # Pre-calculate recommendation lists
                    self.large_files = get_large_files(self.all_files)
                    self.duplicates = find_duplicate_files(self.all_files)
                    
                    # Build fast O(1) maps for duplicates and large files
                    self.path_to_dup_file = {}
                    for group in self.duplicates:
                        for f in group['files']:
                            self.path_to_dup_file[f['path']] = f
                            
                    self.path_to_large_file = {}
                    for f in self.large_files:
                        self.path_to_large_file[f['path']] = f
                    
                    # Auto check duplicates except the primary copy
                    for group in self.duplicates:
                        for idx, f in enumerate(group['files']):
                            if idx > 0:
                                f['is_selected'] = True
                                
                    self.junk_categories = find_junk_and_cache(self.tree_roots)
                    
                    # Auto select junk/caches by default
                    for cat in self.junk_categories.values():
                        for p in cat['paths']:
                            self.toggle_path_selection(p, True)
                            
                    # Query ghost registry entries
                    self.ghost_apps = get_ghost_applications()
                    
                    # Run system-wide performance diagnosis if option checked
                    if getattr(self, 'run_diagnostics_opt', False):
                        self.diagnose_performance()
                        
                    # Calculate initial reclaim stats once
                    self.calculate_reclaim_stats()
                    
                    self.is_analyzing = False
                    
                    self.state = "dashboard"
                    self.current_tab = 5 if (getattr(self, 'run_diagnostics_opt', False) and not self.selected_drives) else 0
                    self.active_index = 0
                    self.scroll_top = 0
                    clear_screen()
                    break
            except StopIteration:
                break
                
            # Slow down slightly to prevent thread starvation and allow smooth animations
            time.sleep(0.005)

    def execute_deletion(self, use_recycle_bin=True):
        """Runs the file deleting operations and registry purges in a safe process."""
        self.state = "deleting"
        clear_screen()
        
        total_items = len(self.selected_to_delete)
        self.failed_registry_permissions = []
        
        for idx, item in enumerate(self.selected_to_delete):
            self.visible_items = [f"({idx+1}/{total_items}) {item['path']}"]
            self.render()
            
            if item['type'] == 'ghost_app':
                app = item['app']
                try:
                    delete_registry_key_recursive(app['root'], app['path'])
                except PermissionError:
                    self.failed_registry_permissions.append(app)
                except Exception:
                    pass
            else:
                path = item['path']
                if os.path.exists(path):
                    try:
                        if use_recycle_bin:
                            send_to_recycle_bin([path])
                        else:
                            delete_permanently([path])
                    except Exception:
                        pass # Ignore locked files during bulk cleans
                    
        self.state = "done"
        clear_screen()

    # --- EVENT & KEYBOARD HANDLERS ---

    def handle_input(self):
        """Processes keyboard scans. Returns True to quit the TUI application."""
        if not msvcrt.kbhit():
            time.sleep(0.01) # Sleep to keep CPU idle!
            return False

        key = msvcrt.getch()
        
        # Handle special/escape/arrow sequences on Windows
        if key in (b'\x00', b'\xe0'):
            # Arrow key codes
            subkey = msvcrt.getch()
            if self.state in ("drive_selector", "dashboard"):
                if subkey == b'H': # Up arrow
                    self.active_index = max(0, self.active_index - 1)
                elif subkey == b'P': # Down arrow
                    items_len = (len(self.drives) + 1) if self.state == "drive_selector" else len(self.visible_items)
                    self.active_index = min(items_len - 1, self.active_index + 1)
                elif subkey == b'K': # Left arrow (collapse in tree, or prev tab)
                    if self.state == "dashboard":
                        if self.current_tab == 0:
                            item = self.visible_items[self.active_index]
                            if item['type'] == 'folder' and item['node'].is_expanded:
                                item['node'].is_expanded = False
                        else:
                            num_tabs = 6 if getattr(self, 'run_diagnostics_opt', False) else 5
                            self.current_tab = (self.current_tab - 1) % num_tabs
                            self.active_index = 0
                            self.scroll_top = 0
                            clear_screen()
                elif subkey == b'M': # Right arrow (expand in tree, or next tab)
                    if self.state == "dashboard":
                        if self.current_tab == 0:
                            item = self.visible_items[self.active_index]
                            if item['type'] == 'folder' and not item['node'].is_expanded:
                                item['node'].is_expanded = True
                        else:
                            num_tabs = 6 if getattr(self, 'run_diagnostics_opt', False) else 5
                            self.current_tab = (self.current_tab + 1) % num_tabs
                            self.active_index = 0
                            self.scroll_top = 0
                            clear_screen()
            return False

        # Regular ASCII keys
        if key == b'\x1b': # Escape key
            if self.state == "confirmation":
                self.state = "dashboard"
                clear_screen()
            return False
            
        elif key == b'\r': # Enter key
            if self.state == "drive_selector":
                if self.selected_drives or getattr(self, 'run_diagnostics_opt', False):
                    self.run_scan()
            elif self.state == "dashboard":
                if self.current_tab == 0:
                    item = self.visible_items[self.active_index]
                    if item['type'] == 'folder':
                        item['node'].is_expanded = not item['node'].is_expanded
            elif self.state == "done":
                self.state = "dashboard"
                self.selected_to_delete = []
                self.large_files = get_large_files(self.all_files)
                self.duplicates = find_duplicate_files(self.all_files)
                self.junk_categories = find_junk_and_cache(self.tree_roots)
                self.active_index = 0
                self.scroll_top = 0
                clear_screen()
            return False
            
        elif key == b' ': # Space key
            if self.state == "drive_selector":
                if self.active_index < len(self.drives):
                    drive = self.drives[self.active_index]['drive']
                    if drive in self.selected_drives:
                        # Allow deselection of the last drive only if diagnostics toggle is enabled
                        if getattr(self, 'run_diagnostics_opt', False) or len(self.selected_drives) > 1:
                            self.selected_drives.remove(drive)
                    else:
                        self.selected_drives.add(drive)
                else:
                    self.run_diagnostics_opt = not self.run_diagnostics_opt
                    # Auto-select the system drive as the target path when checked!
                    if self.run_diagnostics_opt:
                        sys_drive = os.environ.get('SystemDrive', 'C:')
                        if not sys_drive.endswith('\\'):
                            sys_drive += '\\'
                        self.selected_drives.add(sys_drive)
                    # Auto-select first drive as a safety fallback if they disable diagnostics with empty drives
                    elif not self.selected_drives and self.drives:
                        self.selected_drives.add(self.drives[0]['drive'])
            elif self.state == "dashboard":
                self.toggle_active_item_selection()
            return False
            
        elif key == b'\t': # Tab key
            if self.state == "dashboard":
                num_tabs = 6 if getattr(self, 'run_diagnostics_opt', False) else 5
                self.current_tab = (self.current_tab + 1) % num_tabs
                self.active_index = 0
                self.scroll_top = 0
                clear_screen()
            return False
            
        # Hotkeys for direct tab navigation
        elif key in (b'1', b'2', b'3', b'4', b'5', b'6'):
            if self.state == "dashboard":
                val = int(key.decode()) - 1
                num_tabs = 6 if getattr(self, 'run_diagnostics_opt', False) else 5
                if val < num_tabs:
                    self.current_tab = val
                    self.active_index = 0
                    self.scroll_top = 0
                    clear_screen()
            return False
            
        elif key in (b'd', b'D'): # Delete key command
            if self.state == "dashboard":
                self.calculate_reclaim_stats()
                if self.selected_to_delete:
                    self.state = "confirmation"
                    clear_screen()
            return False
            
        elif key in (b'r', b'R'): # Re-scan drive
            if self.state in ("dashboard", "done"):
                clear_screen()
                self.run_scan()
            return False
            
        elif key in (b'q', b'Q'): # Quit
            return True
            
        elif key in (b'y', b'Y', b'p', b'P'): # Confirm Deletion actions
            if self.state == "confirmation":
                permanent = (key in (b'p', b'P'))
                self.execute_deletion(use_recycle_bin=not permanent)
            return False
            
        return False

    def toggle_active_item_selection(self):
        """Sets selections for highlighting items when Spacebar is pressed."""
        if not self.visible_items:
            return
            
        item = self.visible_items[self.active_index]
        
        if self.current_tab == 0: # 1. Directory Tree
            if item['type'] == 'folder':
                node = item['node']
                new_state = not (get_selection_state(node) == 'all')
                set_node_selection(node, new_state)
            else:
                f = item['file']
                f['is_selected'] = not f.get('is_selected', False)
                
        elif self.current_tab == 1: # 2. Duplicates
            if item['type'] == 'header':
                # Toggle all duplicate files in this group
                group = item['group']
                # Determine if all are selected
                all_sel = all(f.get('is_selected', False) for f in group['files'])
                for f in group['files']:
                    f['is_selected'] = not all_sel
            else:
                f = item['file']
                f['is_selected'] = not f.get('is_selected', False)
                
        elif self.current_tab == 2: # 3. Large Files
            f = item['file']
            f['is_selected'] = not f.get('is_selected', False)
            
        elif self.current_tab == 3: # 4. Junk/Caches
            if item['type'] == 'header':
                cat = self.junk_categories[item['cat_key']]
                all_sel = all(self.is_path_selected(p) for p in cat['paths'])
                for p in cat['paths']:
                    self.toggle_path_selection(p, not all_sel)
            else:
                p = item['path']
                self.toggle_path_selection(p, not self.is_path_selected(p))
                
        elif self.current_tab == 4: # 5. Ghost App Cleaner
            app = item['app']
            app['is_selected'] = not app.get('is_selected', False)

        # Recalculate and update the cached statistics since selection state changed!
        self.calculate_reclaim_stats()
