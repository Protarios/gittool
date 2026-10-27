"""Execute Git subprocesses without flashing console windows on Windows.

Python GUI executables (pythonw.exe / PyInstaller --windowed) have no console,
but git.exe is a console program and opens one when created normally.
The flags belong to each child process, not to PyInstaller's own window.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Any


def run_git(
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 10,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess; hide its console on Windows without suppressing output."""
    # Do not affect other programs or globally monkeypatch subprocess.run.
    if os.name == "nt":
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
    return subprocess.run(command, cwd=cwd, timeout=timeout, **kwargs)


def configure_gittyup() -> None:
    """Apply the same process policy to gittyup 1.x's synchronous Git helper.

    This touches only gittyup's dedicated launcher, not subprocess.run
    globally; every gittyup status/fetch/pull call uses this helper.
    """
    if os.name != "nt":
        return

    from gittyup import git_operations

    # gittyup 1.2.0 uses this private synchronous helper for its public APIs.
    # Keep the integration narrow rather than monkeypatching all subprocesses.
    if not callable(getattr(git_operations, "_run_git_command", None)):
        raise RuntimeError(
            "Diese Gittyup-Version hat keinen unterstützten Git-Prozessstarter. "
            "Bitte gittyup 1.2.x verwenden."
        )

    def _run_git_command_no_console(
        command: list[str],
        cwd: Path | None = None,
        timeout: int = 10,
    ) -> subprocess.CompletedProcess[str]:
        return run_git(command, cwd=cwd, timeout=timeout, capture_output=True, text=True)

    git_operations._run_git_command = _run_git_command_no_console
