"""Persist the user-selected local repositories, never credentials."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from platformdirs import user_config_path


def default_config_path() -> Path:
    return user_config_path("gittool", "Protarios") / "repositories.json"


def load_repositories(config_path: Path | None = None) -> list[Path]:
    path = Path(config_path) if config_path is not None else default_config_path()
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("repositories"), list):
        raise ValueError("Ungültiges Konfigurationsformat.")
    if not all(isinstance(item, str) for item in data["repositories"]):
        raise ValueError("Ungültiger Repository-Pfad.")
    return [Path(item).expanduser().resolve() for item in data["repositories"]]


def save_repositories(repositories: list[Path], config_path: Path | None = None) -> None:
    path = Path(config_path) if config_path is not None else default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "repositories": [str(path) for path in repositories]}
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
