"""Persist ordered local Git repositories and submodule parent links."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Iterable

from platformdirs import user_config_path

from .repository_catalog import RepositoryCatalog, RepositoryEntry


def default_config_path() -> Path:
    return user_config_path("gittool", "Protarios") / "repositories.json"


def load_repository_entries(config_path: Path | None = None) -> list[RepositoryEntry]:
    path = Path(config_path) if config_path is not None else default_config_path()
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("repositories"), list):
        raise ValueError("Ungültiges Konfigurationsformat.")
    entries: list[RepositoryEntry] = []
    for item in data["repositories"]:
        if isinstance(item, str):  # Legacy v1 file; retain its saved order.
            entries.append(RepositoryEntry(Path(item).expanduser().resolve()))
        elif isinstance(item, dict) and isinstance(item.get("path"), str) and (
            item.get("parent") is None or isinstance(item.get("parent"), str)
        ):
            parent = item.get("parent")
            entries.append(RepositoryEntry(
                Path(item["path"]).expanduser().resolve(),
                Path(parent).expanduser().resolve() if parent else None,
            ))
        else:
            raise ValueError("Ungültiger Repository-Eintrag in der Konfiguration.")
    return RepositoryCatalog(entries).entries


def load_repositories(config_path: Path | None = None) -> list[Path]:
    """Legacy API retained for old scripts and tests."""
    return [entry.path for entry in load_repository_entries(config_path)]


def save_repository_entries(
    entries: Iterable[RepositoryEntry], config_path: Path | None = None
) -> None:
    path = Path(config_path) if config_path is not None else default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = RepositoryCatalog(entries).entries
    payload = {
        "version": 2,
        "repositories": [
            {"path": str(entry.path), "parent": str(entry.parent) if entry.parent else None}
            for entry in normalized
        ],
    }
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".gittool-",
            suffix=".tmp", delete=False,
        ) as stream:
            temporary = stream.name
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def save_repositories(repositories: list[Path], config_path: Path | None = None) -> None:
    """Legacy API: saves independent roots while preserving order."""
    save_repository_entries(
        [RepositoryEntry(Path(repo)) for repo in repositories], config_path,
    )
