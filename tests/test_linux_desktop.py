"""Linux desktop launcher and bundled icon regression tests."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(os.name == "posix", "XDG desktop integration is Linux-only")
class DesktopLauncherTests(unittest.TestCase):
    def test_install_and_uninstall_are_local_and_reversible(self) -> None:
        script = Path(__file__).resolve().parents[1] / "scripts" / "install_linux_desktop.py"
        app_id = "io.github.protarios.gittool"
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "XDG_DATA_HOME": tmp}
            proc = subprocess.run(
                [sys.executable, str(script)], env=env,
                capture_output=True, text=True, check=True,
            )
            desktop = Path(tmp) / "applications" / f"{app_id}.desktop"
            icon = Path(tmp) / "icons/hicolor/192x192/apps" / f"{app_id}.png"
            self.assertTrue(desktop.is_file(), proc.stdout)
            self.assertGreater(icon.stat().st_size, 1000)
            content = desktop.read_text(encoding="utf-8")
            self.assertIn(f"Icon={app_id}", content)
            self.assertIn("Terminal=false", content)
            self.assertIn("-m gittool", content)
            self.assertIn(sys.executable, content)

            subprocess.run(
                [sys.executable, str(script), "--uninstall"], env=env,
                check=True, capture_output=True, text=True,
            )
            self.assertFalse(desktop.exists())
            self.assertFalse(icon.exists())


if __name__ == "__main__":
    unittest.main()
