# Contributing to StorageClear

Thank you for your interest in contributing to **StorageClear**! We welcome developer optimizations, bug fixes, and feature additions to make deep storage reclaiming even faster.

## How Can I Contribute?

### Reporting Bugs
If you find a bug (such as a directory loop hang, a Win32 driver timeout, or a console display glitch), please open a GitHub Issue and include:
* Your exact Windows version.
* The error traceback from the console.
* Steps to reproduce the issue.

### Proposing Features
Have ideas for targeted directory maps, Treemap HTML exports, or new cache detectors? Open a GitHub Issue to discuss it first before diving into code.

## Development Setup

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/YOUR_USERNAME/storageclear.git
   cd storageclear
   ```

2. **Run Tests**:
   Before modifying code, confirm that all mock filesystem tests pass successfully:
   ```bash
   python scratch/verify_system.py
   ```

3. **Code Style**:
   * Follow PEP 8 style guidelines.
   * Write clean, self-documenting code with descriptive inline comments.
   * Ensure any filesystem or registry operations employ proper try/except guardrails to fail-safe against administrative permission limits or file-locking conflicts.

4. **Submitting Changes**:
   * Create a feature branch: `git checkout -b feature/cool-new-optimization`.
   * Commit your changes: `git commit -m "Optimize folder size traversals using lookup maps"`.
   * Push to your fork and submit a Pull Request (PR) describing what your code accomplishes.
