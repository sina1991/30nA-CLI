import contextlib
import hashlib
import io
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from thirtyna import backup_peer, ssh_backup


class BackupTests(unittest.TestCase):
    def generate(self, path):
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(path)],
                       check=True, capture_output=True)

    def test_restore_pair_backups_and_idempotency(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stage = root / "stage"
            home = root / "home"
            stage.mkdir()
            home.mkdir()
            key = stage / "30na_windows"
            self.generate(key)
            old = home / "30na_windows"
            old.write_bytes(b"old private fixture")
            with contextlib.redirect_stdout(io.StringIO()):
                backup_peer.restore(stage, home)
                backup_peer.restore(stage, home)
            targets = [home / "30na_windows", home / ".ssh/id_ed25519",
                       home / ".ssh/30na-management/identity"]
            for target in targets:
                self.assertEqual(target.read_bytes(), key.read_bytes())
                self.assertEqual(target.stat().st_mode & 0o777, 0o600)
                self.assertEqual(target.with_suffix(".pub").read_bytes(),
                                 key.with_suffix(".pub").read_bytes())
            backups = list((home / ".ssh").glob("30na-key-backup.*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0] / "30na_windows").read_bytes(), b"old private fixture")
            expected = b" ".join(key.with_suffix(".pub").read_bytes().split()[:2])
            self.assertEqual((home / ".ssh/authorized_keys").read_bytes().count(expected), 1)

    def test_invalid_pair_preserves_existing_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            home.mkdir()
            self.generate(root / "30na_windows")
            self.generate(root / "other")
            (root / "30na_windows.pub").write_bytes((root / "other.pub").read_bytes())
            old = home / "30na_windows"
            old.write_bytes(b"existing key fixture")
            with self.assertRaisesRegex(RuntimeError, "invalid or mismatched"):
                backup_peer.restore(root, home)
            self.assertEqual(old.read_bytes(), b"existing key fixture")

    def test_receiver_verifies_transfer_before_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            data = b"encrypted archive fixture"
            argv = [sys.executable, "-c", ssh_backup.RECEIVER,
                    hashlib.sha256(data).hexdigest(), str(len(data))]
            env = dict(os.environ, HOME=str(home))
            subprocess.run(argv, input=data, env=env, check=True)
            archive = home / "30na-SSH-Backup.zip"
            self.assertEqual(archive.read_bytes(), data)
            failed = subprocess.run(argv, input=b"corrupt", env=env, capture_output=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual(archive.read_bytes(), data)
            self.assertEqual(archive.stat().st_mode & 0o777, 0o600)

    @patch("thirtyna.ssh_backup.sys.stdin.isatty", return_value=True)
    @patch("thirtyna.ssh_backup.subprocess.run")
    def test_zip_password_uses_remote_tty(self, run, tty):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "30na-SSH-Backup.zip"
            archive.write_bytes(b"encrypted fixture")
            run.return_value = subprocess.CompletedProcess([], 0)
            ssh_backup.restore_backup("ssh.example.test", Path(temp) / "identity", archive)
            calls = run.call_args_list
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0].args[0][1], "-T")
            self.assertEqual(calls[1].args[0][1], "-tt")
            script = shlex.split(calls[1].args[0][-1])[2]
            self.assertIn("</dev/tty", script)
            self.assertIn("7z e -r -y", script)
            self._real_run(["bash", "-n"], input=script, text=True, check=True)

    _real_run = staticmethod(subprocess.run)

    @patch("thirtyna.ssh_backup.sys.stdin.isatty", return_value=False)
    def test_archive_requires_interactive_password_entry(self, tty):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "30na-SSH-Backup.zip"
            archive.write_bytes(b"encrypted fixture")
            with self.assertRaisesRegex(RuntimeError, "interactive terminal"):
                ssh_backup.restore_backup("ssh.example.test", Path(temp) / "identity", archive)
