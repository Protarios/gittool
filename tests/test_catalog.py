"""Repository hierarchy/order regression tests, including real Git submodules."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from gittool.backend import discover_submodules
from gittool.config import (
    load_repositories, load_repository_entries, save_repository_entries,
)
from gittool.repository_catalog import RepositoryCatalog, RepositoryEntry


def git(cwd: Path, *args: str) -> str:
    process = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ALLOW_PROTOCOL": "file"},
    )
    if process.returncode != 0:
        raise AssertionError(f"git {args}: {process.stdout}\n{process.stderr}")
    return process.stdout.strip()


class CatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.a = self.home / "repo-a"
        self.b = self.home / "repo-b"
        self.c = self.home / "repo-c"
        self.child = self.a / "lib" / "child"
        self.grandchild = self.child / "vendor" / "grand"

    def test_reorder_parent_keeps_whole_subtree(self) -> None:
        catalog = RepositoryCatalog()
        catalog.add(self.a)
        catalog.add(self.child, self.a)
        catalog.add(self.grandchild, self.child)
        catalog.add(self.b)
        catalog.add(self.c)
        self.assertEqual(catalog.paths, [self.a, self.child, self.grandchild, self.b, self.c])
        self.assertTrue(catalog.move(self.a, +1))
        self.assertEqual(catalog.paths, [self.b, self.a, self.child, self.grandchild, self.c])
        self.assertFalse(catalog.move(self.child, -1))
        self.assertTrue(catalog.move(self.c, -1))
        self.assertEqual(catalog.paths, [self.b, self.c, self.a, self.child, self.grandchild])
        self.assertEqual(catalog.depth(self.grandchild), 2)

    def test_existing_root_can_be_attached(self) -> None:
        catalog = RepositoryCatalog([RepositoryEntry(self.child), RepositoryEntry(self.a)])
        self.assertTrue(catalog.attach(self.child, self.a))
        self.assertEqual(catalog.paths, [self.a, self.child])
        self.assertEqual(catalog.find(self.child).parent, self.a)
        self.assertFalse(catalog.attach(self.a, self.child))  # prevent cycles
        self.assertFalse(catalog.attach(self.child, self.a))

    def test_remove_parent_cascades_without_touching_directories(self) -> None:
        catalog = RepositoryCatalog()
        catalog.add(self.a)
        catalog.add(self.child, self.a)
        catalog.add(self.grandchild, self.child)
        catalog.add(self.b)
        self.child.mkdir(parents=True)
        (self.child / "keep.txt").write_text("keep", encoding="utf-8")
        self.assertEqual(catalog.remove(self.a), [self.a, self.child, self.grandchild])
        self.assertEqual(catalog.paths, [self.b])
        self.assertEqual((self.child / "keep.txt").read_text(), "keep")

    def test_config_migrates_v1_and_roundtrips_order_and_parents(self) -> None:
        config = self.home / "config" / "repositories.json"
        config.parent.mkdir()
        config.write_text(json.dumps({
            "version": 1, "repositories": [str(self.b), str(self.a)],
        }), encoding="utf-8")
        loaded = load_repository_entries(config)
        self.assertEqual(loaded, [RepositoryEntry(self.b), RepositoryEntry(self.a)])
        catalog = RepositoryCatalog(loaded)
        catalog.add(self.child, self.a)
        catalog.move(self.a, -1)
        save_repository_entries(catalog.entries, config)
        self.assertEqual(load_repository_entries(config), catalog.entries)
        self.assertEqual(load_repositories(config), catalog.paths)
        data = json.loads(config.read_text(encoding="utf-8"))
        self.assertEqual(data["version"], 2)
        self.assertEqual(data["repositories"][1]["parent"], str(self.a))

    def test_orphan_in_config_is_preserved_as_root(self) -> None:
        catalog = RepositoryCatalog([RepositoryEntry(self.child, self.a)])
        self.assertEqual(catalog.paths, [self.child])
        self.assertIsNone(catalog.find(self.child).parent)


class RealSubmoduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.grand_source = root / "grand-source"
        self.child_source = root / "child-source"
        self.parent = root / "main repository"
        for path in (self.grand_source, self.child_source, self.parent):
            path.mkdir()
            git(path, "init", "-b", "main")
            git(path, "config", "user.name", "Tester")
            git(path, "config", "user.email", "test@example.com")
            (path / "README").write_text("hello\n", encoding="utf-8")
            git(path, "add", "README")
            git(path, "commit", "-m", "init")
        git(self.child_source, "submodule", "add", str(self.grand_source), "vendor/nested")
        git(self.child_source, "commit", "-am", "add nested")
        git(self.parent, "submodule", "add", str(self.child_source), "modules/child")
        git(self.parent, "commit", "-am", "add child")
        self.child = self.parent / "modules" / "child"
        self.nested = self.child / "vendor" / "nested"

    def test_detects_only_initialized_submodules_and_correct_parent(self) -> None:
        # Adding a submodule does not automatically clone its nested submodules.
        self.assertEqual(discover_submodules(self.parent), [(self.child.resolve(), self.parent.resolve())])
        git(self.parent, "submodule", "update", "--init", "--recursive")
        self.assertEqual(discover_submodules(self.parent), [
            (self.child.resolve(), self.parent.resolve()),
            (self.nested.resolve(), self.child.resolve()),
        ])
        self.assertTrue((self.child / ".git").is_file())
        self.assertTrue((self.nested / ".git").is_file())

    def test_does_not_initialize_missing_submodules(self) -> None:
        self.assertFalse((self.nested / ".git").exists())
        discover_submodules(self.parent)
        self.assertFalse((self.nested / ".git").exists())


if __name__ == "__main__":
    unittest.main()
