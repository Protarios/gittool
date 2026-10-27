"""Generate native application icons from GitTool's single packaged PNG asset.

Usage:
    python scripts/create_icons.py

Pillow is a *build-time* dependency only; GitTool itself uses Qt to load PNG.
"""
from __future__ import annotations

from pathlib import Path
import sys

from PIL import Image


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "gittool" / "assets" / "gittool.png"
OUTPUT = ROOT / "build" / "icons"


def main() -> int:
    if not SOURCE.is_file():
        raise FileNotFoundError(f"GitTool PNG-Icon fehlt: {SOURCE}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with Image.open(SOURCE) as original:
        image = original.convert("RGBA")
        icon_256 = image.resize((256, 256), Image.Resampling.LANCZOS)
        ico = OUTPUT / "GitTool.ico"
        icon_256.save(
            ico,
            format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32),
                   (48, 48), (64, 64), (128, 128), (256, 256)],
        )
        print(f"Windows-Icon: {ico}")
        if sys.platform == "darwin":
            icns = OUTPUT / "GitTool.icns"
            image.resize((1024, 1024), Image.Resampling.LANCZOS).save(
                icns, format="ICNS",
            )
            print(f"macOS-Icon: {icns}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
