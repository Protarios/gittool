"""Regression tests for the Windows-compatible PySide6 interface."""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

# Rendering a native window is unnecessary for the automated GUI smoke test.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, Qt  # noqa: E402
import shiboken6  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from gittool.app import GitToolWindow, PullReviewRequest  # noqa: E402
from gittool.backend import LocalChange, PullPreview, RepositoryState  # noqa: E402
from gittool.repository_catalog import RepositoryEntry  # noqa: E402
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

    def test_application_icon_is_packaged_and_visible(self) -> None:
        from importlib.resources import files
        from gittool.app_icon import application_icon

        asset = files("gittool").joinpath("assets", "gittool.png")
        self.assertTrue(asset.is_file())
        self.assertGreater(len(asset.read_bytes()), 500)
        self.assertFalse(application_icon().isNull())
        self.assertFalse(self.window.windowIcon().isNull())

    def test_compact_columns_do_not_scroll_horizontally_on_start(self) -> None:
        """Numeric headings fit while the local path expands into free space."""
        from PySide6.QtWidgets import QHeaderView

        self.window.resize(1270, 790)
        self.window.show()
        QApplication.processEvents()

        header = self.window.tree.header()
        self.assertEqual(
            header.sectionResizeMode(7), QHeaderView.ResizeMode.Stretch,
        )
        for column in (4, 5):
            expected = header.fontMetrics().horizontalAdvance(
                self.window.tree.headerItem().text(column)
            ) + 22
            self.assertEqual(self.window.tree.columnWidth(column), expected)
        self.assertGreater(self.window.tree.columnWidth(7), 200)
        self.assertEqual(self.window.tree.horizontalScrollBar().maximum(), 0)

        long_path = self.path / ("very-long-repository-name-" * 8)
        self.window._register_repository(long_path, persist=False, discover=False)
        QApplication.processEvents()
        self.assertEqual(self.window.tree.horizontalScrollBar().maximum(), 0)

    def test_add_and_scan_buttons_work_again_after_repeated_operations(self) -> None:
        """Regression: generic action buttons must not stay disabled after work."""
        by_label = {button.text(): button for button in self.window.buttons}
        add = by_label["＋ Repository"]
        scan = by_label["Ordner scannen"]
        typed = by_label["Pfad hinzufügen"]

        self.window._register_repository(self.path, persist=False, discover=False)
        # Each operation disables every button, but _on_finished must restore
        # add, scan and manual path entry regardless of any selected row.
        for operation in ("scan", "check", "pull", "scan"):
            with patch.object(self.window.executor, "submit") as submit:
                self.window._start(operation, [self.path])
                submit.assert_called_once()
            self.assertFalse(add.isEnabled())
            self.assertFalse(scan.isEnabled())
            self.assertFalse(typed.isEnabled())

            self.window._on_finished()
            self.assertTrue(add.isEnabled(), operation)
            self.assertTrue(scan.isEnabled(), operation)
            self.assertTrue(typed.isEnabled(), operation)
            self.assertTrue(self.window.all_check.isEnabled())
            self.assertFalse(self.window.selected_check.isEnabled())

            # Verify that a click actually invokes the corresponding action,
            # not just that its enabled flag appears true.
            with (
                patch("gittool.app.QFileDialog.getExistingDirectory",
                      return_value=str(self.path)) as dialog,
                patch.object(self.window, "_add_from_path") as register,
                patch.object(self.window, "_start") as start,
            ):
                add.click()
                scan.click()
                self.window.path_input.setText(str(self.path))
                typed.click()
                self.assertEqual(dialog.call_count, 2)
                self.assertEqual(register.call_count, 2)
                start.assert_called_once_with("scan", [self.path])

    def test_obsolete_grey_legend_is_removed(self) -> None:
        self.assertFalse(hasattr(self.window, "legend"))

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

    def test_startup_does_not_start_git_or_rebuild_for_every_saved_entry(self) -> None:
        parents = [self.path.parent / f"saved-{index}" for index in range(12)]
        entries = [RepositoryEntry(path) for path in parents]
        with (
            patch("gittool.app.load_repository_entries", return_value=entries),
            patch("gittool.app.discover_submodules") as discovery,
            patch("gittool.app.QTimer.singleShot") as schedule,
        ):
            other = GitToolWindow()
        try:
            self.assertEqual(other.repositories, parents)
            self.assertEqual(other.tree.topLevelItemCount(), len(parents))
            discovery.assert_not_called()
            schedule.assert_called_once()
        finally:
            other.close()
            import shiboken6
            shiboken6.delete(other)

    def test_parallel_checks_keep_network_fetch_optional(self) -> None:
        paths = [self.path.parent / f"check-{index}" for index in range(6)]
        lock = threading.Lock()
        active = 0
        peak = 0
        calls = []

        def inspect(path: Path, *, fetch: bool) -> RepositoryState:
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                calls.append((path, fetch))
            time.sleep(0.04)
            with lock:
                active -= 1
            return RepositoryState(path=path)

        with patch("gittool.app.inspect_repository", side_effect=inspect):
            self.window._work("quick_check", paths)
        self.assertEqual(len(calls), len(paths))
        self.assertTrue(all(not fetch for _, fetch in calls))
        self.assertGreaterEqual(peak, 2)

    def test_local_changes_dialog_explicit_approval(self) -> None:
        state = RepositoryState(
            self.path, branch="WiSe26", upstream="origin/WiSe26",
            dirty=True, behind=3, status="Lokale Änderungen",
        )
        preview = PullPreview(
            state=state,
            changes=(
                LocalChange("??", "Script-Beamer/Vorlesung_student_de.pdf"),
                LocalChange(" M", "notizen.tex"),
            ),
            head_oid="head", target_oid="target",
        )
        request = PullReviewRequest(preview, threading.Event())
        with patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Accepted):
            self.window._on_pull_review(request)
        self.assertTrue(request.complete.is_set())
        self.assertTrue(request.approved)

        cancelled = PullReviewRequest(preview, threading.Event())
        with patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Rejected):
            self.window._on_pull_review(cancelled)
        self.assertTrue(cancelled.complete.is_set())
        self.assertFalse(cancelled.approved)

    def test_local_collision_never_offers_approval(self) -> None:
        state = RepositoryState(
            self.path, branch="WiSe26", upstream="origin/WiSe26",
            dirty=True, behind=2, status="Lokale Änderungen",
        )
        preview = PullPreview(
            state,
            (LocalChange("??", "Script-Beamer/Vorlesung_student_de.pdf"),),
            ("Script-Beamer/Vorlesung_student_de.pdf",),
            "head", "target",
        )
        request = PullReviewRequest(preview, threading.Event())
        with patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Accepted):
            self.window._on_pull_review(request)
        self.assertTrue(request.complete.is_set())
        self.assertFalse(request.approved)

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
