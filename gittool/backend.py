"""Git operations backed by Michael Kennedy's Python package gittyup.

Fetch and revision counting use Git's plumbing because gittyup 1.2 only exposes
working-tree status, not ahead/behind tracking information.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import threading
from typing import Iterator

from gittyup import git_operations, scanner

from .git_process import configure_gittyup, run_git

# Install per-Git-process console suppression before any Gittyup status/pull.
configure_gittyup()


LOCAL_TIMEOUT = 20
NETWORK_TIMEOUT = 120
_PULL_LOCK = threading.Lock()


class GitToolError(RuntimeError):
    """A repository cannot be inspected or safely updated."""


@dataclass(frozen=True)
class RepositoryState:
    path: Path
    branch: str = ""
    upstream: str = ""
    dirty: bool = False
    ahead: int = 0
    behind: int = 0
    status: str = "Nicht geprüft"
    detail: str = ""
    can_pull: bool = False

    @property
    def name(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class PullOutcome:
    state: RepositoryState
    action: str
    message: str


def _git(path: Path, *args: str, timeout: int = LOCAL_TIMEOUT, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a Git command without an interactive terminal prompt."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        result = run_git(
            ["git", *args],
            cwd=path,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except FileNotFoundError as exc:
        raise GitToolError("Git ist nicht installiert oder nicht im PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitToolError(f"Zeitüberschreitung bei git {args[0]} ({timeout} s).") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise GitToolError(f"git {args[0]}: {detail or 'Unbekannter Fehler'}")
    return result


def normalize_repository(value: str | Path) -> Path:
    """Validate that the chosen folder is the top level of a Git worktree."""
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise GitToolError(f"Verzeichnis existiert nicht: {path}")
    result = _git(path, "rev-parse", "--show-toplevel")
    root = Path(result.stdout.strip()).resolve()
    if os.path.normcase(str(root)) != os.path.normcase(str(path)):
        raise GitToolError(f"Bitte Repository-Stammordner auswählen: {root}")
    return path


def discover_repositories(root: Path) -> list[Path]:
    """Use gittyup's directory scanner; also detect .git-file worktrees."""
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise GitToolError(f"Verzeichnis existiert nicht: {root}")
    result = scanner.scan_directory(root)
    paths = {p.resolve() for p in (repo.path for repo in result.repositories)}
    # gittyup 1.2 recognises .git directories, but not linked worktrees /
    # submodules using .git *files*. Walk those as an additional case.
    for folder, dirs, filenames in os.walk(root, followlinks=False):
        if ".git" in filenames:
            candidate = Path(folder)
            try:
                paths.add(normalize_repository(candidate))
            except GitToolError:
                pass
            dirs[:] = []
        elif ".git" in dirs:
            dirs[:] = []
        else:
            dirs[:] = [
                d for d in dirs
                if d not in scanner.DEFAULT_EXCLUDE_DIRS and not (Path(folder) / d).is_symlink()
            ]
    if (root / ".git").is_dir() or (root / ".git").is_file():
        paths.add(normalize_repository(root))
    return sorted(paths, key=lambda p: str(p).casefold())


def inspect_repository(value: str | Path, *, fetch: bool = True) -> RepositoryState:
    """Refresh remote refs, then inspect branch, tree and ahead/behind counts.

    Never changes the current branch, index or working tree.
    """
    path = normalize_repository(value)
    flags = git_operations.get_repo_status(path, timeout=LOCAL_TIMEOUT)
    branch = git_operations.get_current_branch(path, timeout=LOCAL_TIMEOUT)
    porcelain = _git(path, "status", "--porcelain=v1", "--untracked-files=normal").stdout
    dirty = bool(porcelain.strip())

    if flags["is_detached"] or branch is None:
        return RepositoryState(path, branch="(detached)", dirty=dirty,
                               status="Detached HEAD", detail="Kein Pull auf detached HEAD.")
    if not flags["has_remote"]:
        return RepositoryState(path, branch=branch, dirty=dirty,
                               status="Kein Remote", detail="Kein Remote konfiguriert.")

    upstream_result = _git(
        path, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}",
        check=False,
    )
    if upstream_result.returncode != 0:
        return RepositoryState(path, branch=branch, dirty=dirty,
                               status="Kein Upstream", detail="Tracking-Branch fehlt.")

    upstream = upstream_result.stdout.strip()
    if fetch:
        # Fetch only the upstream's configured remote. Some branches track a
        # local branch (remote='.'), for which network fetch is inappropriate.
        remote = _git(path, "config", "--get", f"branch.{branch}.remote", check=False).stdout.strip()
        if remote and remote != ".":
            _git(path, "fetch", "--prune", "--no-tags", remote, timeout=NETWORK_TIMEOUT)

    counts = _git(path, "rev-list", "--left-right", "--count", "HEAD...@{upstream}").stdout.split()
    if len(counts) != 2:
        raise GitToolError("Ungültige Ahead/Behind-Angabe von Git.")
    ahead, behind = (int(x) for x in counts)

    if ahead and behind:
        status, detail = "Divergiert", "Lokale und entfernte Commits: manuell lösen."
    elif dirty:
        status, detail = "Lokale Änderungen", "Uncommittete/geänderte Dateien: Pull gesperrt."
    elif ahead:
        status, detail = "Nur lokal voraus", "Lokale Commits vorhanden; kein automatischer Pull."
    elif behind:
        status, detail = "Pull möglich", f"{behind} entfernte(s) Commit(s) verfügbar."
    else:
        status, detail = "Aktuell", "Keine entfernten Commits ausstehend."

    return RepositoryState(
        path=path, branch=branch, upstream=upstream,
        dirty=dirty, ahead=ahead, behind=behind,
        status=status, detail=detail,
        can_pull=(not dirty and ahead == 0 and behind > 0),
    )


@contextmanager
def _fast_forward_only_environment() -> Iterator[None]:
    """Enforce ff-only when gittyup internally invokes plain 'git pull'.

    Git supports command-scoped configuration via GIT_CONFIG_COUNT/KEY/VALUE.
    This changes no repository configuration. The caller holds _PULL_LOCK.
    """
    old_count = os.environ.get("GIT_CONFIG_COUNT")
    try:
        count = int(old_count or "0")
    except ValueError as exc:
        raise GitToolError("Ungültige GIT_CONFIG_COUNT-Umgebungsvariable.") from exc
    names = ("GIT_TERMINAL_PROMPT", "GIT_CONFIG_COUNT",
             f"GIT_CONFIG_KEY_{count}", f"GIT_CONFIG_VALUE_{count}",
             f"GIT_CONFIG_KEY_{count + 1}", f"GIT_CONFIG_VALUE_{count + 1}")
    previous = {name: os.environ.get(name) for name in names}
    try:
        os.environ["GIT_TERMINAL_PROMPT"] = "0"
        os.environ["GIT_CONFIG_COUNT"] = str(count + 2)
        os.environ[f"GIT_CONFIG_KEY_{count}"] = "pull.ff"
        os.environ[f"GIT_CONFIG_VALUE_{count}"] = "only"
        os.environ[f"GIT_CONFIG_KEY_{count + 1}"] = "pull.rebase"
        os.environ[f"GIT_CONFIG_VALUE_{count + 1}"] = "false"
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def pull_repository(value: str | Path) -> PullOutcome:
    """Fetch, check safety preconditions, then pull through gittyup.

    Dirty, detached, nontracking, ahead and diverged repositories are skipped.
    """
    with _PULL_LOCK:
        before = inspect_repository(value, fetch=True)
        if not before.can_pull:
            action = "Aktuell" if before.status == "Aktuell" else "Übersprungen"
            return PullOutcome(before, action, before.detail)

        # gittyup's public API parses pull output and commit/file statistics.
        # Its default implementation calls plain 'git pull', therefore force
        # ff-only in the child Git process rather than altering local config.
        with _fast_forward_only_environment():
            result = git_operations.pull_repository_detailed(before.path, timeout=NETWORK_TIMEOUT)

        if not result.success:
            detail = result.error_details or result.error_message or "Unbekannter Pull-Fehler"
            raise GitToolError(detail)

        after = inspect_repository(before.path, fetch=False)
        action = "Aktuell" if result.already_up_to_date else "Aktualisiert"
        message = result.full_output or (
            "Bereits aktuell." if result.already_up_to_date else "Fast-forward erfolgreich."
        )
        return PullOutcome(after, action, message.strip())


def discover_submodules(root: str | Path) -> list[tuple[Path, Path]]:
    """Discover initialized Git submodules, preserving their direct parent.

    Git's index has mode 160000 for gitlinks, even if no .gitmodules exists.
    A submodule is included only if its worktree is initialized and its own
    repository root can be verified. Never execute submodule init/update.
    """
    root = normalize_repository(root)
    found: list[tuple[Path, Path]] = []
    visited: set[Path] = {root}

    def descend(parent: Path) -> None:
        result = _git(parent, "ls-files", "--stage", "-z")
        for record in result.stdout.split("\0"):
            if not record or "\t" not in record:
                continue
            meta, relative = record.split("\t", 1)
            fields = meta.split()
            if len(fields) != 3 or fields[0] != "160000" or fields[2] != "0":
                continue
            candidate = (parent / relative).resolve()
            if candidate in visited or not candidate.is_relative_to(parent):
                continue
            if not candidate.is_dir() or not (
                (candidate / ".git").is_file() or (candidate / ".git").is_dir()
            ):
                continue  # Uninitialized gitlink: do not clone or change disk contents.
            try:
                validated = normalize_repository(candidate)
            except GitToolError:
                continue
            visited.add(validated)
            found.append((validated, parent))
            descend(validated)

    descend(root)
    return found
