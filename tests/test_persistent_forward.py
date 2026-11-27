from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch

from thirtyna import persistent_forward as forward


class PersistentForwardTests(unittest.TestCase):
    def test_service_lifecycle(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            systemd = root / "systemd"
            systemd.mkdir()
            params = dict(mode="forward", local="127.0.0.1", local_port=34567,
                          remote_port=9443, remote_id=7, host="ssh.example.test")
            with (patch("thirtyna.two_vps.folder", return_value=root),
                  patch.object(forward, "SYSTEMD", systemd),
                  patch.object(forward.os, "geteuid", return_value=0),
                  patch.object(forward, "existing_identity", return_value=root / "key"),
                  patch.object(forward, "local_machine", return_value="test"),
                  patch.object(forward, "distinct_probe", return_value=True),
                  patch.object(forward, "check_free"),
                  patch.object(forward, "command", return_value="0") as command,
                  patch.object(forward, "wait_for_listener", side_effect=lambda row: row.copy())):
                row = forward.start(params)
                path = systemd / forward.unit(row)
                definition = path.read_text()
                argv = shlex.split(next(line.partition("=")[2] for line in definition.splitlines()
                                        if line.startswith("ExecStart=")))
                self.assertEqual(argv[argv.index("-L") + 1], "127.0.0.1:34567:127.0.0.1:9443")
                self.assertIn("WantedBy=multi-user.target", definition)
                self.assertIn("StrictHostKeyChecking=yes", argv)
                token = row["id"]
                self.assertTrue(forward.operate(token, "stop"))
                self.assertEqual(forward.list_rows()[0]["state"], "stopped")
                self.assertTrue(forward.operate(token, "resume"))
                self.assertTrue(forward.operate(token, "restart"))
                command.assert_any_call(["systemctl", "restart", forward.unit(row)])
                path.write_text("external unit\n")
                with self.assertRaisesRegex(RuntimeError, "ownership changed"):
                    forward.operate(token, "delete")
                self.assertEqual(path.read_text(), "external unit\n")
                path.write_text(definition)
                self.assertTrue(forward.operate(token, "delete"))
                self.assertFalse(path.exists())
                self.assertEqual(forward.list_rows(), [])
