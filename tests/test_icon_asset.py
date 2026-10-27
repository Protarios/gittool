"""The same branded PNG is available from every installation mode."""
from __future__ import annotations

from importlib import resources
import struct
import unittest


class IconResourceTests(unittest.TestCase):
    def test_gittool_png_is_installed_and_square(self) -> None:
        asset = resources.files("gittool").joinpath("assets", "gittool.png")
        data = asset.read_bytes()
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(data), 1024)
        width, height = struct.unpack(">II", data[16:24])
        self.assertEqual(width, height)
        self.assertGreaterEqual(width, 128)


if __name__ == "__main__":
    unittest.main()
