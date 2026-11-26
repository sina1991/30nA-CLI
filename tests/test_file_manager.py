import tempfile
import unittest
from pathlib import Path
from thirtyna.menus.files import named, relocate, remove, transfer


class FileActions(unittest.TestCase):
    def test_copy_move_rename_and_collisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "source"
            src.write_text("original")
            copy = root / "copy"
            transfer(src, copy)
            with self.assertRaises(FileExistsError):
                transfer(src, copy, move=True)
            relocate(copy, root / "renamed")
            transfer(src, copy, move=True)
            self.assertFalse(src.exists())
            self.assertEqual(copy.read_text(), "original")
            remove(copy)

    def test_directories_and_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "dir"
            folder.mkdir()
            (folder / "link").symlink_to("missing")
            with self.assertRaises(ValueError):
                transfer(folder, folder / "nested")
            transfer(folder, root / "copy")
            self.assertTrue((root / "copy/link").is_symlink())
            with self.assertRaises(OSError):
                remove(folder)
            with self.assertRaises(ValueError):
                named(root, "../outside")
