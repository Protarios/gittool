"""Regression tests for the Windows-compatible PySide6 interface."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

# Rendering a native window is unnecessary for the automated GUI smoke test.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, Qt  # noqa: E402
import shiboken6  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from gittool.app import GitToolWindow  # noqa: E402
from gittool.backend import RepositoryState  # noqa: E402
from gittool.status_style import visual_status  # noqa: E402


class QtGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt_app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Never pick up or modify real user configuration during tests.
        with patch("gittool.app.load_repository_entries", return_value=[]):
            self.window = GitToolWindow()
        self.path = Path(self.tmp.name).resolve()

    def tearDown(self) -> None:
        self.window.close()
        shiboken6.delete(self.window)
        self.window = None
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.qt_app.quit()
        cls.qt_app.processEvents()
        shiboken6.delete(cls.qt_app)
        cls.qt_app = None

    def test_window_creation_and_actions(self) -> None:
        self.assertIn("GitTool", self.window.windowTitle())
        self.assertEqual(self.window.tree.columnCount(), 8)
        self.assertFalse(self.window.all_check.isEnabled())
        self.assertFalse(self.window.all_pull.isEnabled())

    def test_add_select_and_remove_repository(self) -> None:
        self.assertTrue(self.window._register_repository(self.path, persist=False))
        self.assertFalse(self.window._register_repository(self.path, persist=False))
        self.assertEqual(self.window.tree.topLevelItemCount(), 1)
        self.assertTrue(self.window.all_check.isEnabled())
        self.assertTrue(self.window.all_pull.isEnabled())

        item = self.window.items[str(self.path)]
        item.setSelected(True)
        self.assertEqual(self.window._selected_paths(), [self.path])
        self.assertTrue(self.window.selected_pull.isEnabled())

        with patch("gittool.app.save_repository_entries"):
            self.window._remove_selected()
        self.assertEqual(len(self.window.repositories), 0)
        self.assertEqual(self.window.tree.topLevelItemCount(), 0)

    def test_status_colors_and_search(self) -> None:
        self.window._register_repository(self.path, persist=False)
        state = RepositoryState(
            path=self.path, branch="gpt", upstream="origin/gpt",
            ahead=0, behind=2, dirty=False, status="Pull möglich", can_pull=True,
        )
        self.window._display_state(state)
        item = self.window.items[str(self.path)]
        self.assertIn("Pull möglich", item.text(6))
        self.assertTrue(item.background(6).color().isValid())
        self.assertEqual(item.text(5), "2")
        self.assertEqual(item.text(2), "origin/gpt")
        self.assertIn("1 Pull möglich", self.window.summary.text())
        self.window.search.setText("origin/gpt")
        self.assertFalse(item.isHidden())
        self.window.search.setText("something-that-does-not-exist")
        self.assertTrue(item.isHidden())

        self.window.search.clear()
        self.window._on_error(self.path, "Simulierter Fehler")
        self.assertIn("Fehler", item.text(6))
        self.assertIn("1 blockiert", self.window.summary.text())


    def test_submodule_groups_and_move_controls(self) -> None:
        parent = self.path
        sibling = self.path.parent / "another"
        child = parent / "modules" / "inner"
        with patch("gittool.app.discover_submodules", return_value=[(child, parent)]):
            self.assertTrue(self.window._register_repository(parent, persist=False))
        with patch("gittool.app.discover_submodules", return_value=[]):
            self.assertTrue(self.window._register_repository(sibling, persist=False))
        self.assertEqual(self.window.repositories, [parent, child, sibling])
        self.assertEqual(self.window.items[str(parent)].childCount(), 1)
        self.assertEqual(self.window.items[str(child)].parent(), self.window.items[str(parent)])
        item = self.window.items[str(parent)]
        item.setSelected(True)
        with patch("gittool.app.save_repository_entries"):
            self.window._move_selected(+1)
        self.assertEqual(self.window.repositories, [sibling, parent, child])
        self.assertEqual(self.window.catalog.find(child).parent, parent)

    def test_visual_status_categories(self) -> None:
        expectations = {
            "Aktuell": "ok", "Pull möglich": "info",
            "Lokale Änderungen": "warn", "Nur lokal voraus": "warn",
            "Divergiert": "error", "Detached HEAD": "error",
            "Fehler": "error", "Nicht geprüft": "muted",
        }
        for status, color in expectations.items():
            with self.subTest(status=status):
                self.assertEqual(visual_status(status)[1], color)


if __name__ == "__main__":
    unittest.main()
