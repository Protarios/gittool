"""PyInstaller entry point: use absolute package imports outside gittool/__main__.py."""
from gittool.app import main

if __name__ == "__main__":
    raise SystemExit(main())
