"""Cross-platform Tkinter frontend for gittyup."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import os
from pathlib import Path
from queue import Empty, Queue
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from .backend import (
    GitToolError, PullOutcome, RepositoryState, discover_repositories,
    inspect_repository, normalize_repository, pull_repository,
)
from .config import default_config_path, load_repositories, save_repositories


COLUMNS = (
    ("name", "Repository", 150),
    ("branch", "Branch", 115),
    ("upstream", "Upstream", 155),
    ("dirty", "Dateien", 90),
    ("ahead", "Ahead", 65),
    ("behind", "Behind", 65),
    ("status", "Status", 170),
    ("path", "Lokaler Pfad", 330),
)


class GitToolApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("GitTool – Repository-Status & Pull (gittyup)")
        self.geometry("1280x760")
        self.minsize(920, 560)

        self.repositories: list[Path] = []
        self.states: dict[str, RepositoryState] = {}
        self.events: Queue[tuple] = Queue()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gittool")
        self.busy = False
        self.buttons: list[ttk.Button] = []
        self.path_var = tk.StringVar()
        self.summary_var = tk.StringVar(value="0 Repositories")
        self.activity_var = tk.StringVar(value="Bereit")
        self._total = 0
        self._finished = 0

        self._build_ui()
        self._load_repositories()
        self.after(100, self._drain_events)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _button(self, parent: ttk.Frame, label: str, command: object) -> ttk.Button:
        button = ttk.Button(parent, text=label, command=command)
        button.pack(side=tk.LEFT, padx=(0, 6), pady=3)
        self.buttons.append(button)
        return button

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            outer, text="GitTool", font=("TkDefaultFont", 17, "bold")
        ).pack(anchor=tk.W)
        ttk.Label(
            outer, text="Lokale Repositories verwalten, Remote-Status prüfen und sicher per Fast-Forward aktualisieren."
        ).pack(anchor=tk.W, pady=(2, 10))

        path_row = ttk.Frame(outer)
        path_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(path_row, text="Pfad:").pack(side=tk.LEFT, padx=(0, 6))
        entry = ttk.Entry(path_row, textvariable=self.path_var)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        entry.bind("<Return>", lambda _event: self._add_typed())
        self._button(path_row, "Hinzufügen", self._add_typed)
        self._button(path_row, "Ordner wählen …", self._browse_add)
        self._button(path_row, "Ordner durchsuchen …", self._scan_folder)

        operations = ttk.Frame(outer)
        operations.pack(fill=tk.X, pady=(0, 7))
        self._button(operations, "Auswahl entfernen", self._remove_selected)
        ttk.Separator(operations, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=9)
        self._button(operations, "Auswahl prüfen", lambda: self._operate("check", True))
        self._button(operations, "Alle prüfen", lambda: self._operate("check", False))
        ttk.Separator(operations, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=9)
        self._button(operations, "Auswahl: prüfen + Pull", lambda: self._operate("pull", True))
        self._button(operations, "Alle: prüfen + Pull", lambda: self._operate("pull", False))

        ttk.Label(
            outer, text="Mehrfachauswahl: Strg/Umschalt. Pull nur bei sauberem Arbeitsverzeichnis, Upstream und Fast-Forward.",
        ).pack(anchor=tk.W, pady=(0, 7))

        table_frame = ttk.Frame(outer)
        table_frame.pack(fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(
            table_frame, columns=[item[0] for item in COLUMNS],
            show="headings", selectmode="extended", height=13,
        )
        for key, label, width in COLUMNS:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=55, stretch=(key == "path"))
        self.tree.tag_configure("ok", foreground="#137333")
        self.tree.tag_configure("ready", foreground="#0b63a7")
        self.tree.tag_configure("warning", foreground="#965f00")
        self.tree.tag_configure("error", foreground="#b3261e")
        yscroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        xscroll = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        log_frame = ttk.LabelFrame(outer, text="Protokoll", padding=(8, 5))
        log_frame.pack(fill=tk.BOTH, expand=False, pady=(10, 5))
        self.log = scrolledtext.ScrolledText(
            log_frame, height=9, state=tk.DISABLED, wrap=tk.WORD,
            font=("TkFixedFont", 10),
        )
        self.log.pack(fill=tk.BOTH, expand=True)

        footer = ttk.Frame(outer)
        footer.pack(fill=tk.X)
        ttk.Label(footer, textvariable=self.summary_var).pack(side=tk.LEFT)
        self.progress = ttk.Progressbar(footer, mode="determinate", length=160)
        self.progress.pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Label(footer, textvariable=self.activity_var).pack(side=tk.RIGHT)

    def _load_repositories(self) -> None:
        try:
            paths = load_repositories()
        except (OSError, ValueError) as exc:
            self._write_log(f"Konfiguration konnte nicht geladen werden: {exc}")
            messagebox.showwarning(
                "Konfiguration", f"Die Konfiguration ist nicht lesbar:\n{exc}\n\n{default_config_path()}",
            )
            return
        for path in paths:
            self._register(path, persist=False)
        self._update_summary()
        self._write_log(f"{len(self.repositories)} Repository(s) geladen.")

    def _persist(self) -> None:
        try:
            save_repositories(self.repositories)
        except OSError as exc:
            messagebox.showerror("Speichern fehlgeschlagen", str(exc))
            self._write_log(f"Konfiguration konnte nicht gespeichert werden: {exc}")

    def _register(self, path: Path, *, persist: bool = True) -> bool:
        path = path.expanduser().resolve()
        key = os.path.normcase(str(path))
        if any(os.path.normcase(str(p)) == key for p in self.repositories):
            return False
        self.repositories.append(path)
        self.tree.insert(
            "", tk.END, iid=str(path),
            values=(path.name, "–", "–", "–", "–", "–", "Nicht geprüft", str(path)),
        )
        if persist:
            self._persist()
        self._update_summary()
        return True

    def _add_typed(self) -> None:
        raw = self.path_var.get().strip().strip('"')
        if not raw:
            messagebox.showinfo("Repository hinzufügen", "Bitte einen lokalen Verzeichnispfad eingeben.")
            return
        try:
            path = normalize_repository(raw)
        except (GitToolError, OSError) as exc:
            messagebox.showerror("Kein Repository", str(exc))
            return
        if self._register(path):
            self._write_log(f"Hinzugefügt: {path}")
        self.path_var.set("")

    def _browse_add(self) -> None:
        directory = filedialog.askdirectory(title="Git-Repository-Stammordner auswählen")
        if directory:
            self.path_var.set(directory)
            self._add_typed()

    def _scan_folder(self) -> None:
        root = filedialog.askdirectory(title="Übergeordneten Ordner nach Repositories durchsuchen")
        if not root:
            return
        self._start_job("scan", [Path(root)])

    def _selected(self) -> list[Path]:
        return [Path(iid) for iid in self.tree.selection()]

    def _remove_selected(self) -> None:
        selected = set(self.tree.selection())
        if not selected:
            messagebox.showinfo("Auswahl", "Bitte mindestens ein Repository auswählen.")
            return
        self.repositories = [p for p in self.repositories if str(p) not in selected]
        for iid in selected:
            self.tree.delete(iid)
            self.states.pop(iid, None)
        self._persist()
        self._update_summary()
        self._write_log(f"{len(selected)} Repository(s) aus der Liste entfernt (keine Dateien gelöscht).")

    def _operate(self, operation: str, selected_only: bool) -> None:
        paths = self._selected() if selected_only else list(self.repositories)
        if not paths:
            messagebox.showinfo(
                "Keine Repositories",
                "Bitte Repositories hinzufügen bzw. Zeilen auswählen.",
            )
            return
        self._start_job(operation, paths)

    def _start_job(self, operation: str, paths: list[Path]) -> None:
        if self.busy:
            return
        self.busy = True
        self._total = len(paths)
        self._finished = 0
        self.progress.configure(maximum=self._total, value=0)
        for button in self.buttons:
            button.configure(state=tk.DISABLED)
        label = {"scan": "Suche", "check": "Statusprüfung", "pull": "Prüfen + Pull"}[operation]
        self.activity_var.set(f"{label}: 0/{self._total}")
        self._write_log(f"--- {label} gestartet ({self._total}) ---")
        try:
            self.executor.submit(self._worker, operation, paths)
        except RuntimeError as exc:
            self.events.put(("error", paths[0], str(exc)))
            self.events.put(("done", operation))

    def _worker(self, operation: str, paths: list[Path]) -> None:
        try:
            if operation == "scan":
                try:
                    found = discover_repositories(paths[0])
                    self.events.put(("scan", found))
                except Exception as exc:
                    self.events.put(("error", paths[0], str(exc)))
                return

            for path in paths:
                try:
                    if operation == "check":
                        state = inspect_repository(path, fetch=True)
                        self.events.put(("state", state))
                    else:
                        outcome = pull_repository(path)
                        self.events.put(("outcome", outcome))
                except Exception as exc:
                    self.events.put(("error", path, str(exc)))
        finally:
            self.events.put(("done", operation))

    def _drain_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "state":
                    state = event[1]
                    self._show_state(state)
                    self._write_log(f"{state.name}: {state.status} – {state.detail}")
                    self._advance()
                elif kind == "outcome":
                    outcome: PullOutcome = event[1]
                    self._show_state(outcome.state)
                    detail = outcome.message.replace("\r", "")
                    self._write_log(f"{outcome.state.name}: {outcome.action}\n{detail}")
                    self._advance()
                elif kind == "error":
                    path, detail = event[1:]
                    if self.tree.exists(str(path)):
                        current = list(self.tree.item(str(path), "values"))
                        current[6] = "Fehler"
                        self.tree.item(str(path), values=current, tags=("error",))
                    self._write_log(f"FEHLER {path}: {detail}")
                    self._advance()
                elif kind == "scan":
                    found: list[Path] = event[1]
                    count = sum(self._register(path, persist=False) for path in found)
                    if count:
                        self._persist()
                    self._write_log(f"Suche abgeschlossen: {len(found)} gefunden, {count} neu hinzugefügt.")
                    self._advance()
                elif kind == "done":
                    self.busy = False
                    for button in self.buttons:
                        button.configure(state=tk.NORMAL)
                    self.activity_var.set("Bereit")
                    self._write_log("--- Abgeschlossen ---")
        except Empty:
            pass
        if self.winfo_exists():
            self.after(100, self._drain_events)

    def _advance(self) -> None:
        self._finished += 1
        self.progress.configure(value=self._finished)
        self.activity_var.set(f"Fortschritt: {self._finished}/{self._total}")

    def _show_state(self, state: RepositoryState) -> None:
        key = str(state.path)
        if not self.tree.exists(key):
            return
        self.states[key] = state
        if state.status == "Aktuell":
            tag = "ok"
        elif state.status == "Pull möglich":
            tag = "ready"
        elif state.status in ("Divergiert", "Detached HEAD", "Kein Upstream", "Kein Remote"):
            tag = "error"
        else:
            tag = "warning"
        self.tree.item(
            key,
            values=(
                state.name, state.branch or "–", state.upstream or "–",
                "Geändert" if state.dirty else "Sauber",
                state.ahead, state.behind, state.status, str(state.path),
            ),
            tags=(tag,),
        )
        self._update_summary()

    def _update_summary(self) -> None:
        checked = len(self.states)
        self.summary_var.set(f"{len(self.repositories)} Repositories · {checked} geprüft")

    def _write_log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, f"[{stamp}] {message}\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _close(self) -> None:
        if self.busy:
            messagebox.showwarning(
                "Git-Operation läuft", "Die Git-Operation läuft noch. Bitte vor dem Beenden abschließen lassen.",
            )
            return
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()


def main() -> None:
    app = GitToolApp()
    app.mainloop()
