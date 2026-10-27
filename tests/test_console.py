"""Regression: windowed GitTool never creates child git.exe console windows."""
from __future__ import annotations

import os
import subprocess
from unittest.mock import patch
import unittest

from gittyup import git_operations

from gittool import git_process


class ConsoleWindowTests(unittest.TestCase):
    def test_git_child_uses_create_no_window_on_windows(self) -> None:
        # Simulate win32 even on CI Linux; no process is launched.
        with (
            patch.object(git_process.os, "name", "nt"),
            patch.object(git_process.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True),
            patch.object(git_process.subprocess, "run") as run,
        ):
            git_process.run_git(["git", "--version"], timeout=7, capture_output=True)
        self.assertEqual(run.call_args.args[0], ["git", "--version"])
        self.assertEqual(run.call_args.kwargs["creationflags"] & 0x08000000, 0x08000000)
        self.assertEqual(run.call_args.kwargs["timeout"], 7)
        self.assertTrue(run.call_args.kwargs["capture_output"])

    def test_other_platforms_do_not_receive_windows_specific_flags(self) -> None:
        with (
            patch.object(git_process.os, "name", "posix"),
            patch.object(git_process.subprocess, "run") as run,
        ):
            git_process.run_git(["git", "--version"])
        self.assertNotIn("creationflags", run.call_args.kwargs)

    def test_gittyup_uses_same_no_console_child_launcher(self) -> None:
        # gittyup's public status/pull methods call _run_git_command. The
        # adapter must preserve capture_output/text/timeout arguments.
        with (
            patch.object(git_process.os, "name", "nt"),
            patch.object(git_operations, "_run_git_command"),
            patch.object(git_process, "run_git") as run,
        ):
            git_process.configure_gittyup()
            git_operations._run_git_command(["git", "status"], timeout=22)
            run.assert_called_once_with(
                ["git", "status"], cwd=None, timeout=22,
                capture_output=True, text=True,
            )

    @unittest.skipUnless(os.name == "nt", "Real subprocess flags only apply on Windows")
    def test_actual_gittyup_subprocess_has_no_console_creation_flag(self) -> None:
        original = git_process.subprocess.run
        arguments = []

        def spy(*args, **kwargs):
            arguments.append(kwargs)
            return original(*args, **kwargs)

        # Ensure backend import has configured the library.
        from gittool import backend  # noqa: F401

        with patch.object(git_process.subprocess, "run", side_effect=spy):
            result = git_operations._run_git_command(["git", "--version"])
        self.assertEqual(result.returncode, 0)
        self.assertTrue(arguments)
        self.assertTrue(arguments[0]["creationflags"] & subprocess.CREATE_NO_WINDOW)


if __name__ == "__main__":
    unittest.main()
