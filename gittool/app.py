"""GTK4 + libadwaita desktop UI. Git operations never run in the GTK main loop."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import os
import sys

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gio, GLib, Gtk
except (ImportError, ValueError) as exc:
    raise SystemExit(
        "GTK 4 / libadwaita / PyGObject fehlen.\n"
        "Arch: sudo pacman -S python-gobject gtk4 libadwaita\n"
        "Debian/Ubuntu: sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1\n"
        "Wichtig: Die virtuelle Python-Umgebung muss 'gi' sehen. "
        "Siehe Installationshinweise in README.md."
    ) from exc

from .backend import (
    GitToolError, PullOutcome, RepositoryState, discover_repositories,
    inspect_repository, normalize_repository, pull_repository,
)
from .config import default_config_path, load_repositories, save_repositories
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


class GitToolApp(Adw.Application):
    """One application/window; all GTK calls remain on the main thread."""

    def __init__(self) -> None:
        super().__init__(application_id="io.github.protarios.gittool")
        self.repositories: list[Path] = []
        self.states: dict[str, RepositoryState] = {}
        self.errors: dict[str, str] = {}
        self.widgets: dict[str, tuple] = {}
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gittool")
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
            provider = Gtk.CssProvider()
            provider.load_from_data(CSS.encode("utf-8"))
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

        self.window = Adw.ApplicationWindow(application=self)
        self.window.set_title("GitTool")
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
        body.append(options)

        legend = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        for status in ("Aktuell", "Pull möglich", "Lokale Änderungen", "Divergiert"):
            title, css, icon = visual_status(status)
            dot = Gtk.Image.new_from_icon_name(icon)
            dot.add_css_class("pill-" + css)
            legend.append(dot)
            caption = Gtk.Label(label=title)
            caption.add_css_class("dim-label")
            legend.append(caption)
        body.append(legend)

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
        path = str(row.get_name())
        state = self.states.get(path)
        haystack = " ".join((
            path,
            state.branch if state else "",
            state.upstream if state else "",
            state.status if state else "",
        )).casefold()
        return query in haystack

    def _register_repository(self, path: Path, *, persist: bool = True) -> bool:
        path = path.expanduser().resolve()
        key = os.path.normcase(str(path))
        if any(os.path.normcase(str(old)) == key for old in self.repositories):
            return False

        row = Adw.ActionRow(title=path.name, subtitle=str(path))
        row.set_name(str(path))
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
        details.set_ellipsize(3)  # Pango.EllipsizeMode.END
        details.set_max_width_chars(60)
        details.set_tooltip_text("Noch nicht geprüft")
        row.add_suffix(details)

        badge = Gtk.Label(label="Nicht geprüft")
        badge.add_css_class("status-pill")
        badge.add_css_class("pill-muted")
        row.add_suffix(badge)

        self.listbox.append(row)
        self.repositories.append(path)
        self.widgets[str(path)] = (row, checkbox, indicator, details, badge)
        if persist:
            self._save()
        self._update_summary()
        return True

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
        if self._register_repository(path):
            self._log(f"Hinzugefügt: {path}")
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
                    if self._register_repository(normalized):
                        self._log(f"Hinzugefügt: {normalized}")
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
        for path in selected:
            key = str(path)
            self.listbox.remove(self.widgets[key][0])
            self.widgets.pop(key)
            self.states.pop(key, None)
            self.errors.pop(key, None)
        selected_set = set(selected)
        self.repositories = [p for p in self.repositories if p not in selected_set]
        self._save()
        self._log(f"{len(selected)} Repository(s) aus der Liste entfernt – keine Dateien gelöscht.")
        self._update_summary()

    def _save(self) -> None:
        try:
            save_repositories(self.repositories)
        except OSError as exc:
            self._toast(f"Speichern fehlgeschlagen: {exc}")
            self._log(f"FEHLER beim Speichern: {exc}")

    def _load_saved(self) -> None:
        try:
            paths = load_repositories()
        except (OSError, ValueError) as exc:
            self._toast(f"Konfiguration kann nicht gelesen werden: {exc}")
            self._log(f"FEHLER: {exc} ({default_config_path()})")
            return
        for path in paths:
            self._register_repository(path, persist=False)
        self._log(f"{len(self.repositories)} Repository(s) geladen.")

    def _start(self, operation: str, paths: list[Path]) -> None:
        if self.busy:
            return
        if not paths:
            self._toast("Bitte mindestens ein Repository hinzufügen oder auswählen.")
            return
        self.busy = True
        self.processed = 0
        self.total = len(paths)
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
        try:
            if operation == "scan":
                try:
                    self._emit("scan", discover_repositories(paths[0]))
                except Exception as exc:
                    self._emit("error", (paths[0], str(exc)))
            else:
                for path in paths:
                    try:
                        if operation == "check":
                            self._emit("status", inspect_repository(path, fetch=True))
                        else:
                            self._emit("pull", pull_repository(path))
                    except Exception as exc:
                        self._emit("error", (path, str(exc)))
        finally:
            self._emit("done", None)

    def _emit(self, kind: str, payload: object) -> None:
        GLib.idle_add(self._event, kind, payload)

    def _event(self, kind: str, payload: object) -> bool:
        if self.closing:
            return False
        if kind == "status":
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
            count = sum(self._register_repository(path, persist=False) for path in discovered)
            if count:
                self._save()
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
        current = sum(s.status == "Aktuell" for s in self.states.values())
        pullable = sum(s.status == "Pull möglich" for s in self.states.values())
        warnings = sum(s.status in ("Lokale Änderungen", "Nur lokal voraus") for s in self.states.values())
        errors = sum(s.status in ("Divergiert", "Detached HEAD", "Kein Upstream", "Kein Remote")
                     for s in self.states.values()) + len(self.errors)
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
        return False


def main() -> int:
    """Installed 'gittool' launcher and 'python -m gittool' entrypoint."""
    return GitToolApp().run(sys.argv)
