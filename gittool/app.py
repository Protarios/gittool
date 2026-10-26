"""Modern Qt 6 frontend for Windows and Linux, using Python gittyup.

The repository configuration and Git backend are shared with the GTK branch.
Only the GUI thread touches Qt widgets; worker results use queued Qt signals.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import os
from pathlib import Path
import sys

try:
    from PySide6.QtCore import QObject, Qt, Signal
    from PySide6.QtGui import QBrush, QColor, QFont
    from PySide6.QtWidgets import (
        QAbstractItemView, QApplication, QFileDialog, QFrame, QHBoxLayout,
        QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
        QProgressBar, QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem,
        QVBoxLayout, QWidget,
    )
except ImportError as exc:
    raise SystemExit(
        f"PySide6 konnte nicht geladen werden: {exc}\n"
        "Bitte im aktiven Python-Environment 'python -m pip install -e .' ausführen."
    ) from exc

from .backend import (
    GitToolError, PullOutcome, RepositoryState, discover_repositories,
    inspect_repository, normalize_repository, pull_repository,
)
from .config import default_config_path, load_repositories, save_repositories
from .status_style import visual_status


COLUMNS = (
    "Repository", "Branch", "Upstream", "Dateien", "Ahead ↑",
    "Behind ↓", "Status", "Lokaler Pfad",
)
STATUS_COLUMN = 6
PATH_COLUMN = 7


class WorkerEvents(QObject):
    """Qt automatically dispatches cross-thread signals to the GUI thread."""

    state = Signal(object)
    outcome = Signal(object)
    error = Signal(object, str)
    scan = Signal(object)
    finished = Signal()


class GitToolWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.repositories: list[Path] = []
        self.states: dict[str, RepositoryState] = {}
        self.errors: dict[str, str] = {}
        self.items: dict[str, QTreeWidgetItem] = {}
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gittool")
        self.events = WorkerEvents(self)
        self.events.state.connect(self._on_state)
        self.events.outcome.connect(self._on_outcome)
        self.events.error.connect(self._on_error)
        self.events.scan.connect(self._on_scan)
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
        command_bar.addSpacing(8)
        self.selected_check = self._button(
            "Auswahl prüfen", lambda: self._start("check", self._selected_paths())
        )
        command_bar.addWidget(self.selected_check)
        self.all_check = self._button(
            "Alle prüfen", lambda: self._start("check", list(self.repositories))
        )
        command_bar.addWidget(self.all_check)
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
            "Prüfen und ausschließlich saubere Fast-Forward-Repositories aktualisieren"
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
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setUniformRowHeights(True)
        self.tree.setSortingEnabled(True)
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

    def _register_repository(self, path: Path, *, persist: bool = True) -> bool:
        path = path.expanduser().resolve()
        key = os.path.normcase(str(path))
        if any(os.path.normcase(str(p)) == key for p in self.repositories):
            return False

        item = QTreeWidgetItem(
            [path.name, "–", "–", "–", "–", "–", "Nicht geprüft", str(path)]
        )
        item.setData(0, Qt.ItemDataRole.UserRole, str(path))
        item.setToolTip(0, str(path))
        self.tree.addTopLevelItem(item)
        self.repositories.append(path)
        self.items[str(path)] = item
        self._colorize(item, "Nicht geprüft")
        self._filter_rows()
        self._update_summary()
        if persist:
            self._save()
        return True

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
        item.setText(1, state.branch or "–")
        item.setText(2, state.upstream or "–")
        item.setText(3, "Geändert" if state.dirty else "Sauber")
        item.setText(4, str(state.ahead))
        item.setText(5, str(state.behind))
        item.setToolTip(STATUS_COLUMN, state.detail)
        self._colorize(item, state.status)
        self._filter_rows()
        self._update_summary()

    def _filter_rows(self) -> None:
        query = self.search.text().strip().casefold()
        for path in self.repositories:
            item = self.items[str(path)]
            text = " ".join(item.text(index) for index in range(len(COLUMNS))).casefold()
            item.setHidden(bool(query and query not in text))
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
        self.all_pull.setEnabled(any_repos)
        # Remove button is the third button in the toolbar, after Add/Scan/Path.
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
        if self._register_repository(path):
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
        for path in selected:
            key = str(path)
            item = self.items.pop(key)
            index = self.tree.indexOfTopLevelItem(item)
            if index >= 0:
                self.tree.takeTopLevelItem(index)
            self.states.pop(key, None)
            self.errors.pop(key, None)
        selected_set = set(selected)
        self.repositories = [p for p in self.repositories if p not in selected_set]
        self._save()
        self._log(f"{len(selected)} Repository(s) aus der Liste entfernt (keine Dateien gelöscht).")
        self._update_summary()
        self._refresh_buttons()

    def _load_saved(self) -> None:
        try:
            paths = load_repositories()
        except (OSError, ValueError) as exc:
            self._log(f"FEHLER beim Lesen von {default_config_path()}: {exc}")
            QMessageBox.warning(self, "Konfiguration", f"Repositories konnten nicht geladen werden:\n{exc}")
            return
        for path in paths:
            self._register_repository(path, persist=False)
        self._log(f"{len(self.repositories)} Repository(s) aus der Konfiguration geladen.")

    def _save(self) -> None:
        try:
            save_repositories(self.repositories)
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
            else:
                for path in paths:
                    try:
                        if operation == "check":
                            self.events.state.emit(inspect_repository(path, fetch=True))
                        else:
                            self.events.outcome.emit(pull_repository(path))
                    except Exception as exc:
                        self.events.error.emit(path, str(exc))
        finally:
            self.events.finished.emit()

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
        count = sum(self._register_repository(p, persist=False) for p in discovered)
        if count:
            self._save()
        self._log(f"Suche: {len(discovered)} gefunden, {count} neu aufgenommen.")
        self.statusBar().showMessage(f"{count} Repository(s) hinzugefügt.", 7000)
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
        behind = sum(s.status == "Pull möglich" for k, s in self.states.items() if k not in self.errors)
        warnings = sum(s.status in ("Lokale Änderungen", "Nur lokal voraus", "Kein Upstream", "Kein Remote")
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
