#!/usr/bin/env bash
# Portable Linux AppImage for the current GitTool frontend (GTK4 or Qt6).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p build dist
if grep -q 'PySide6_Essentials' pyproject.toml; then
  variant="Qt"
else
  variant="GTK"
fi

# Only the native frontend entry point differs; both use one Git backend.
cat > build/appimage_launcher.py <<'PY'
from gittool.app import main

if __name__ == "__main__":
    raise SystemExit(main())
PY

options=(
  --noconfirm --clean --onedir --windowed
  --name GitTool
  --paths .
  --collect-data gittool
  --collect-submodules gittyup
)
if [[ "$variant" == "GTK" ]]; then
  # PyInstaller GI hooks collect the required GTK4/adwaita typelibs and libs.
  options+=(
    --hidden-import gi.repository.Gtk
    --hidden-import gi.repository.Adw
    --hidden-import gi.repository.Gdk
    --hidden-import gi.repository.Gio
    --hidden-import gi.repository.Pango
    --hidden-import gi.repository.GLib
    --collect-submodules gi
  )
fi
python -m PyInstaller "${options[@]}" build/appimage_launcher.py

appdir="$PWD/build/GitTool-$variant.AppDir"
rm -rf "$appdir"
mkdir -p "$appdir/usr/lib/gittool" "$appdir/usr/share/applications"
cp -a dist/GitTool/. "$appdir/usr/lib/gittool/"
cp gittool/assets/gittool.png "$appdir/gittool.png"
cp gittool/assets/gittool.png "$appdir/.DirIcon"

cat > "$appdir/GitTool.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=GitTool ($variant)
Comment=Git repositories safely update and inspect
Exec=GitTool
Icon=gittool
Categories=Development;RevisionControl;
Terminal=false
DESKTOP

cat > "$appdir/AppRun" <<'SH'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/gittool/GitTool" "$@"
SH
chmod +x "$appdir/AppRun"

appimagetool="$PWD/build/appimagetool-x86_64.AppImage"
if [[ ! -f "$appimagetool" ]]; then
  curl --fail --location --retry 3 --silent --show-error \
    https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage \
    --output "$appimagetool"
  chmod +x "$appimagetool"
fi

output="$PWD/dist/GitTool-$variant-x86_64.AppImage"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$appimagetool" "$appdir" "$output"
chmod +x "$output"
echo "AppImage created: $output"
