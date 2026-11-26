import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from thirtyna.menus.model import MenuSession

CLI = Path(__file__).resolve().parents[1] / "30na"


class MenuTests(unittest.TestCase):
    def test_navigation_and_stale_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            start = Path(tmp).resolve()
            child = start / "child"
            child.mkdir()
            (start / "file").touch()
            session = MenuSession(start)
            session.select(session.items[0])
            self.assertEqual([item.title for item in session.items], ["..", "child/"])
            session.select(session.items[1])
            self.assertEqual(session.title, str(child))
            session.select(session.items[0])
            child.rmdir()
            session.select(session.items[1])
            self.assertTrue(session.error)
            self.assertEqual(session.title, str(start))
            session.back()
            self.assertFalse(session.done)
            session.back()
            self.assertTrue(session.done)

    def test_numbered_and_optional_backends(self):
        with tempfile.TemporaryDirectory() as tmp:
            def run(*args, data=""):
                return subprocess.run([CLI, "-menu", *args], cwd=tmp, input=data,
                                      text=True, capture_output=True, timeout=5,
                                      env=dict(os.environ, DISPLAY=""))
            result = run("-dir", data="bad\n0\n")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(tmp, result.stdout)
            self.assertIn("listed number", result.stdout)
            self.assertEqual(run("-gui", "-tui").returncode, 2)
            self.assertEqual(run("-tui").returncode, 1)
            self.assertEqual(run("-gui").returncode, 1)
