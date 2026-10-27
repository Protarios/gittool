"""GTK4 + libadwaita desktop UI. Git operations never run in the GTK main loop."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from pathlib import Path
import os
import sys
import threading

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango
except (ImportError, ValueError) as exc:
    # Preserve the real import failure; the older generic message wrongly
    # implied missing GTK OS packages when only the venv hid PyGObject.
    raise SystemExit(
        f"GTK-Bindings konnten nicht geladen werden: {type(exc).__name__}: {exc}\n"
        f"Python: {sys.executable}\n\n"
        "Auf Arch/CachyOS: sudo pacman -S --needed python-gobject gtk4 libadwaita\n"
        "Falls diese Pakete bereits installiert sind und du eine .venv nutzt,\n"
        "prüfe in .venv/pyvenv.cfg die Einstellung:\n"
        "    include-system-site-packages = true\n"
        "Danach erneut starten. PyGObject muss mit deiner Python-Version kompatibel sein.\n"
        "Prüfung: python -c 'import gi; from gi.repository import Gtk, Adw'\n"
        "Details: README.md"
    ) from exc

from .backend import (
    GitToolError, PullOutcome, PullPreview, RepositoryState,
    discover_repositories, discover_submodules, inspect_repository,
    normalize_repository, prepare_pull, pull_repository,
)
from .config import default_config_path, load_repository_entries, save_repository_entries
from .repository_catalog import RepositoryCatalog
from .status_style import visual_status


CSS = """
.repo-indicator { min-width: 5px; min-height: 34px; border-radius: 6px; }
.indicator-ok { background: @success_color; }
.indicator-info { background: @accent_color; }
.indicator-warn { background: @warning_color; }
.indicator-error { background: @error_color; }
.indicator-muted { background: @insensitive_fg_color; }
.status-pill {
    border-radius: 999px;
    padding: 5px 12px;
    font-weight: 700;
    font-size: 0.88em;
    min-width: 95px;
}
.pill-ok { color: @success_color; background: alpha(@success_color, .13); }
.pill-info { color: @accent_color; background: alpha(@accent_color, .13); }
.pill-warn { color: @warning_color; background: alpha(@warning_color, .15); }
.pill-error { color: @error_color; background: alpha(@error_color, .13); }
.pill-muted { color: @insensitive_fg_color; background: alpha(@insensitive_fg_color, .10); }
.git-details { font-size: 0.89em; }
.repo-list { border-radius: 12px; }
.section-label { font-weight: 700; }
"""


@dataclass
class PullReviewRequest:
    """Worker waits for the GTK main thread to approve or reject a dirty pull."""
    preview: PullPreview
    complete: threading.Event
    approved: bool = False


class GitToolApp(Adw.Application):
    """One application/window; all GTK calls remain on the main thread."""

    def __init__(self) -> None:
        super().__init__(application_id="io.github.protarios.gittool")
        self.catalog = RepositoryCatalog()
        self.repositories: list[Path] = []
        self.states: dict[str, RepositoryState] = {}
        self.errors: dict[str, str] = {}
        self.widgets: dict[str, tuple] = {}
        self.row_paths: dict[str, str] = {}
        self.next_row_id = 0
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gittool")
        self.submodule_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="gittool-submodules",
        )
        self.busy = False
        self.closing = False
        self.buttons: list[Gtk.Button] = []
        self.window: Adw.ApplicationWindow | None = None
        self.processed = 0
        self.total = 0

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return

        display = Gdk.Display.get_default()
        if display is not None:
            # The bundled PNG is a local, unthemed icon named "gittool".
            # Works from editable installs, wheels, and any working directory.
            icon_dir = resources.files("gittool").joinpath("assets")
            Gtk.IconTheme.get_for_display(display).add_search_path(str(icon_dir))
            Gtk.Window.set_default_icon_name("gittool")
            provider = Gtk.CssProvider()
            provider.load_from_data(CSS.encode("utf-8"))
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

        self.window = Adw.ApplicationWindow(application=self)
        self.window.set_title("GitTool")
        self.window.set_icon_name("gittool")
        self.window.set_default_size(1160, 760)
        self.window.connect("close-request", self._on_close_request)

        self.toasts = Adw.ToastOverlay()
        self.window.set_content(self.toasts)
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.toasts.set_child(main)

        bar = Adw.HeaderBar()
        bar.set_title_widget(Adw.WindowTitle.new("GitTool", "Repository-Status und sicherer Pull"))
        main.append(bar)

        add_button = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Git-Repository hinzufügen")
        add_button.connect("clicked", lambda *_: self._choose_folder(scan=False))
        bar.pack_start(add_button)
        scan_button = Gtk.Button(icon_name="folder-saved-search-symbolic",
                                 tooltip_text="Verzeichnisbaum nach Repositories durchsuchen")
        scan_button.connect("clicked", lambda *_: self._choose_folder(scan=True))
        bar.pack_start(scan_button)
        self.buttons.extend([add_button, scan_button])

        self.all_check = Gtk.Button(label="Alle prüfen")
        self.all_check.connect("clicked", lambda *_: self._start("check", self.repositories[:]))
        bar.pack_end(self.all_check)
        self.buttons.append(self.all_check)

        self.all_pull = Gtk.Button(label="Alle prüfen + Pull")
        self.all_pull.add_css_class("suggested-action")
        self.all_pull.connect("clicked", lambda *_: self._start("pull", self.repositories[:]))
        bar.pack_end(self.all_pull)
        self.buttons.append(self.all_pull)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        body.set_margin_top(16)
        body.set_margin_bottom(14)
        body.set_margin_start(20)
        body.set_margin_end(20)
        main.append(body)

        intro = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        intro.set_valign(Gtk.Align.CENTER)
        self.summary = Gtk.Label(label="0 Repositories", xalign=0)
        self.summary.add_css_class("title-3")
        self.summary.set_hexpand(True)
        intro.append(self.summary)
        self.search = Gtk.SearchEntry(placeholder_text="Repository, Pfad oder Status suchen")
        self.search.set_width_chars(31)
        self.search.connect("search-changed", lambda *_: self.listbox.invalidate_filter())
        intro.append(self.search)
        body.append(intro)

        pathline = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.path_entry = Gtk.Entry(placeholder_text="Lokalen Repository-Pfad eingeben …")
        self.path_entry.set_hexpand(True)
        self.path_entry.connect("activate", lambda *_: self._add_entered_path())
        pathline.append(self.path_entry)
        path_button = Gtk.Button(label="Pfad hinzufügen")
        path_button.connect("clicked", lambda *_: self._add_entered_path())
        self.buttons.append(path_button)
        pathline.append(path_button)
        body.append(pathline)

        options = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.quick_check = Gtk.Button(label="Lokal prüfen")
        self.quick_check.set_tooltip_text(
            "Alle Repositories ohne Netzwerk-Fetch gegen vorhandene Tracking-Refs prüfen."
        )
        self.quick_check.connect(
            "clicked", lambda *_: self._start("quick_check", self.repositories[:])
        )
        options.append(self.quick_check)
        self.buttons.append(self.quick_check)
        for label, callback in (
            ("Auswahl prüfen", lambda: self._start("check", self._selected_paths())),
            ("Auswahl: prüfen + Pull", lambda: self._start("pull", self._selected_paths())),
            ("Auswahl entfernen", self._remove_selected),
        ):
            button = Gtk.Button(label=label)
            button.connect("clicked", lambda _b, run=callback: run())
            options.append(button)
            self.buttons.append(button)
        self.select_button = Gtk.Button(label="Alle auswählen")
        self.select_button.connect("clicked", lambda *_: self._toggle_selection())
        options.append(self.select_button)
        self.buttons.append(self.select_button)
        self.move_up = Gtk.Button(label="↑ Nach oben")
        self.move_up.connect("clicked", lambda *_: self._move_selected(-1))
        options.append(self.move_up)
        self.buttons.append(self.move_up)
        self.move_down = Gtk.Button(label="↓ Nach unten")
        self.move_down.connect("clicked", lambda *_: self._move_selected(1))
        options.append(self.move_down)
        self.buttons.append(self.move_down)
        body.append(options)

        scroll = Gtk.ScrolledWindow()
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.listbox = Gtk.ListBox()
        self.listbox.add_css_class("boxed-list")
        self.listbox.add_css_class("repo-list")
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.set_filter_func(self._filter_row)
        empty = Adw.StatusPage(
            title="Noch keine Repositories",
            description="Über „+“ einen Repository-Ordner wählen oder einen ganzen Verzeichnisbaum durchsuchen.",
            icon_name="folder-symbolic",
        )
        empty.set_vexpand(True)
        self.listbox.set_placeholder(empty)
        scroll.set_child(self.listbox)
        body.append(scroll)

        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.progress = Gtk.ProgressBar()
        self.progress.set_hexpand(True)
        self.progress.set_show_text(True)
        self.progress.set_text("Bereit")
        bottom.append(self.progress)
        body.append(bottom)

        expander = Gtk.Expander(label="Protokoll")
        expander.set_expanded(True)
        body.append(expander)
        log_scroll = Gtk.ScrolledWindow()
        log_scroll.set_min_content_height(132)
        log_scroll.set_max_content_height(200)
        log_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.logview = Gtk.TextView()
        self.logview.set_editable(False)
        self.logview.set_cursor_visible(False)
        self.logview.set_monospace(True)
        self.logview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.logview.set_top_margin(6)
        self.logview.set_left_margin(8)
        self.logview.set_right_margin(8)
        log_scroll.set_child(self.logview)
        expander.set_child(log_scroll)

        self._load_saved()
        self._update_summary()
        self.window.present()

    def _filter_row(self, row: Gtk.ListBoxRow) -> bool:
        query = self.search.get_text().strip().casefold()
        if not query:
            return True
        path = self.row_paths.get(row.get_name(), "")
        state = self.states.get(path)
        haystack = " ".join((
            path,
            state.branch if state else "",
            state.upstream if state else "",
            state.status if state else "",
        )).casefold()
        return query in haystack

    def _create_row(self, path: Path) -> None:
        row = Adw.ActionRow(title=path.name, subtitle=str(path))
        row_id = f"gittool-row-{self.next_row_id}"
        self.next_row_id += 1
        row.set_name(row_id)
        self.row_paths[row_id] = str(path)
        row.set_tooltip_text(str(path))
        checkbox = Gtk.CheckButton()
        checkbox.set_tooltip_text("Repository für Aktionen auswählen")
        row.add_prefix(checkbox)

        indicator = Gtk.Box()
        indicator.add_css_class("repo-indicator")
        indicator.add_css_class("indicator-muted")
        row.add_prefix(indicator)

        details = Gtk.Label(label="Branch: –     Upstream: –     ↑ 0   ↓ 0")
        details.add_css_class("dim-label")
        details.add_css_class("git-details")
        details.set_ellipsize(Pango.EllipsizeMode.END)
        details.set_max_width_chars(60)
        details.set_tooltip_text("Noch nicht geprüft")
        row.add_suffix(details)

        badge = Gtk.Label(label="Nicht geprüft")
        badge.add_css_class("status-pill")
        badge.add_css_class("pill-muted")
        row.add_suffix(badge)

        self.widgets[str(path)] = (row, checkbox, indicator, details, badge)
        self.listbox.append(row)

    def _sync_rows(self) -> None:
        """Keep visual order in sync with catalog while retaining row state."""
        self.repositories = self.catalog.paths
        for entry in self.catalog.entries:
            path = entry.path
            if str(path) not in self.widgets:
                self._create_row(path)
            row = self.widgets[str(path)][0]
            depth = self.catalog.depth(path)
            row.set_title(("↳ " * depth) + path.name)
            row.set_subtitle(
                f"Submodul von {entry.parent.name}  ·  {path}"
                if entry.parent else str(path)
            )
            row.set_tooltip_text(
                f"Submodul von: {entry.parent}\n{path}" if entry.parent else str(path)
            )
        for index, entry in enumerate(self.catalog.entries):
            row = self.widgets[str(entry.path)][0]
            self.listbox.remove(row)
            self.listbox.insert(row, index)
        self.listbox.invalidate_filter()
        self._update_summary()

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
            self._sync_rows()
            if persist:
                self._save()
        return added

    def _move_selected(self, direction: int) -> None:
        selected = self._selected_paths()
        if len(selected) != 1:
            self._toast("Zum Verschieben bitte genau ein Repository auswählen.")
            return
        if self.catalog.move(selected[0], direction):
            self._sync_rows()
            self._save()

    def _set_status(self, path: Path, status: str, detail: str,
                    state: RepositoryState | None = None) -> None:
        key = str(path)
        if key not in self.widgets:
            return
        row, checkbox, indicator, details, badge = self.widgets[key]
        for color in ("ok", "info", "warn", "error", "muted"):
            badge.remove_css_class("pill-" + color)
            indicator.remove_css_class("indicator-" + color)
        label, color, _icon = visual_status(status)
        badge.set_text(label)
        badge.add_css_class("pill-" + color)
        indicator.add_css_class("indicator-" + color)
        row.set_tooltip_text(detail or key)
        if state is not None:
            self.states[key] = state
            branch = state.branch or "–"
            upstream = state.upstream or "–"
            details.set_text(f"{branch}  →  {upstream}    ↑ {state.ahead}   ↓ {state.behind}"
                             + ("    ● lokal geändert" if state.dirty else ""))
            details.set_tooltip_text(
                f"Branch: {branch}\nUpstream: {upstream}\nAhead: {state.ahead} / Behind: {state.behind}\n{detail}"
            )
            self.errors.pop(key, None)
        elif status == "Fehler":
            self.errors[key] = detail
        self.listbox.invalidate_filter()
        self._update_summary()

    def _add_entered_path(self) -> None:
        value = self.path_entry.get_text().strip().strip('"')
        if not value:
            self._toast("Bitte einen Repository-Pfad eingeben.")
            return
        try:
            path = normalize_repository(value)
        except (GitToolError, OSError) as exc:
            self._toast(str(exc))
            self._log(f"FEHLER: {exc}")
            return
        if self._register_repository(path, discover=False):
            self._log(f"Hinzugefügt: {path}")
            self._schedule_submodule_scan([path])
        else:
            self._toast("Repository bereits vorhanden.")
        self.path_entry.set_text("")

    def _choose_folder(self, *, scan: bool) -> None:
        dialog = Gtk.FileDialog()
        dialog.set_title(
            "Übergeordneten Ordner durchsuchen" if scan else "Git-Repository auswählen"
        )

        def chosen(dlg: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
            try:
                folder = dlg.select_folder_finish(result)
            except GLib.Error as exc:
                if not exc.matches(Gtk.DialogError.quark(), Gtk.DialogError.DISMISSED):
                    self._toast(str(exc))
                return
            if folder is None or folder.get_path() is None:
                self._toast("Nur lokale Ordner werden unterstützt.")
                return
            path = Path(folder.get_path())
            if scan:
                self._start("scan", [path])
            else:
                try:
                    normalized = normalize_repository(path)
                    if self._register_repository(normalized, discover=False):
                        self._log(f"Hinzugefügt: {normalized}")
                        self._schedule_submodule_scan([normalized])
                    else:
                        self._toast("Repository bereits vorhanden.")
                except (GitToolError, OSError) as exc:
                    self._toast(str(exc))

        dialog.select_folder(self.window, None, chosen)

    def _selected_paths(self) -> list[Path]:
        return [
            path for path in self.repositories
            if self.widgets[str(path)][1].get_active()
        ]

    def _toggle_selection(self) -> None:
        all_selected = bool(self.repositories) and all(
            self.widgets[str(path)][1].get_active() for path in self.repositories
        )
        for path in self.repositories:
            self.widgets[str(path)][1].set_active(not all_selected)
        self.select_button.set_label("Alle auswählen" if all_selected else "Auswahl aufheben")

    def _remove_selected(self) -> None:
        selected = self._selected_paths()
        if not selected:
            self._toast("Bitte zuerst Repositories auswählen.")
            return
        removed: list[Path] = []
        for path in selected:
            removed.extend(self.catalog.remove(path))
        for path in removed:
            key = str(path)
            row = self.widgets[key][0]
            self.row_paths.pop(row.get_name(), None)
            self.listbox.remove(row)
            self.widgets.pop(key)
            self.states.pop(key, None)
            self.errors.pop(key, None)
        self._sync_rows()
        self._save()
        self._log(f"{len(removed)} Repository(s) aus der Liste entfernt – keine Dateien gelöscht.")

    def _save(self) -> None:
        try:
            save_repository_entries(self.catalog.entries)
        except OSError as exc:
            self._toast(f"Speichern fehlgeschlagen: {exc}")
            self._log(f"FEHLER beim Speichern: {exc}")

    def _load_saved(self) -> None:
        try:
            entries = load_repository_entries()
        except (OSError, ValueError) as exc:
            self._toast(f"Konfiguration kann nicht gelesen werden: {exc}")
            self._log(f"FEHLER: {exc} ({default_config_path()})")
            return
        # Bulk-load: do not rebuild the entire Gtk.ListBox or launch git
        # once for every saved repository during startup.
        self.catalog = RepositoryCatalog(entries)
        self._sync_rows()
        if self.catalog.entries != entries:
            self._save()
        self._log(f"{len(self.repositories)} Repository(s) geladen.")
        roots = [entry.path for entry in self.catalog.entries if entry.parent is None]
        if roots:
            self._schedule_submodule_scan(roots)

    def _start(self, operation: str, paths: list[Path]) -> None:
        if self.busy:
            return
        if not paths:
            self._toast("Bitte mindestens ein Repository hinzufügen oder auswählen.")
            return
        self.busy = True
        self.processed = 0
        self.total = 1 if operation == "scan" else len(paths)
        self.progress.set_fraction(0)
        self.progress.set_text(f"0 / {self.total}")
        for button in self.buttons:
            button.set_sensitive(False)
        self.path_entry.set_sensitive(False)
        self._log(f"--- {operation}: {self.total} Verzeichnis(se) ---")
        try:
            self.executor.submit(self._work, operation, paths)
        except RuntimeError as exc:
            self._event("error", (paths[0], str(exc)))
            self._event("done", None)

    def _work(self, operation: str, paths: list[Path]) -> None:
        """Independent status checks parallel; pulls serialized and ff-only."""
        try:
            if operation == "scan":
                try:
                    self._emit("scan", discover_repositories(paths[0]))
                except Exception as exc:
                    self._emit("error", (paths[0], str(exc)))
            elif operation in ("check", "quick_check"):
                with ThreadPoolExecutor(
                    max_workers=min(4, len(paths)), thread_name_prefix="gittool-check",
                ) as pool:
                    jobs = {
                        pool.submit(
                            inspect_repository, path, fetch=operation == "check",
                        ): path for path in paths
                    }
                    for job in as_completed(jobs):
                        path = jobs[job]
                        try:
                            self._emit("status", job.result())
                        except Exception as exc:
                            self._emit("error", (path, str(exc)))
            elif operation == "pull":
                for path in paths:
                    try:
                        # One fetch and immutable preview; no duplicate network
                        # fetch when the caller proceeds with a clean tree.
                        preview = prepare_pull(path)
                        if preview.needs_confirmation:
                            request = PullReviewRequest(preview, threading.Event())
                            self._emit("pull_review", request)
                            request.complete.wait()
                            if not request.approved:
                                self._emit("pull", PullOutcome(
                                    preview.state, "Übersprungen",
                                    "Pull abgebrochen; keine lokalen Dateien geändert.",
                                ))
                                continue
                            outcome = pull_repository(path, approved_preview=preview)
                        else:
                            outcome = pull_repository(
                                path, checked_state=preview.state,
                            )
                        self._emit("pull", outcome)
                    except Exception as exc:
                        self._emit("error", (path, str(exc)))
            else:
                raise ValueError(f"Unbekannte GitTool-Aktion: {operation}")
        finally:
            self._emit("done", None)

    def _schedule_submodule_scan(self, roots: list[Path]) -> None:
        if not roots or self.closing:
            return
        try:
            self.submodule_executor.submit(
                self._discover_submodules_worker, list(roots),
            )
        except RuntimeError as exc:
            self._log(f"Submodul-Prüfung konnte nicht gestartet werden: {exc}")

    def _discover_submodules_worker(self, roots: list[Path]) -> None:
        discovered: list[tuple[Path, Path]] = []
        errors: list[str] = []
        for root in roots:
            try:
                discovered.extend(discover_submodules(root))
            except (GitToolError, OSError) as exc:
                errors.append(f"{root}: {exc}")
        self._emit("submodules", (discovered, errors))

    def _show_pull_review(self, request: PullReviewRequest) -> None:
        """Native nonblocking GTK dialog; worker resumes on explicit response."""
        preview = request.preview
        try:
            blocking = bool(preview.overlaps)
            heading = (
                "Pull gesperrt: Dateiüberschneidung"
                if blocking else "Pull trotz lokaler Änderungen?"
            )
            body = (
                f"{preview.state.name} · {preview.state.branch} → "
                f"{preview.state.upstream} · {preview.state.behind} Remote-Commits\n"
                + (
                    "Eingehende Commits berühren lokale Dateien. "
                    "Bitte zunächst die betroffenen Dateien klären."
                    if blocking else
                    "Keine Pfadüberschneidung erkannt. Die lokalen Dateien "
                    "bleiben erhalten; Git prüft vor dem Fast-Forward erneut."
                )
            )
            dialog = Adw.MessageDialog.new(self.window, heading, body)
            dialog.add_response("cancel", "Überspringen")
            dialog.set_close_response("cancel")
            if not blocking:
                dialog.add_response("pull", "Pull durchführen")
                dialog.set_response_appearance(
                    "pull", Adw.ResponseAppearance.SUGGESTED,
                )
            textview = Gtk.TextView()
            textview.set_editable(False)
            textview.set_cursor_visible(False)
            textview.set_monospace(True)
            textview.get_buffer().set_text("\n".join(
                f"{change.status}  {change.path}"
                + ("    ← Überschneidung!" if change.path in preview.overlaps else "")
                for change in preview.changes
            ))
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            scroll.set_min_content_height(220)
            scroll.set_size_request(590, 220)
            scroll.set_child(textview)
            dialog.set_extra_child(scroll)

            def decision(_dialog: Adw.MessageDialog, response: str) -> None:
                request.approved = not blocking and response == "pull"
                request.complete.set()
                _dialog.destroy()

            dialog.connect("response", decision)
            dialog.present()
        except Exception as exc:
            request.approved = False
            request.complete.set()
            self._log(f"Pull-Freigabedialog fehlgeschlagen: {exc}")

    def _emit(self, kind: str, payload: object) -> None:
        GLib.idle_add(self._event, kind, payload)

    def _event(self, kind: str, payload: object) -> bool:
        if self.closing:
            return False
        if kind == "pull_review":
            self._show_pull_review(payload)
        elif kind == "submodules":
            discovered, errors = payload
            changed = 0
            for child, parent in discovered:
                if not self.catalog.has(parent):
                    continue
                if not self.catalog.has(child):
                    self.catalog.add(child, parent)
                    changed += 1
                elif self.catalog.attach(child, parent):
                    changed += 1
            if changed:
                self._sync_rows()
                self._save()
                self._log(f"Submodule: {changed} neue/zugeordnete Einträge.")
            for error in errors:
                self._log(f"Submodul-Prüfung: {error}")
        elif kind == "status":
            state: RepositoryState = payload
            self._set_status(state.path, state.status, state.detail, state)
            self._log(f"{state.name}: {state.status} – {state.detail}")
            self._advance()
        elif kind == "pull":
            outcome: PullOutcome = payload
            self._set_status(
                outcome.state.path, outcome.state.status,
                outcome.state.detail, outcome.state,
            )
            self._log(f"{outcome.state.name}: {outcome.action}\n{outcome.message}")
            self._advance()
        elif kind == "error":
            path, detail = payload
            self._set_status(path, "Fehler", detail)
            self._log(f"FEHLER {path}: {detail}")
            self._advance()
        elif kind == "scan":
            discovered = payload
            added: list[Path] = []
            for path in discovered:
                path = Path(path).expanduser().resolve()
                if not self.catalog.has(path):
                    self.catalog.add(path)
                    added.append(path)
            if added:
                self._sync_rows()
                self._save()
                self._schedule_submodule_scan(added)
            count = len(added)
            self._log(f"Suche: {len(discovered)} gefunden, {count} neu aufgenommen.")
            self._toast(f"{count} Repository(s) hinzugefügt.")
            self._advance()
        elif kind == "done":
            self.busy = False
            for button in self.buttons:
                button.set_sensitive(True)
            self.path_entry.set_sensitive(True)
            self.progress.set_text("Abgeschlossen")
            self._log("--- Fertig ---")
        return False

    def _advance(self) -> None:
        self.processed += 1
        self.progress.set_fraction(self.processed / max(self.total, 1))
        self.progress.set_text(f"{self.processed} / {self.total}")

    def _update_summary(self) -> None:
        current = sum(s.status == "Aktuell" for key, s in self.states.items() if key not in self.errors)
        pullable = sum(
            s.status in ("Pull möglich", "Lokal geändert · Pull möglich")
            for key, s in self.states.items() if key not in self.errors
        )
        warnings = sum(
            s.status in (
                "Lokale Änderungen", "Lokal geändert · Aktuell",
                "Lokal geändert · Lokal voraus", "Nur lokal voraus",
                "Kein Upstream", "Kein Remote", "Tracking-Ref fehlt",
            ) for key, s in self.states.items() if key not in self.errors
        )
        errors = sum(
            s.status in ("Divergiert", "Detached HEAD")
            for key, s in self.states.items() if key not in self.errors
        ) + len(self.errors)
        self.summary.set_text(
            f"{len(self.repositories)} Repositories   ·   {current} aktuell   ·   "
            f"{pullable} Pull möglich   ·   {warnings} lokal   ·   {errors} blockiert"
        )

    def _log(self, message: str) -> None:
        buffer = self.logview.get_buffer()
        stamp = datetime.now().strftime("%H:%M:%S")
        buffer.insert(buffer.get_end_iter(), f"[{stamp}] {message}\n")

    def _toast(self, message: str) -> None:
        self.toasts.add_toast(Adw.Toast.new(message))

    def _on_close_request(self, _window: Adw.ApplicationWindow) -> bool:
        if self.busy:
            self._toast("Git-Vorgang läuft noch. Vor dem Schließen bitte abschließen lassen.")
            return True
        self.closing = True
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.submodule_executor.shutdown(wait=False, cancel_futures=True)
        return False


def main() -> int:
    """Installed 'gittool' launcher and 'python -m gittool' entrypoint."""
    return GitToolApp().run(sys.argv)
