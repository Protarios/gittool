"""Ordered Git repository catalog with explicit parent/submodule relationships.

Every subtree is stored in pre-order, so moving a parent preserves all children.
The model deliberately never initializes, fetches or modifies a submodule.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class RepositoryEntry:
    path: Path
    parent: Path | None = None


@lru_cache(maxsize=32768)
def path_key(path: Path) -> str:
    return os.path.normcase(str(path.expanduser().resolve()))


class RepositoryCatalog:
    def __init__(self, entries: Iterable[RepositoryEntry] = ()) -> None:
        # Load in one pass instead of rebuilding the entire ordered tree for
        # every entry. A large saved repository list otherwise becomes O(n^3).
        self.entries: list[RepositoryEntry] = []
        seen: set[str] = set()
        for entry in entries:
            path = Path(entry.path).expanduser().resolve()
            key = path_key(path)
            if key in seen:
                continue
            parent = (
                Path(entry.parent).expanduser().resolve()
                if entry.parent is not None else None
            )
            if parent is not None and path_key(parent) not in seen:
                parent = None  # Preserve orphaned entries as roots.
            self.entries.append(RepositoryEntry(path, parent))
            seen.add(key)
        if self.entries:
            self._rebuild(self._ordered_groups())

    def has(self, path: Path) -> bool:
        return any(path_key(entry.path) == path_key(path) for entry in self.entries)

    def find(self, path: Path) -> RepositoryEntry | None:
        key = path_key(path)
        return next((entry for entry in self.entries if path_key(entry.path) == key), None)

    def _children(self, parent: Path | None) -> list[RepositoryEntry]:
        return [entry for entry in self.entries if (
            (parent is None and entry.parent is None) or
            (parent is not None and entry.parent is not None and
             path_key(parent) == path_key(entry.parent))
        )]

    def _rebuild(self, orders: dict[str | None, list[RepositoryEntry]]) -> None:
        flattened: list[RepositoryEntry] = []
        def visit(parent: Path | None) -> None:
            key = path_key(parent) if parent is not None else None
            for entry in orders.get(key, ()):
                flattened.append(entry)
                visit(entry.path)
        visit(None)
        if len(flattened) != sum(len(group) for group in orders.values()):
            raise ValueError("Ungültige Repository-Hierarchie.")
        self.entries = flattened

    def _ordered_groups(self) -> dict[str | None, list[RepositoryEntry]]:
        groups: dict[str | None, list[RepositoryEntry]] = {}
        for entry in self.entries:
            parent = path_key(entry.parent) if entry.parent else None
            groups.setdefault(parent, []).append(entry)
        return groups

    def add(self, path: Path, parent: Path | None = None) -> bool:
        path = Path(path).expanduser().resolve()
        if self.has(path):
            return False
        if parent is not None:
            parent = Path(parent).expanduser().resolve()
            if not self.has(parent) or path_key(parent) == path_key(path):
                raise ValueError(f"Unbekanntes oder ungültiges Hauptrepository: {parent}")
        entry = RepositoryEntry(path, parent)
        groups = self._ordered_groups()
        groups.setdefault(path_key(parent) if parent else None, []).append(entry)
        self._rebuild(groups)
        return True

    def attach(self, path: Path, parent: Path) -> bool:
        """Attach an existing root entry to a parent, leaving descendants intact."""
        entry = self.find(path)
        target = self.find(parent)
        if entry is None or target is None:
            return False
        if entry.parent is not None and path_key(entry.parent) == path_key(target.path):
            return False
        # An entry cannot become a descendant of its own subtree.
        cursor = target
        while cursor.parent is not None:
            if path_key(cursor.parent) == path_key(entry.path):
                return False
            cursor = self.find(cursor.parent)
            if cursor is None:
                return False
        if path_key(entry.path) == path_key(target.path):
            return False
        groups = self._ordered_groups()
        old_key = path_key(entry.parent) if entry.parent else None
        groups[old_key].remove(entry)
        updated = RepositoryEntry(entry.path, target.path)
        groups.setdefault(path_key(target.path), []).append(updated)
        self._rebuild(groups)
        return True

    def remove(self, path: Path) -> list[Path]:
        """Remove a repository and all descendant entries (never delete files)."""
        entry = self.find(path)
        if entry is None:
            return []
        removed: list[Path] = []
        def collect(root: Path) -> None:
            removed.append(root)
            for child in self._children(root):
                collect(child.path)
        collect(entry.path)
        keys = {path_key(path) for path in removed}
        self.entries = [entry for entry in self.entries if path_key(entry.path) not in keys]
        return removed

    def move(self, path: Path, direction: int) -> bool:
        """Move one sibling position; a parent carries its full subtree."""
        entry = self.find(path)
        if entry is None or direction not in (-1, 1):
            return False
        groups = self._ordered_groups()
        key = path_key(entry.parent) if entry.parent else None
        siblings = groups[key]
        index = siblings.index(entry)
        target = index + direction
        if not 0 <= target < len(siblings):
            return False
        siblings[index], siblings[target] = siblings[target], siblings[index]
        self._rebuild(groups)
        return True

    @property
    def paths(self) -> list[Path]:
        return [entry.path for entry in self.entries]

    def depth(self, path: Path) -> int:
        entry = self.find(path)
        level = 0
        while entry and entry.parent:
            level += 1
            entry = self.find(entry.parent)
        return level
