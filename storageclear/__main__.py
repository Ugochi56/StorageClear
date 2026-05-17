import sys
import argparse
from storageclear.tui import TUIApp

def main():
    parser = argparse.ArgumentParser(description="StorageClear - Deep Disk Mapper & Space Reclaim System")
    parser.add_argument('paths', metavar='PATH', type=str, nargs='*',
                        help='Direct folder paths to scan immediately (skips partition drive selector)')
    args = parser.parse_args()

    # Pre-parse drive letter shortcuts (e.g. C: -> C:\)
    start_paths = []
    if args.paths:
        for path in args.paths:
            cleaned_path = path
            if sys.platform == 'win32' and len(path) == 2 and path[1] == ':':
                cleaned_path = path + '\\'
            start_paths.append(cleaned_path)
            
    app = TUIApp(start_paths=start_paths if start_paths else None)
    app.run()

if __name__ == '__main__':
    main()
