"""GUI regressions: colors and an actual GTK window smoke test when available."""
from __future__ import annotations

import ast
import os
from pathlib import Path
import unittest

from gittool.status_style import visual_status


class StatusColorTests(unittest.TestCase):
    def test_statuses_have_distinct_theme_colors(self) -> None:
        expected = {
            "Aktuell": "ok",
            "Pull möglich": "info",
            "Lokale Änderungen": "warn",
            "Nur lokal voraus": "warn",
            "Divergiert": "error",
            "Detached HEAD": "error",
            "Fehler": "error",
            "Nicht geprüft": "muted",
        }
        for status, color in expected.items():
            with self.subTest(status=status):
                label, category, icon = visual_status(status)
                self.assertTrue(label)
                self.assertEqual(category, color)
                self.assertTrue(icon.endswith("-symbolic"))

    def test_gui_is_gtk4_and_does_not_override_internal_register(self) -> None:
        path = Path(__file__).resolve().parents[1] / "gittool" / "app.py"
        code = path.read_text(encoding="utf-8")
        tree = ast.parse(code)
        methods = {
            item.name
            for cls in tree.body if isinstance(cls, ast.ClassDef)
            for item in cls.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertNotIn("_register", methods)
        self.assertIn("_register_repository", methods)
        self.assertIn('gi.require_version("Gtk", "4.0")', code)
        self.assertIn('gi.require_version("Adw", "1")', code)
        self.assertNotIn("tkinter", code)

    @unittest.skipUnless(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
                         "Keine grafische Linux-Sitzung vorhanden")
    def test_gtk_window_starts(self) -> None:
        try:
            import gi
            gi.require_version("Gtk", "4.0")
            gi.require_version("Adw", "1")
            from gi.repository import Gtk
            from gittool.app import GitToolApp
        except (ImportError, ValueError) as exc:
            self.skipTest(f"GTK-Bindings nicht installiert: {exc}")

        application = GitToolApp()
        self.assertTrue(application.register(None))
        application.activate()
        try:
            self.assertIsNotNone(application.window)
            self.assertIsInstance(application.window, Gtk.Window)
            self.assertTrue(application.listbox is not None)
            self.assertIsNotNone(application.all_pull)
        finally:
            if application.window is not None:
                application.window.close()
            application.quit()


if __name__ == "__main__":
    unittest.main()
