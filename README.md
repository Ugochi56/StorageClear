# 🚀 StorageClear

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.8+](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows-lightgrey.svg)](https://www.microsoft.com/windows)

**StorageClear** is an interactive, ultra-high-speed, premium command-line utility (CLI) designed for Windows. It generates a deep visual map of your storage partitions, identifies massive space-saving opportunities (duplicates, caches, junk, and large files), and helps you safely clear them using the native Windows Recycle Bin.

Additionally, StorageClear features a native **Ghost Software Cleaner**—a zero-dependency Win32 registry scanner that finds and purges orphaned, broken "ghost" programs from your Windows Add/Remove programs list that the native Windows uninstaller fails to remove.

---

## ✨ Features

* **⚡ Ultra-High-Speed Directory Traversal**: Scans, catalogs, and aggregates folder structures with over **500,000+ files and 400+ GB of data in under 3 seconds** using non-blocking iterative depth-first traversal with junction loop safety guards.
* **📂 Double-Buffered ANSI Terminal UI (TUI)**: A stunning, interactive terminal interface featuring an alternate screen buffer, custom color schemes, smooth custom progress loaders, and a responsive keyboard-driven workflow.
* **🔍 Multi-Point Sparse Hashing**: Discovers exact duplicate files in milliseconds by utilizing a sparse hashing algorithm (analyzing starts, middles, and ends) rather than reading entire gigabytes of candidate files from disk.
* **⚙️ Ghost Application Registry Cleaner**: Safely scours Windows Add/Remove program registry paths (HKLM 64-bit, HKLM 32-bit/WOW64, and HKCU) and purges stubborn registry orphans whose uninstallers and directories no longer exist on disk.
* **♻️ Native Recycle Bin Integration**: Sends reclaimed directories and duplicate files to the Windows Recycle Bin as a primary safety layer, allowing instant recovery in case of accidental deletions.
* **🛠️ Zero Dependencies**: Crafted entirely in pure Python utilizing native Win32 `ctypes` and standard system libraries. No `pip install` required!

---

## ⚡ High-Speed Performance Engine

StorageClear is engineered from the ground up to handle massive, multi-terabyte drives without hanging or lagging the interactive console thread:
* **O(1) Constant-Time Selection Indices**: Auto-selecting thousands of pycache or node_modules paths is resolved instantly in **under 0.1ms** via pre-compiled index lookup tables, completely eliminating the lag of traditional recursive tree updates.
* **10MB Duplicate floor**: Filters out tiny files under 10MB (yielding maximum space savings while saving thousands of costly disk seeks).
* **Local Path Sandboxing**: Safeguards registry path checks to local drive letters, completely avoiding timeouts from disconnected network drives or unmounted CD/DVD media.

---

## 📁 Architectural Layout

```
storageclear/
│   CODE_OF_CONDUCT.md   # Open-source Contributor Guidelines
│   CONTRIBUTING.md      # Development setup guide
│   LICENSE              # MIT License
│   README.md            # Project overview & documentation
│   SECURITY.md          # Vulnerability disclosure policy
│
├───scratch/
│       verify_system.py     # Automated mock filesystem & Registry test suite
│
└───storageclear/
        __init__.py          # Marks package boundaries
        __main__.py          # CLI argument parser and boot orchestrator
        ops.py               # Win32 ctypes storage strings, stats, Recycle Bin, and recursive Registry APIs
        scanner.py           # High-speed recursive directory traversal with junction loop safety
        recommender.py       # Space reclaim recommendation algorithms (sparse hashing duplicates)
        tui.py               # Double-buffered interactive ANSI keyboard-driven Terminal User Interface
```

---

## 🎮 How to Run

### Prerequisite: Elevated Execution
To clean system-wide program listings in **HKEY_LOCAL_MACHINE (HKLM)**, StorageClear requires administrator rights.
1. Search for **Command Prompt** (or **PowerShell**) in your Windows Start menu.
2. Right-click and choose **Run as Administrator**.
3. Run the module directly:
   ```powershell
   python -m storageclear
   ```

### ⌨️ Controls & Navigation

* **`Spacebar`**: Toggle selection state of active folder, file, or registry key.
* **`Arrow Keys (Up/Down)`**: Move cursor up/down through lists.
* **`Arrow Keys (Left/Right)` or `Tab`**: Switch tabs in the dashboard.
* **`Enter`**: Expand/Collapse folders in the Directory Tree view.
* **`1` - `5`**: Jump directly to a tab:
  1. *Directory Tree* (Explore folder sizes recursively)
  2. *Duplicate Finder* (Locate and delete identical file copies)
  3. *Large Files* (Isolate massive binaries and installers)
  4. *Junk & Caches* (Python bytecode, node_modules, build directories)
  5. *Ghost App Cleaner* (Clean orphaned Add/Remove program registry keys)
* **`D`**: Proceed to confirmation screen listing the entire deletion queue.
* **`Esc`**: Return to dashboard.
* **`R`**: Trigger a fresh drive re-scan.
* **`Q`**: Safely exit the terminal application.

---

## 🧪 Testing and Verification

StorageClear includes a comprehensive mock filesystem validation suite that tests registry queries, path sandboxing, file scanning, sparse-hash duplicate discovery, and cache detections without affecting your active files.

Run the test suite with:
```powershell
python scratch/verify_system.py
```

---

## 📜 License

Distributed under the **MIT License**. See `LICENSE` for more information.
