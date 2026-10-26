"""Regression tests for the Tkinter GUI startup issue.

The original GitToolApp._register(path) method replaced Tkinter's internal
Misc._register(callback) method and crashed before displaying any window.
"""
from __future__ import annotations

import os
import tkinter as tk
import unittest

from gittool.app import GitToolApp


class GuiStartupTests(unittest.TestCase):
    def test_tkinter_callback_registration_is_not_overridden(self) -> None:
        self.assertIs(
            GitToolApp._register,
            tk.Misc._register,
            "The GUI must not override Tkinter's private callback registrar.",
        )
        self.assertIn("_add_repository", GitToolApp.__dict__)

    @unittest.skipUnless(os.environ.get("DISPLAY"), "Graphical display is unavailable")
    def test_main_window_can_be_created(self) -> None:
        app = GitToolApp()
        try:
            app.update_idletasks()
            self.assertTrue(app.winfo_exists())
            self.assertEqual(app.title(), "GitTool – Repository-Status & Pull (gittyup)")
        finally:
            app._close()
