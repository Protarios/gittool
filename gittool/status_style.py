"""Visual status mapping, independent of the GTK runtime for unit testing."""

from __future__ import annotations


def visual_status(status: str) -> tuple[str, str, str]:
    """Return accessible label, themed color category, symbolic GTK icon."""
    options = {
        "Aktuell": ("Aktuell", "ok", "emblem-default-symbolic"),
        "Pull möglich": ("Pull möglich", "info", "software-update-available-symbolic"),
        "Lokale Änderungen": ("Lokal geändert", "warn", "dialog-warning-symbolic"),
        "Nur lokal voraus": ("Lokal voraus", "warn", "go-up-symbolic"),
        "Divergiert": ("Divergiert", "error", "dialog-error-symbolic"),
        "Detached HEAD": ("Detached HEAD", "error", "dialog-error-symbolic"),
        "Kein Remote": ("Kein Remote", "warn", "dialog-warning-symbolic"),
        "Kein Upstream": ("Kein Upstream", "warn", "dialog-warning-symbolic"),
        "Fehler": ("Fehler", "error", "dialog-error-symbolic"),
        "Nicht geprüft": ("Nicht geprüft", "muted", "dialog-question-symbolic"),
    }
    return options.get(status, (status or "Unbekannt", "muted", "dialog-question-symbolic"))
