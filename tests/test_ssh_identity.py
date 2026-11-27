import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest

from thirtyna.ssh_identity import import_identity, existing_identity


class IdentityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.source = self.home / "30na_windows"
        self.generate(self.source)

    def generate(self, path):
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(path)],
                       stdin=subprocess.DEVNULL, check=True, capture_output=True, timeout=5)

    def test_copy_permissions_reuse_and_original_unchanged(self):
        original = self.source.read_bytes()
        self.assertIsNone(existing_identity(self.home))
        key = import_identity(self.home)
        self.assertEqual(key.read_bytes(), original)
        self.assertEqual(key.with_suffix(".pub").read_bytes(), self.source.with_suffix(".pub").read_bytes())
        self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(key.parent.stat().st_mode), 0o700)
        self.assertEqual(import_identity(self.home), key)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(existing_identity(self.home), key)

    def test_mismatch_never_publishes_private_copy(self):
        other = self.home / "other"
        self.generate(other)
        self.source.with_suffix(".pub").write_bytes(other.with_suffix(".pub").read_bytes())
        with self.assertRaisesRegex(RuntimeError, "pair mismatch"):
            import_identity(self.home)
        self.assertIsNone(existing_identity(self.home))

    def test_insecure_source_and_symlink_rejected(self):
        self.source.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, "0600"):
            import_identity(self.home)
        self.source.chmod(0o600)
        other = self.home / "other"
        self.source.rename(other)
        self.source.symlink_to(other)
        with self.assertRaises(OSError):
            import_identity(self.home)
        self.assertIsNone(existing_identity(self.home))

    def test_incomplete_management_copy_not_overwritten(self):
        ssh = self.home / ".ssh"
        ssh.mkdir(mode=0o700)
        directory = ssh / "30na-management"
        directory.mkdir(mode=0o700)
        key = directory / "identity"
        key.write_bytes(b"existing")
        key.chmod(0o600)
        with self.assertRaises(OSError):
            import_identity(self.home)
        self.assertEqual(key.read_bytes(), b"existing")

    def test_fresh_controller_creates_one_reusable_management_key(self):
        self.source.unlink()
        self.source.with_suffix(".pub").unlink()
        key = import_identity(self.home, create=True)
        self.assertEqual(existing_identity(self.home), key)
        original = key.read_bytes()
        self.assertEqual(import_identity(self.home, create=True).read_bytes(), original)
        self.assertFalse(self.source.exists())
