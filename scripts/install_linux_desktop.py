"""Install or remove a user-local Linux desktop launcher for the GTK build.

Run with the Python interpreter / venv in which GitTool is installed:
    python scripts/install_linux_desktop.py
    python scripts/install_linux_desktop.py --uninstall
No root privileges, network access or GTK imports are needed.
"""
from __future__ import annotations

import argparse
from importlib import resources
import os
from pathlib import Path
import sys


APP_ID = "io.github.protarios.gittool"


def desktop_argument(value: str) -> str:
    """Quote one Desktop Entry Exec token (freedesktop desktop-entry spec)."""
    escaped = (value.replace("\\", "\\\\")
               .replace('"', '\\"')
               .replace("$", "\\$")
               .replace("`", "\\`"))
    return f'"{escaped}"'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uninstall", action="store_true",
                        help="Benutzerspezifischen Starter und dessen Icon entfernen")
    args = parser.parse_args()
    xdg_data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    desktop = xdg_data / "applications" / f"{APP_ID}.desktop"
    icon = xdg_data / "icons" / "hicolor" / "192x192" / "apps" / f"{APP_ID}.png"

    if args.uninstall:
        desktop.unlink(missing_ok=True)
        icon.unlink(missing_ok=True)
        print("GitTool-Desktopstarter entfernt.")
        return 0

    if os.name == "nt":
        parser.error("Dieser Desktopstarter ist nur für Linux/Unix gedacht.")
    artwork = resources.files("gittool").joinpath("assets", "gittool.png").read_bytes()
    desktop.parent.mkdir(parents=True, exist_ok=True)
    icon.parent.mkdir(parents=True, exist_ok=True)
    icon.write_bytes(artwork)
    command = f"{desktop_argument(str(Path(sys.executable).resolve()))} -m gittool"
    content = (
        "[Desktop Entry]\n"
        "Version=1.0\n"
        "Type=Application\n"
        "Name=GitTool\n"
        "Comment=Git-Repositories prüfen und sicher aktualisieren\n"
        f"Exec={command}\n"
        f"Icon={APP_ID}\n"
        "Terminal=false\n"
        "StartupNotify=true\n"
        "Categories=Development;RevisionControl;\n"
    )
    desktop.write_text(content, encoding="utf-8")
    desktop.chmod(0o644)
    print(f"Desktopstarter installiert: {desktop}")
    print(f"Icon installiert: {icon}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
