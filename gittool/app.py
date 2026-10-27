"""Modern Qt 6 frontend for Windows and Linux, using Python gittyup.

The repository configuration and Git backend are shared with the GTK branch.
Only the GUI thread touches Qt widgets; worker results use queued Qt signals.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from dataclasses import dataclass
import os
import threading
from pathlib import Path
import sys

try:
    from PySide6.QtCore import QObject, Qt, QTimer, Signal
    from PySide6.QtGui import QBrush, QColor, QFont
    from PySide6.QtWidgets import (
        QAbstractItemView, QApplication, QDialog, QDialogButtonBox, QFileDialog,
        QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
        QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSplitter,
        QTreeWidget, QTreeWidgetItem,
        QVBoxLayout, QWidget,
    )
except ImportError as exc:
    raise SystemExit(
        f"PySide6 konnte nicht geladen werden: {exc}\n"
        "Bitte im aktiven Python-Environment 'python -m pip install -e .' ausführen."
    ) from exc

from .backend import (
    GitToolError, PullOutcome, PullPreview, RepositoryState,
    discover_repositories, discover_submodules, inspect_repository,
    normalize_repository, prepare_pull, pull_repository,
)
from .config import default_config_path, load_repository_entries, save_repository_entries
from .repository_catalog import RepositoryCatalog
from .status_style import visual_status


COLUMNS = (
    "Repository", "Branch", "Upstream", "Dateien", "Ahead ↑",
    "Behind ↓", "Status", "Lokaler Pfad",
)
STATUS_COLUMN = 6
PATH_COLUMN = 7


@dataclass
class PullReviewRequest:
    """Worker-to-GUI request requiring an explicit decision."""
    preview: PullPreview
    complete: threading.Event
    approved: bool = False


class WorkerEvents(QObject):
    """Qt automatically dispatches cross-thread signals to the GUI thread."""

    state = Signal(object)
    outcome = Signal(object)
    error = Signal(object, str)
    scan = Signal(object)
    submodules = Signal(object)
    pull_review = Signal(object)
    finished = Signal()


class GitToolWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.catalog = RepositoryCatalog()
        self.repositories: list[Path] = []
        self.states: dict[str, RepositoryState] = {}
        self.errors: dict[str, str] = {}
        self.items: dict[str, QTreeWidgetItem] = {}
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gittool")
        self.submodule_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="gittool-submodules",
        )
        self.events = WorkerEvents(self)
        self.events.state.connect(self._on_state)
        self.events.outcome.connect(self._on_outcome)
        self.events.error.connect(self._on_error)
        self.events.scan.connect(self._on_scan)
        self.events.submodules.connect(self._on_submodules)
        self.events.pull_review.connect(self._on_pull_review)
        self.events.finished.connect(self._on_finished)
        self.busy = False
        self.completed = 0
        self.total = 0
        self.buttons: list[QPushButton] = []

        self.setWindowTitle("GitTool – Repository-Status und Pull")
        self.resize(1270, 790)
        self.setMinimumSize(850, 540)
        self._build_ui()
        self._load_saved()
        self._update_summary()

    def _button(self, label: str, handler: object, *, primary: bool = False) -> QPushButton:
        button = QPushButton(label)
        button.clicked.connect(handler)
        if primary:
            button.setObjectName("primaryAction")
        self.buttons.append(button)
        return button

    def _build_ui(self) -> None:
        wrapper = QWidget(self)
        self.setCentralWidget(wrapper)
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(20, 18, 20, 15)
        layout.setSpacing(13)

        heading = QHBoxLayout()
        heading.setSpacing(12)
        titles = QVBoxLayout()
        title = QLabel("GitTool")
        title.setObjectName("pageTitle")
        titles.addWidget(title)
        description = QLabel("Lokale Repositories prüfen und sicher per Fast-Forward aktualisieren")
        description.setObjectName("subtitle")
        titles.addWidget(description)
        heading.addLayout(titles, 1)
        heading.addWidget(self._button("＋ Repository", lambda: self._choose_folder(False)))
        heading.addWidget(self._button("Ordner scannen", lambda: self._choose_folder(True)))
        layout.addLayout(heading)

        pathline = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Repository-Pfad eingeben, z. B. C:\\Projekte\\MeinRepo")
        self.path_input.returnPressed.connect(self._add_typed)
        pathline.addWidget(self.path_input, 1)
        pathline.addWidget(self._button("Pfad hinzufügen", self._add_typed))
        layout.addLayout(pathline)

        command_bar = QHBoxLayout()
        command_bar.setSpacing(7)
        command_bar.addWidget(self._button("Auswahl entfernen", self._remove_selected))
        self.move_up = self._button("↑ Nach oben", lambda: self._move_selected(-1))
        self.move_down = self._button("↓ Nach unten", lambda: self._move_selected(1))
        command_bar.addWidget(self.move_up)
        command_bar.addWidget(self.move_down)
        command_bar.addSpacing(8)
        self.selected_check = self._button(
            "Auswahl prüfen", lambda: self._start("check", self._selected_paths())
        )
        command_bar.addWidget(self.selected_check)
        self.all_check = self._button(
            "Alle prüfen", lambda: self._start("check", list(self.repositories))
        )
        command_bar.addWidget(self.all_check)
        self.quick_check = self._button(
            "Lokal prüfen", lambda: self._start("quick_check", list(self.repositories))
        )
        self.quick_check.setToolTip(
            "Schnelle Prüfung gegen bereits vorhandene Remote-Refs; ohne git fetch."
        )
        command_bar.addWidget(self.quick_check)
        command_bar.addSpacing(8)
        self.selected_pull = self._button(
            "Auswahl prüfen + Pull", lambda: self._start("pull", self._selected_paths())
        )
        command_bar.addWidget(self.selected_pull)
        self.all_pull = self._button(
            "Alle prüfen + Pull",
            lambda: self._start("pull", list(self.repositories)),
            primary=True,
        )
        self.all_pull.setToolTip(
            "Fast-Forward-Prüfung; bei lokalen Änderungen Dateiliste zeigen und Freigabe einholen"
        )
        command_bar.addWidget(self.all_pull)
        command_bar.addStretch()
        layout.addLayout(command_bar)

        overview = QHBoxLayout()
        self.summary = QLabel("0 Repositories")
        self.summary.setObjectName("summary")
        overview.addWidget(self.summary, 1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Suchen: Name, Pfad, Branch, Status …")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(270)
        self.search.textChanged.connect(self._filter_rows)
        overview.addWidget(self.search)
        layout.addLayout(overview)

        self.legend = QLabel(
            "● Aktuell      ● Pull möglich      ● Lokale Änderungen      "
            "● Divergiert / Fehler      ● Nicht geprüft"
        )
        self.legend.setObjectName("legend")
        layout.addWidget(self.legend)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(COLUMNS))
        self.tree.setHeaderLabels(COLUMNS)
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setUniformRowHeights(True)
        self.tree.setSortingEnabled(False)
        self.tree.setMinimumHeight(180)
        self.tree.setAllColumnsShowFocus(True)
        header = self.tree.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for col, width in enumerate((165, 145, 175, 85, 80, 80, 175, 380)):
            self.tree.setColumnWidth(col, width)
        self.tree.itemSelectionChanged.connect(self._refresh_buttons)
        splitter.addWidget(self.tree)

        logs = QFrame()
        log_layout = QVBoxLayout(logs)
        log_layout.setContentsMargins(0, 7, 0, 0)
        log_header = QLabel("Aktivitätsprotokoll")
        log_header.setObjectName("sectionTitle")
        log_layout.addWidget(log_header)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1800)
        log_layout.addWidget(self.log)
        splitter.addWidget(logs)
        splitter.setSizes([480, 170])
        layout.addWidget(splitter, 1)

        footer = QHBoxLayout()
        self.activity = QLabel("Bereit")
        footer.addWidget(self.activity)
        footer.addStretch()
        self.progress = QProgressBar()
        self.progress.setMinimumWidth(220)
        self.progress.setTextVisible(True)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        footer.addWidget(self.progress)
        layout.addLayout(footer)
        self.statusBar().showMessage("Mehrfachauswahl mit Strg oder Umschalt. Kein Merge und kein Rebase.")
        self._refresh_buttons()

    def _register_repository(
        self, path: Path, *, parent: Path | None = None,
        persist: bool = True, discover: bool = True,
    ) -> bool:
        path = Path(path).expanduser().resolve()
        added = self.catalog.add(path, parent) if not self.catalog.has(path) else False
        changed = added
        if parent is not None and not added:
            changed = self.catalog.attach(path, parent) or changed
        if discover:
            try:
                descendants = discover_submodules(path)
            except GitToolError as exc:
                descendants = []
                self._log(f"Submodule konnten nicht geprüft werden ({path}): {exc}")
            for child, immediate_parent in descendants:
                if not self.catalog.has(child):
                    self.catalog.add(child, immediate_parent)
                    changed = True
                else:
                    changed = self.catalog.attach(child, immediate_parent) or changed
        if changed:
            self._rebuild_tree()
            if persist:
                self._save()
        return added

    def _rebuild_tree(self) -> None:
        """Rebuild true parent/child rows while retaining state and selection."""
        selected = {str(path) for path in self._selected_paths()}
        self.repositories = self.catalog.paths
        self.tree.blockSignals(True)
        try:
            self.tree.clear()
            self.items.clear()
            for entry in self.catalog.entries:
                path = entry.path
                label = f"↳ {path.name}" if entry.parent else path.name
                item = QTreeWidgetItem(
                    [label, "–", "–", "–", "–", "–", "Nicht geprüft", str(path)]
                )
                item.setData(0, Qt.ItemDataRole.UserRole, str(path))
                item.setToolTip(0, (
                    f"Submodul von {entry.parent}\n{path}" if entry.parent else str(path)
                ))
                if entry.parent is not None:
                    self.items[str(entry.parent)].addChild(item)
                else:
                    self.tree.addTopLevelItem(item)
                self.items[str(path)] = item
                state = self.states.get(str(path))
                if state is not None:
                    self._write_item_state(item, state)
                if str(path) in self.errors:
                    self._colorize(item, "Fehler")
                    item.setToolTip(STATUS_COLUMN, self.errors[str(path)])
                elif state is None:
                    self._colorize(item, "Nicht geprüft")
                if str(path) in selected:
                    item.setSelected(True)
            self.tree.expandAll()
        finally:
            self.tree.blockSignals(False)
        self._filter_rows()
        self._update_summary()

    def _write_item_state(self, item: QTreeWidgetItem, state: RepositoryState) -> None:
        item.setText(1, state.branch or "–")
        item.setText(2, state.upstream or "–")
        item.setText(3, "Geändert" if state.dirty else "Sauber")
        item.setText(4, str(state.ahead))
        item.setText(5, str(state.behind))
        item.setToolTip(STATUS_COLUMN, state.detail)
        self._colorize(item, state.status)

    def _move_selected(self, direction: int) -> None:
        selected = self._selected_paths()
        if selected and self.catalog.move(selected[0], direction):
            self._rebuild_tree()
            self._save()

    def _colorize(self, item: QTreeWidgetItem, status: str) -> None:
        label, category, _icon = visual_status(status)
        dark = self.palette().color(self.backgroundRole()).lightness() < 128
        palette = {
            "ok": ("#81c995", "#153825") if dark else ("#176d38", "#e3f3e8"),
            "info": ("#8fc6ff", "#193b5a") if dark else ("#176aa6", "#e2effa"),
            "warn": ("#ffd078", "#543915") if dark else ("#935500", "#fff0d2"),
            "error": ("#ff9795", "#562323") if dark else ("#b3261e", "#fbe6e5"),
            "muted": ("#aab2bb", "#35373b") if dark else ("#6a7078", "#eef0f2"),
        }
        foreground, background = palette[category]
        item.setText(STATUS_COLUMN, f"● {label}")
        item.setForeground(STATUS_COLUMN, QBrush(QColor(foreground)))
        item.setBackground(STATUS_COLUMN, QBrush(QColor(background)))
        font = item.font(STATUS_COLUMN)
        font.setBold(True)
        item.setFont(STATUS_COLUMN, font)

    def _display_state(self, state: RepositoryState) -> None:
        key = str(state.path)
        item = self.items.get(key)
        if item is None:
            return
        self.states[key] = state
        self.errors.pop(key, None)
        self._write_item_state(item, state)
        self._filter_rows()
        self._update_summary()

    def _filter_rows(self) -> None:
        query = self.search.text().strip().casefold()
        if not query:
            for item in self.items.values():
                if item.isHidden():
                    item.setHidden(False)
            self._refresh_buttons()
            return
        matches: set[str] = set()
        for path in self.repositories:
            item = self.items[str(path)]
            haystack = " ".join(item.text(index) for index in range(len(COLUMNS))).casefold()
            if not query or query in haystack:
                entry = self.catalog.find(path)
                while entry is not None:
                    matches.add(str(entry.path))
                    entry = self.catalog.find(entry.parent) if entry.parent else None
        for path in self.repositories:
            self.items[str(path)].setHidden(str(path) not in matches)
        self._refresh_buttons()

    def _selected_paths(self) -> list[Path]:
        # Selection is independent of sorting and filtering.
        return [
            Path(str(item.data(0, Qt.ItemDataRole.UserRole)))
            for item in self.tree.selectedItems() if not item.isHidden()
        ]

    def _refresh_buttons(self) -> None:
        if self.busy:
            for button in self.buttons:
                button.setEnabled(False)
            return
        any_repos = bool(self.repositories)
        any_selection = bool(self._selected_paths())
        self.selected_check.setEnabled(any_selection)
        self.selected_pull.setEnabled(any_selection)
        self.all_check.setEnabled(any_repos)
        self.quick_check.setEnabled(any_repos)
        self.all_pull.setEnabled(any_repos)
        selected = self._selected_paths()
        if len(selected) == 1:
            entry = self.catalog.find(selected[0])
            siblings = self.catalog._children(entry.parent) if entry else []
            index = siblings.index(entry) if entry else -1
            self.move_up.setEnabled(index > 0)
            self.move_down.setEnabled(0 <= index < len(siblings) - 1)
        else:
            self.move_up.setEnabled(False)
            self.move_down.setEnabled(False)
        for button in self.buttons:
            if button.text() == "Auswahl entfernen":
                button.setEnabled(any_selection)
                break

    def _choose_folder(self, scan: bool) -> None:
        title = "Ordner mit Git-Repositories auswählen" if scan else "Git-Repository auswählen"
        folder = QFileDialog.getExistingDirectory(self, title, str(Path.home()))
        if not folder:
            return
        if scan:
            self._start("scan", [Path(folder)])
        else:
            self._add_from_path(folder)

    def _add_from_path(self, value: str) -> None:
        try:
            path = normalize_repository(value)
        except (GitToolError, OSError) as exc:
            self._log(f"FEHLER: {exc}")
            QMessageBox.warning(self, "Ungültiges Repository", str(exc))
            return
        if self._register_repository(path, discover=False):
            self._schedule_submodule_scan([path])
            self._log(f"Hinzugefügt: {path}")
        else:
            self.statusBar().showMessage("Repository ist bereits vorhanden.", 4000)

    def _add_typed(self) -> None:
        raw = self.path_input.text().strip().strip('"')
        if not raw:
            QMessageBox.information(self, "Repository hinzufügen", "Bitte einen lokalen Pfad eingeben.")
            return
        self._add_from_path(raw)
        self.path_input.clear()

    def _remove_selected(self) -> None:
        selected = self._selected_paths()
        if not selected:
            return
        removed: list[Path] = []
        for path in selected:
            removed.extend(self.catalog.remove(path))
        if not removed:
            return
        for path in removed:
            self.states.pop(str(path), None)
            self.errors.pop(str(path), None)
        self._rebuild_tree()
        self._save()
        self._log(f"{len(removed)} Repository(s) aus der Liste entfernt (keine Dateien gelöscht).")

    def _load_saved(self) -> None:
        """Load cached hierarchy in one UI update, without starting git.exe."""
        try:
            entries = load_repository_entries()
        except (OSError, ValueError) as exc:
            self._log(f"FEHLER beim Lesen von {default_config_path()}: {exc}")
            QMessageBox.warning(
                self, "Konfiguration", f"Repositories konnten nicht geladen werden:\n{exc}"
            )
            return
        self.catalog = RepositoryCatalog(entries)
        self._rebuild_tree()
        self._log(f"{len(self.repositories)} Repository(s) aus der Konfiguration geladen.")
        # Discover newly initialized submodules *after* the Qt event loop starts,
        # so a large library never blocks the main window from appearing.
        roots = [entry.path for entry in self.catalog.entries if entry.parent is None]
        if roots:
            QTimer.singleShot(0, lambda: self._schedule_submodule_scan(roots))

    def _schedule_submodule_scan(self, roots: list[Path]) -> None:
        """Run read-only Gitlink discovery outside the GUI/main worker queue."""
        if not roots:
            return
        try:
            self.submodule_executor.submit(self._discover_submodules_worker, list(roots))
        except RuntimeError as exc:
            self._log(f"Submodule-Prüfung konnte nicht gestartet werden: {exc}")

    def _discover_submodules_worker(self, roots: list[Path]) -> None:
        discovered: list[tuple[Path, Path]] = []
        errors: list[str] = []
        for root in roots:
            try:
                discovered.extend(discover_submodules(root))
            except (GitToolError, OSError) as exc:
                errors.append(f"{root}: {exc}")
        self.events.submodules.emit((discovered, errors))

    def _on_submodules(self, report: tuple[list[tuple[Path, Path]], list[str]]) -> None:
        """Batch all discovered links into one tree rebuild and one save."""
        discovered, errors = report
        changed = 0
        for child, parent in discovered:
            if not self.catalog.has(parent):
                continue  # The parent may have been removed while scanning.
            if not self.catalog.has(child):
                self.catalog.add(child, parent)
                changed += 1
            elif self.catalog.attach(child, parent):
                changed += 1
        if changed:
            self._rebuild_tree()
            self._save()
            self._log(f"Submodule-Erkennung: {changed} neue/zugeordnete Einträge.")
        for error in errors:
            self._log(f"Submodule-Prüfung: {error}")

    def _save(self) -> None:
        try:
            save_repository_entries(self.catalog.entries)
        except OSError as exc:
            self._log(f"FEHLER beim Speichern: {exc}")
            QMessageBox.warning(self, "Konfiguration", str(exc))

    def _start(self, operation: str, paths: list[Path]) -> None:
        if self.busy:
            return
        if not paths:
            QMessageBox.information(self, "Keine Repositories", "Bitte Repositories auswählen oder hinzufügen.")
            return
        self.busy = True
        self.completed = 0
        self.total = 1 if operation == "scan" else len(paths)
        self.progress.setRange(0, self.total)
        self.progress.setValue(0)
        self.activity.setText(f"{operation}: 0 / {self.total}")
        for button in self.buttons:
            button.setEnabled(False)
        self.path_input.setEnabled(False)
        self._log(f"--- {operation}: {len(paths)} Repository(s) / Ordner ---")
        try:
            self.executor.submit(self._work, operation, paths)
        except RuntimeError as exc:
            self.events.error.emit(paths[0], str(exc))
            self.events.finished.emit()

    def _work(self, operation: str, paths: list[Path]) -> None:
        try:
            if operation == "scan":
                try:
                    self.events.scan.emit(discover_repositories(paths[0]))
                except Exception as exc:
                    self.events.error.emit(paths[0], str(exc))
            elif operation in ("check", "quick_check"):
                # Only independent read/fetch checks run concurrently. Pulls
                # remain sequential because gittyup's ff-only environment is
                # process-wide and order/consistency must not be compromised.
                workers = min(4, len(paths))
                with ThreadPoolExecutor(
                    max_workers=workers, thread_name_prefix="gittool-check",
                ) as pool:
                    jobs = {
                        pool.submit(
                            inspect_repository, path, fetch=operation == "check",
                        ): path
                        for path in paths
                    }
                    for future in as_completed(jobs):
                        path = jobs[future]
                        try:
                            self.events.state.emit(future.result())
                        except Exception as exc:
                            self.events.error.emit(path, str(exc))
            else:
                for path in paths:
                    try:
                        preview = prepare_pull(path)
                        if preview.needs_confirmation:
                            request = PullReviewRequest(preview, threading.Event())
                            self.events.pull_review.emit(request)
                            request.complete.wait()
                            if not request.approved:
                                self.events.outcome.emit(PullOutcome(
                                    preview.state, "Übersprungen",
                                    "Pull abgebrochen; keine lokalen Dateien geändert.",
                                ))
                                continue
                            outcome = pull_repository(path, approved_preview=preview)
                        else:
                            outcome = pull_repository(path, checked_state=preview.state)
                        self.events.outcome.emit(outcome)
                    except Exception as exc:
                        self.events.error.emit(path, str(exc))
        finally:
            self.events.finished.emit()

    def _on_pull_review(self, request: PullReviewRequest) -> None:
        """List local changes and offer approval only if paths do not collide."""
        preview = request.preview
        try:
            dialog = QDialog(self)
            dialog.setWindowTitle(f"Lokale Änderungen – {preview.state.name}")
            dialog.resize(760, 470)
            layout = QVBoxLayout(dialog)

            if preview.overlaps:
                heading = QLabel(
                    "<b>Pull gesperrt:</b> Eingehende Commits berühren "
                    "lokal geänderte oder unversionierte Dateien."
                )
            else:
                heading = QLabel(
                    "<b>Lokale Änderungen vorhanden.</b> Die eingehenden Commits "
                    "berühren nach der Vorprüfung keine dieser Dateien. "
                    "Möchtest du den Fast-Forward-Pull durchführen?"
                )
            heading.setWordWrap(True)
            layout.addWidget(heading)

            summary = QLabel(
                f"Repository: {preview.state.path}\n"
                f"Branch: {preview.state.branch} → {preview.state.upstream}\n"
                f"Eingehende Commits: {preview.state.behind}  ·  "
                f"Lokale Dateieinträge: {len(preview.changes)}"
            )
            summary.setWordWrap(True)
            layout.addWidget(summary)

            details = QPlainTextEdit(dialog)
            details.setReadOnly(True)
            details.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            details.setPlainText("\n".join(
                f"{change.status}  {change.path}"
                + ("    ← Überschneidung!" if change.path in preview.overlaps else "")
                for change in preview.changes
            ))
            layout.addWidget(details, 1)

            if preview.overlaps:
                note = QLabel(
                    "Bitte die überschneidenden Dateien sichern, committen, "
                    "verschieben oder anderweitig klären."
                )
            else:
                note = QLabel(
                    "Nur Fast-Forward; Git überprüft selbst zusätzlich, dass "
                    "lokale Änderungen nicht überschrieben werden."
                )
            note.setWordWrap(True)
            layout.addWidget(note)

            buttons = QDialogButtonBox(dialog)
            cancel = buttons.addButton(
                "Überspringen", QDialogButtonBox.ButtonRole.RejectRole,
            )
            cancel.clicked.connect(dialog.reject)
            if not preview.overlaps:
                proceed = buttons.addButton(
                    "Pull durchführen", QDialogButtonBox.ButtonRole.AcceptRole,
                )
                proceed.clicked.connect(dialog.accept)
            layout.addWidget(buttons)
            request.approved = bool(
                not preview.overlaps and dialog.exec() == QDialog.DialogCode.Accepted
            )
        except Exception as exc:
            request.approved = False
            self._log(f"Pull-Freigabedialog fehlgeschlagen: {exc}")
        finally:
            request.complete.set()

    def _on_state(self, state: RepositoryState) -> None:
        self._display_state(state)
        self._log(f"{state.name}: {state.status} – {state.detail}")
        self._advance()

    def _on_outcome(self, outcome: PullOutcome) -> None:
        self._display_state(outcome.state)
        self._log(f"{outcome.state.name}: {outcome.action}\n{outcome.message}")
        self._advance()

    def _on_error(self, path: Path, detail: str) -> None:
        key = str(path)
        item = self.items.get(key)
        if item is not None:
            self.errors[key] = detail
            self._colorize(item, "Fehler")
            item.setToolTip(STATUS_COLUMN, detail)
        self._log(f"FEHLER {path}: {detail}")
        self._update_summary()
        self._advance()

    def _on_scan(self, discovered: list[Path]) -> None:
        # Build just one tree, regardless of how many repositories were found.
        new: list[Path] = []
        for path in discovered:
            path = Path(path).expanduser().resolve()
            if not self.catalog.has(path):
                self.catalog.add(path)
                new.append(path)
        if new:
            self._rebuild_tree()
            self._save()
            self._schedule_submodule_scan(new)
        self._log(f"Suche: {len(discovered)} gefunden, {len(new)} neu aufgenommen.")
        self.statusBar().showMessage(f"{len(new)} Repository(s) hinzugefügt.", 7000)
        self._advance()

    def _advance(self) -> None:
        self.completed += 1
        self.progress.setValue(min(self.completed, self.total))
        self.activity.setText(f"{self.completed} / {self.total}")

    def _on_finished(self) -> None:
        self.busy = False
        self.activity.setText("Abgeschlossen")
        self.path_input.setEnabled(True)
        self._refresh_buttons()
        self._log("--- Fertig ---")

    def _update_summary(self) -> None:
        current = sum(s.status == "Aktuell" for k, s in self.states.items() if k not in self.errors)
        behind = sum(s.status in ("Pull möglich", "Lokal geändert · Pull möglich") for k, s in self.states.items() if k not in self.errors)
        warnings = sum(s.status in ("Lokale Änderungen", "Lokal geändert · Aktuell", "Lokal geändert · Lokal voraus", "Nur lokal voraus", "Kein Upstream", "Kein Remote", "Tracking-Ref fehlt")
                       for k, s in self.states.items() if k not in self.errors)
        blocked = sum(s.status in ("Divergiert", "Detached HEAD")
                      for k, s in self.states.items() if k not in self.errors) + len(self.errors)
        self.summary.setText(
            f"{len(self.repositories)} Repositories   ·   {current} aktuell   ·   "
            f"{behind} Pull möglich   ·   {warnings} lokal   ·   {blocked} blockiert"
        )

    def _log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log.appendPlainText(f"[{stamp}] {message}")

    def closeEvent(self, event: object) -> None:
        if self.busy:
            QMessageBox.information(
                self, "Git-Vorgang läuft",
                "Bitte den laufenden Git-Vorgang vor dem Schließen abschließen lassen.",
            )
            event.ignore()
            return
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.submodule_executor.shutdown(wait=False, cancel_futures=True)
        event.accept()


STYLE = """
QWidget { font-size: 10pt; }
QMainWindow { background: palette(window); }
QLabel#pageTitle { font-size: 21pt; font-weight: bold; }
QLabel#subtitle { color: palette(mid); font-size: 10pt; }
QLabel#summary { font-size: 11pt; font-weight: bold; }
QLabel#legend { color: palette(mid); font-size: 9pt; padding: 3px; }
QLabel#sectionTitle { font-size: 10pt; font-weight: bold; }
QLineEdit { padding: 8px 11px; border: 1px solid palette(midlight); border-radius: 7px; }
QLineEdit:focus { border: 1px solid #3988cb; }
QPushButton { padding: 7px 11px; border: 1px solid palette(midlight); border-radius: 7px; }
QPushButton#primaryAction { background: #176aa6; color: white; border-color: #176aa6; font-weight: bold; }
QPushButton#primaryAction:hover { background: #125c95; }
QTreeWidget { border: 1px solid palette(midlight); border-radius: 8px; }
QTreeWidget::item { min-height: 27px; padding: 2px; }
QPlainTextEdit { border: 1px solid palette(midlight); border-radius: 8px; }
QProgressBar { height: 13px; border: 1px solid palette(midlight); border-radius: 6px; text-align: center; }
QProgressBar::chunk { border-radius: 5px; background: #3988cb; }
"""


def main() -> int:
    """Entry point for the Windows-compatible PySide6 interface."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    app.setApplicationName("GitTool")
    app.setOrganizationName("Protarios")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = GitToolWindow()
    window.show()
    return app.exec()
