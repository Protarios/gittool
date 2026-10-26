"""Offline backend regression tests using real local Git repositories."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest


def git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=path, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode:
        raise AssertionError(f"git {args} failed:\n{result.stderr}")
    return result.stdout.strip()


# The project requires Python 3.13 for the real gittyup dependency. In local
# test environments without it, supply only the small API surface we use.
if importlib.util.find_spec("gittyup") is None:
    gittyup = types.ModuleType("gittyup")
    operations = types.ModuleType("gittyup.git_operations")
    scanner = types.ModuleType("gittyup.scanner")

    def get_repo_status(path: Path, timeout: int = 10) -> dict[str, bool]:
        branch = subprocess.run(
            ["git", "symbolic-ref", "-q", "HEAD"], cwd=path,
            capture_output=True,
        )
        return {
            "is_detached": branch.returncode != 0,
            "has_remote": bool(git(path, "remote")),
            "has_upstream": subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "@{upstream}"],
                cwd=path, capture_output=True,
            ).returncode == 0,
            "is_clean": not bool(git(path, "status", "--porcelain")),
        }

    def get_current_branch(path: Path, timeout: int = 10) -> str | None:
        ref = git(path, "rev-parse", "--abbrev-ref", "HEAD")
        return None if ref == "HEAD" else ref

    def pull_repository_detailed(path: Path, timeout: int = 60) -> object:
        result = subprocess.run(
            ["git", "pull"], cwd=path, capture_output=True,
            text=True, encoding="utf-8", errors="replace",
        )
        return types.SimpleNamespace(
            success=result.returncode == 0,
            already_up_to_date="Already up to date" in result.stdout,
            full_output=result.stdout + result.stderr,
            error_details=result.stderr,
            error_message=result.stderr,
        )

    def scan_directory(root: Path) -> object:
        found = []
        for folder, dirs, _files in os.walk(root):
            if ".git" in dirs:
                found.append(types.SimpleNamespace(path=Path(folder)))
                dirs[:] = []
        return types.SimpleNamespace(repositories=found)

    operations.get_repo_status = get_repo_status
    operations.get_current_branch = get_current_branch
    operations.pull_repository_detailed = pull_repository_detailed
    scanner.scan_directory = scan_directory
    scanner.DEFAULT_EXCLUDE_DIRS = {"venv", ".venv", "node_modules"}
    gittyup.git_operations = operations
    gittyup.scanner = scanner
    sys.modules["gittyup"] = gittyup
    sys.modules["gittyup.git_operations"] = operations
    sys.modules["gittyup.scanner"] = scanner

from gittool.backend import (  # noqa: E402
    GitToolError, discover_repositories, inspect_repository,
    normalize_repository, pull_repository,
)
from gittool.config import load_repositories, save_repositories  # noqa: E402


class RepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.remote = root / "remote.git"
        self.seed = root / "seed"
        self.clone = root / "clone"
        git(root, "init", "--bare", str(self.remote))
        git(root, "init", str(self.seed))
        git(self.seed, "config", "user.email", "test@example.com")
        git(self.seed, "config", "user.name", "Test")
        git(self.seed, "checkout", "-b", "main")
        (self.seed / "example.txt").write_text("first\n")
        git(self.seed, "add", ".")
        git(self.seed, "commit", "-m", "first")
        git(self.seed, "remote", "add", "origin", str(self.remote))
        git(self.seed, "push", "-u", "origin", "main")
        git(self.remote, "symbolic-ref", "HEAD", "refs/heads/main")
        git(root, "clone", str(self.remote), str(self.clone))
        git(self.clone, "config", "user.email", "test@example.com")
        git(self.clone, "config", "user.name", "Test")

    def make_remote_commit(self) -> None:
        with (self.seed / "example.txt").open("a") as handle:
            handle.write("remote\n")
        git(self.seed, "commit", "-am", "remote update")
        git(self.seed, "push")

    def test_check_then_fast_forward_pull(self) -> None:
        self.make_remote_commit()
        before = inspect_repository(self.clone)
        self.assertEqual((before.ahead, before.behind), (0, 1))
        self.assertTrue(before.can_pull)
        result = pull_repository(self.clone)
        self.assertEqual(result.action, "Aktualisiert")
        self.assertEqual((result.state.ahead, result.state.behind), (0, 0))
        self.assertIn("remote", (self.clone / "example.txt").read_text())

    def test_dirty_tree_blocks_pull(self) -> None:
        self.make_remote_commit()
        (self.clone / "extra.txt").write_text("untracked")
        state = inspect_repository(self.clone)
        self.assertTrue(state.dirty)
        self.assertFalse(state.can_pull)
        self.assertEqual(pull_repository(self.clone).action, "Übersprungen")

    def test_divergence_blocks_pull(self) -> None:
        (self.clone / "local.txt").write_text("local")
        git(self.clone, "add", ".")
        git(self.clone, "commit", "-m", "local")
        self.make_remote_commit()
        state = inspect_repository(self.clone)
        self.assertEqual((state.ahead, state.behind), (1, 1))
        self.assertEqual(state.status, "Divergiert")
        self.assertFalse(state.can_pull)
        self.assertEqual(pull_repository(self.clone).action, "Übersprungen")

    def test_untracked_branch_and_detached_head(self) -> None:
        git(self.clone, "checkout", "-b", "local-only")
        self.assertEqual(inspect_repository(self.clone).status, "Kein Upstream")
        git(self.clone, "checkout", "--detach")
        self.assertEqual(inspect_repository(self.clone).status, "Detached HEAD")

    def test_invalid_directory(self) -> None:
        with self.assertRaises(GitToolError):
            normalize_repository(self.clone / "missing")

    def test_scanner_finds_normal_repository(self) -> None:
        self.assertIn(self.clone, discover_repositories(self.clone.parent))

    def test_saved_list(self) -> None:
        path = self.clone.parent / "config" / "repositories.json"
        save_repositories([self.clone], path)
        self.assertEqual(load_repositories(path), [self.clone])


if __name__ == "__main__":
    unittest.main()
