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


def _read_local_status(path: Path) -> tuple[str, str, bool, int | None, int | None]:
    """Read stable Git porcelain v2 status and potentially absent branch.ab.

    Git may report branch.upstream while omitting branch.ab if the
    remote-tracking ref has not been fetched. Missing counters are unknown,
    never automatically treated as +0/-0 (up-to-date).
    """
    result = _git(
        path, "status", "--porcelain=v2", "--branch", "--untracked-files=normal",
    )
    head = upstream = ""
    ahead: int | None = None
    behind: int | None = None
    dirty = False
    for line in result.stdout.splitlines():
        if line.startswith("# branch.head "):
            head = line[len("# branch.head "):]
        elif line.startswith("# branch.upstream "):
            upstream = line[len("# branch.upstream "):]
        elif line.startswith("# branch.ab "):
            fields = line[len("# branch.ab "):].split()
            if len(fields) != 2:
                raise GitToolError("Ungültige Ahead/Behind-Angabe von Git.")
            ahead, behind = int(fields[0]), -int(fields[1])
        elif line and not line.startswith("# "):
            dirty = True
    if not head:
        raise GitToolError("Git hat keinen Branch-Status geliefert.")
    return head, upstream, dirty, ahead, behind


def _upstream_config(path: Path, branch: str) -> tuple[str, str]:
    """Read the canonical per-branch Git configuration without guessing."""
    remote = _git(
        path, "config", "--get", f"branch.{branch}.remote", check=False,
    ).stdout.strip()
    merge = _git(
        path, "config", "--get", f"branch.{branch}.merge", check=False,
    ).stdout.strip()
    return remote, merge


def _resolve_upstream(path: Path) -> str:
    """Ask Git to resolve the tracking ref if porcelain omitted it."""
    result = _git(
        path, "rev-parse", "--abbrev-ref", "--symbolic-full-name",
        "@{upstream}", check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def inspect_repository(value: str | Path, *, fetch: bool = True) -> RepositoryState:
    """Inspect branch and tracking relationship; never merge or switch branches.

    Fetch existing configured remotes even when upstream is not currently
    resolvable, because an unfetched tracking ref should not be mistaken
    for an unset branch configuration.
    """
    path = normalize_repository(value)
    branch, upstream, dirty, ahead, behind = _read_local_status(path)

    if branch == "(detached)":
        return RepositoryState(
            path, branch=branch, dirty=dirty,
            status="Detached HEAD", detail="Kein Pull auf detached HEAD.",
        )

    remote = merge = ""
    if not upstream or ahead is None or behind is None or fetch:
        remote, merge = _upstream_config(path, branch)

    if fetch and remote and remote != ".":
        # Fetch tracking refs before classification; never touches the worktree.
        _git(path, "fetch", "--prune", "--no-tags", remote, timeout=NETWORK_TIMEOUT)
        branch, upstream, dirty, ahead, behind = _read_local_status(path)

    if not upstream:
        upstream = _resolve_upstream(path)

    if not upstream:
        if remote and merge:
            # push --set-upstream may configure origin/WiSe26 even when
            # remote.origin.fetch does not map that ref locally.
            configured = (
                f"{remote}/{merge.removeprefix('refs/heads/')}"
                if merge.startswith("refs/heads/") and remote != "." else merge
            )
            return RepositoryState(
                path, branch=branch, upstream=configured, dirty=dirty,
                status="Tracking-Ref fehlt",
                detail=(
                    f"Tracking-Branch konfiguriert ({configured}), aber nicht "
                    f"auflösbar. Remote-Fetch-Refspec prüfen. Repository: {path}"
                ),
            )
        has_remote = bool(_git(path, "remote").stdout.strip())
        return RepositoryState(
            path, branch=branch, dirty=dirty,
            status="Kein Upstream" if has_remote else "Kein Remote",
            detail=(
                f"Kein Tracking-Branch für {branch} konfiguriert. Repository: {path}"
                if has_remote else f"Kein Remote konfiguriert. Repository: {path}"
            ),
        )

    if ahead is None or behind is None:
        # branch.upstream may exist without the remote-tracking ref.
        counts = _git(
            path, "rev-list", "--left-right", "--count",
            "HEAD...@{upstream}", check=False,
        )
        if counts.returncode != 0:
            return RepositoryState(
                path, branch=branch, upstream=upstream, dirty=dirty,
                status="Tracking-Ref fehlt",
                detail=(
                    f"Tracking-Branch {upstream} ist konfiguriert, dessen "
                    f"Referenz ist aber lokal nicht verfügbar. Repository: {path}"
                ),
            )
        fields = counts.stdout.split()
        if len(fields) != 2:
            raise GitToolError("Ungültige Ahead/Behind-Angabe von Git.")
        ahead, behind = (int(x) for x in fields)

    if ahead and behind:
        status, detail = "Divergiert", "Lokale und entfernte Commits: manuell lösen."
    elif dirty and behind and not ahead:
        status = "Lokal geändert · Pull möglich"
        detail = (
            f"{behind} entfernte(s) Commit(s) verfügbar. "
            "Fast-Forward nach Dateiprüfung und Bestätigung möglich."
        )
    elif dirty and ahead:
        status, detail = (
            "Lokal geändert · Lokal voraus",
            "Lokale Änderungen und eigene Commits vorhanden; kein automatischer Pull.",
        )
    elif dirty:
        status, detail = (
            "Lokal geändert · Aktuell",
            "Lokale Änderungen vorhanden; keine entfernten Commits ausstehend.",
        )
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



@dataclass(frozen=True)
class LocalChange:
    """One changed path, preserving its Git status code for the review dialog."""
    status: str
    path: str


@dataclass(frozen=True)
class PullPreview:
    """Immutable result of a fetch + fast-forward and local-path safety check."""
    state: RepositoryState
    changes: tuple[LocalChange, ...] = ()
    overlaps: tuple[str, ...] = ()
    head_oid: str = ""
    target_oid: str = ""

    @property
    def needs_confirmation(self) -> bool:
        return bool(
            self.state.dirty and self.state.ahead == 0
            and self.state.behind > 0 and self.state.upstream
            and self.head_oid and self.target_oid
        )

    @property
    def safe_to_continue(self) -> bool:
        return self.needs_confirmation and not self.overlaps


def _local_changes(path: Path) -> tuple[LocalChange, ...]:
    """Parse -z porcelain to avoid quoted path ambiguities and list ALL PDFs."""
    result = _git(
        path, "status", "--porcelain=v1", "-z",
        "--untracked-files=all", "--ignore-submodules=none",
    )
    parts = result.stdout.split("\0")
    changes: list[LocalChange] = []
    index = 0
    while index < len(parts):
        entry = parts[index]
        index += 1
        if not entry:
            continue
        if len(entry) < 4 or entry[2] != " ":
            raise GitToolError("Ungültige Dateiliste von git status.")
        code = entry[:2]
        name = entry[3:]
        changes.append(LocalChange(code, name))
        # Porcelain v1 -z puts the second pathname directly after a
        # rename/copy entry (new path first, original path second).
        if "R" in code or "C" in code:
            if index >= len(parts) or not parts[index]:
                raise GitToolError("Unvollständiger Git-Rename-/Copy-Eintrag.")
            changes.append(LocalChange(code, parts[index]))
            index += 1
    return tuple(changes)


def _path_overlap(left: str, right: str) -> bool:
    """Conservatively catch identical paths and file/directory replacements."""
    # Git tree paths always use '/' regardless of host OS.
    a = left.replace("\\", "/").rstrip("/")
    b = right.replace("\\", "/").rstrip("/")
    if os.name == "nt":
        a, b = a.casefold(), b.casefold()
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def _incoming_changed_paths(path: Path) -> tuple[str, ...]:
    """All tree paths changed by the incoming fast-forward, including deletions."""
    result = _git(
        path, "diff", "--name-only", "-z", "--no-renames",
        "--ignore-submodules=none", "HEAD", "@{upstream}",
    )
    return tuple(p for p in result.stdout.split("\0") if p)


def prepare_pull(value: str | Path) -> PullPreview:
    """Fetch first, then provide a bounded, read-only local-change review."""
    state = inspect_repository(value, fetch=True)
    if not (state.dirty and state.ahead == 0 and state.behind > 0 and state.upstream):
        return PullPreview(state)
    changes = _local_changes(state.path)
    if not changes:
        raise GitToolError("Lokale Änderungen konnten nicht vollständig erfasst werden.")
    incoming = _incoming_changed_paths(state.path)
    overlaps = tuple(sorted({
        change.path
        for change in changes
        if any(_path_overlap(change.path, modified) for modified in incoming)
    }))
    head = _git(state.path, "rev-parse", "HEAD").stdout.strip()
    target = _git(state.path, "rev-parse", "@{upstream}").stdout.strip()
    return PullPreview(state, changes, overlaps, head, target)


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


def pull_repository(
    value: str | Path, *, approved_preview: PullPreview | None = None,
    checked_state: RepositoryState | None = None,
) -> PullOutcome:
    """Fast-forward only; permit safe dirty trees with explicit prior approval.

    For approved dirty worktrees, merge the *already fetched exact commit*,
    rather than running a second network fetch inside gittyup. The preflight
    checks incoming changed paths and Git itself refuses local overwrites.
    """
    with _PULL_LOCK:
        if approved_preview is not None:
            if not approved_preview.safe_to_continue:
                raise GitToolError("Ein Pull mit kollidierenden lokalen Änderungen ist gesperrt.")
            path = normalize_repository(value)
            if path != approved_preview.state.path:
                raise GitToolError("Repository-Pfad hat sich seit der Freigabe geändert.")
            # Reinspect immediately before updating (including status, refs).
            before = inspect_repository(path, fetch=False)
            if not (
                before.dirty and before.ahead == 0 and before.behind > 0
                and before.upstream == approved_preview.state.upstream
                and before.branch == approved_preview.state.branch
                and _git(path, "rev-parse", "HEAD").stdout.strip()
                    == approved_preview.head_oid
                and _git(path, "rev-parse", "@{upstream}").stdout.strip()
                    == approved_preview.target_oid
            ):
                raise GitToolError(
                    "Git-Stand hat sich seit der Bestätigung geändert. "
                    "Bitte erneut prüfen und bestätigen."
                )
            current_changes = _local_changes(path)
            if current_changes != approved_preview.changes:
                raise GitToolError(
                    "Lokale Dateiliste hat sich seit der Bestätigung geändert. "
                    "Bitte erneut prüfen und bestätigen."
                )
            if any(
                _path_overlap(change.path, incoming)
                for change in current_changes
                for incoming in _incoming_changed_paths(path)
            ):
                raise GitToolError("Dateiüberschneidung erkannt; Pull sicherheitshalber abgebrochen.")
            # A fast-forward move to a pinned object is equivalent to fetch +
            # ff-only pull, without a second fetch invalidating the preview.
            # Git refuses to overwrite local changes even in unforeseen cases.
            result = _git(
                path, "-c", "merge.autoStash=false",
                "merge", "--ff-only", approved_preview.target_oid,
                timeout=NETWORK_TIMEOUT,
            )
            after = inspect_repository(path, fetch=False)
            return PullOutcome(
                after, "Aktualisiert",
                (result.stdout + result.stderr).strip()
                or "Fast-forward erfolgreich; lokale Dateien unverändert.",
            )

        before = checked_state if checked_state is not None else inspect_repository(value, fetch=True)
        if checked_state is not None and normalize_repository(value) != before.path:
            raise GitToolError("Repository-Pfad der Vorprüfung stimmt nicht überein.")
        if not before.can_pull:
            action = "Aktuell" if before.status == "Aktuell" else "Übersprungen"
            if before.dirty and before.behind > 0 and before.ahead == 0:
                return PullOutcome(
                    before, "Übersprungen",
                    "Lokale Änderungen: Pull nur nach Prüfung und Bestätigung möglich.",
                )
            return PullOutcome(before, action, before.detail)

        # Keep clean worktrees on gittyup's existing, proven ff-only path.
        with _fast_forward_only_environment():
            result = git_operations.pull_repository_detailed(
                before.path, timeout=NETWORK_TIMEOUT,
            )

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
