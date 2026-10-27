"""Load the bundled cross-platform GitTool application icon for Qt.

Keep the artwork as package data, not a working-directory relative path, so
python -m gittool, installed entrypoints, wheels and PyInstaller all agree.
"""
from __future__ import annotations

from importlib import resources

from PySide6.QtGui import QIcon, QPixmap


def application_icon() -> QIcon:
    """Load the same transparent PNG on Windows, Linux and macOS."""
    asset = resources.files("gittool").joinpath("assets", "gittool.png")
    image = QPixmap()
    if not image.loadFromData(asset.read_bytes(), "PNG"):
        raise RuntimeError(f"GitTool-Icon konnte nicht gelesen werden: {asset}")
    return QIcon(image)
