import contextlib
import io
import json
from pathlib import Path
import shlex
import socket
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from thirtyna import two_vps as engine, reverse_peer
from thirtyna.core import UsageError

TOKEN = "a" * 24
PUBLIC = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKabcdefgh1234567890"
PARAMS = dict(mode="reverse", local="192.0.2.1", local_port=5555,
              remote_port=443, host="192.0.2.2", remote_id=2, restore=False)


class ReverseTests(unittest.TestCase):
    def row(self):
        return dict(PARAMS, id=TOKEN, gateway="192.0.2.1")

    def test_reverse_command_and_scoped_policy(self):
        row = self.row()
        self.assertEqual(engine.reverse_spec(row), "192.0.2.1:5555:127.0.0.1:443")
        definition = engine.service_definition(row)
        args = shlex.split(next(line[10:] for line in definition.splitlines() if line.startswith("ExecStart=")))
        self.assertEqual(args[args.index("-R")+1], engine.reverse_spec(row))
        self.assertEqual(args[-1], "ntr-" + TOKEN + "@192.0.2.1")
        self.assertIn("StrictHostKeyChecking=yes", args)
        self.assertIn("Restart=always", definition)
        policy = engine.policy(row)
        self.assertIn("AllowTcpForwarding remote", policy)
        self.assertIn("PermitListen 192.0.2.1:5555", policy)
        self.assertIn("MaxSessions 0", policy)
        self.assertIn("PermitOpen none", policy)
        self.assertIn("GatewayPorts clientspecified", policy)
        self.assertNotIn("Match User root", policy)

    @patch("thirtyna.two_vps.local_addresses", return_value=["192.0.2.1"])
    def test_gateway_local_identity(self, ips):
        self.assertEqual(engine.gateway_address("127.0.0.1"), "192.0.2.1")
        self.assertEqual(engine.gateway_address("192.0.2.1"), "192.0.2.1")
        with self.assertRaises(UsageError):
            engine.gateway_address("192.0.2.8")
        with self.assertRaises(UsageError):
            engine.gateway_address("::1")
        ips.return_value.append("192.0.2.3")
        with self.assertRaises(UsageError):
            engine.gateway_address("127.0.0.1")

    def test_foreign_listener_preserved(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen()
            row = dict(self.row(), local="127.0.0.1", local_port=sock.getsockname()[1])
            with patch("thirtyna.agents.port.matching", return_value=[]):
                with self.assertRaisesRegex(UsageError, "Local port"):
                    engine.check_free(row)
            with socket.create_connection(sock.getsockname(), timeout=1):
                peer, _ = sock.accept()
                peer.close()

    def orchestrate(self, failure=False, cleanup_failure=False):
        with tempfile.TemporaryDirectory() as temp, contextlib.ExitStack() as stack:
            root = Path(temp)
            row_path = root / "reverse.json"
            rows = {}
            lock = stack.enter_context(patch("thirtyna.two_vps.locked"))
            lock.return_value.__enter__.return_value = (row_path, rows)
            stack.enter_context(patch("thirtyna.two_vps.os.geteuid", return_value=0))
            stack.enter_context(patch("thirtyna.two_vps.secrets.token_hex", return_value=TOKEN))
            stack.enter_context(patch("thirtyna.two_vps.gateway_address", return_value=PARAMS["local"]))
            stack.enter_context(patch("thirtyna.two_vps.local_machine", return_value="0"*64))
            stack.enter_context(patch("thirtyna.two_vps.check_free"))
            stack.enter_context(patch("thirtyna.two_vps.config_path", return_value=root/"config"))
            stack.enter_context(patch("thirtyna.two_vps.keys_path", return_value=root/"keys"))
            stack.enter_context(patch("thirtyna.two_vps.pwd.getpwnam", side_effect=KeyError))
            # Patch only the single host-key read, keep state and resource I/O real.
            read = Path.read_text
            def fake_read(path, *a, **kw):
                if str(path) == "/etc/ssh/ssh_host_ed25519_key.pub":
                    return PUBLIC
                return read(path, *a, **kw)
            stack.enter_context(patch.object(Path, "read_text", fake_read))
            command = stack.enter_context(patch("thirtyna.two_vps.command", return_value=""))
            stack.enter_context(patch("thirtyna.two_vps.ensure_policy_loaded"))
            stack.enter_context(patch("thirtyna.two_vps.validate_policy"))
            stack.enter_context(patch("thirtyna.two_vps.listener", return_value=0 if failure else 321))
            remote = stack.enter_context(patch("thirtyna.two_vps.remote"))
            def execute(row, op, **kwargs):
                if op == "identity":
                    return {"machine":"1"*64, "ips":["192.0.2.2"]}
                if op == "prepare":
                    # Intent must be durable before any remote mutation.
                    self.assertTrue(json.loads(row_path.read_text())[TOKEN]["remote_attempt"])
                    return {"public":PUBLIC}
                if op == "start":
                    self.assertIn("-R 192.0.2.1:5555:127.0.0.1:443", kwargs["definition"])
                    self.assertTrue(kwargs["known_hosts"].startswith("192.0.2.1 ssh-ed25519 "))
                    if failure:
                        raise RuntimeError("fixture failed")
                    return {"active":"active"}
                if op == "stop":
                    if cleanup_failure:
                        raise RuntimeError("peer unavailable")
                    return {"stopped":True}
                raise AssertionError(op)
            remote.side_effect = execute
            if failure:
                with self.assertRaisesRegex(RuntimeError, "cleanup pending" if cleanup_failure else "owned resources removed"):
                    engine.start(PARAMS)
                if cleanup_failure:
                    self.assertEqual(rows[TOKEN]["reason"], "cleanup_pending")
                    self.assertTrue((root/"config").exists())
                else:
                    self.assertEqual(rows, {})
                    self.assertFalse((root/"config").exists())
                    self.assertFalse((root/"keys").exists())
            else:
                item = engine.start(PARAMS)
                self.assertEqual(item["state"], "ready")
                self.assertEqual(item["pid"], 321)
                self.assertEqual(item["engine"], "two-vps")
                self.assertEqual(json.loads(row_path.read_text())[TOKEN]["state"], "ready")
                self.assertEqual([call.args[1] for call in remote.call_args_list], ["identity","prepare","start"])
                self.assertTrue((root/"config").exists())
                # Stop uses the exact record and removes only its resources.
                with patch("thirtyna.two_vps.listener", return_value=0):
                    self.assertTrue(engine.stop(TOKEN))
                self.assertFalse((root/"config").exists())
                self.assertEqual(rows, {})
            self.assertFalse(any("kill" in call.args[0] for call in command.call_args_list))

    def test_create_and_stop(self):
        self.orchestrate()

    def test_failure_rolls_back(self):
        self.orchestrate(failure=True)

    def test_cleanup_failure_preserves_retry_record(self):
        self.orchestrate(failure=True, cleanup_failure=True)

    @patch("thirtyna.two_vps.remote")
    @patch("thirtyna.two_vps.local_machine", return_value="1"*64)
    @patch("thirtyna.two_vps.gateway_address", return_value="192.0.2.1")
    @patch("thirtyna.two_vps.os.geteuid", return_value=0)
    def test_same_machine_refused_before_provision(self, uid, gateway, machine, remote):
        remote.return_value = {"machine":"1"*64,"ips":["192.0.2.1"]}
        with self.assertRaisesRegex(UsageError, "Remote is local"):
            engine.start(PARAMS)
        self.assertEqual(remote.call_count, 1)
        self.assertEqual(remote.call_args.args[1], "identity")

    @patch("thirtyna.reverse_peer.machine", return_value="1"*64)
    @patch("thirtyna.reverse_peer.os.geteuid", return_value=0)
    def test_peer_does_not_mutate_changed_machine(self, uid, machine):
        with self.assertRaisesRegex(RuntimeError, "identity changed"):
            reverse_peer.execute("prepare", {"id":TOKEN,"machine":"2"*64})

    def test_peer_prepare_start_stop_owns_exact_unit(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.ExitStack() as stack:
            root = Path(temp)
            base = root/"keys"
            units = root/"units"
            units.mkdir()
            stack.enter_context(patch("thirtyna.reverse_peer.BASE", base))
            stack.enter_context(patch("thirtyna.reverse_peer.SYSTEMD", units))
            stack.enter_context(patch("thirtyna.reverse_peer.machine", return_value="1"*64))
            stack.enter_context(patch("thirtyna.reverse_peer.os.geteuid", return_value=0))
            # CI runs as nonroot, but the private fixture belongs to that user.
            orig_stat = Path.stat
            def fixture_stat(path, *a, **kw):
                value = orig_stat(path, *a, **kw)
                if path == base:
                    mock = MagicMock()
                    mock.st_uid = 0
                    mock.st_mode = value.st_mode
                    return mock
                return value
            stack.enter_context(patch.object(Path, "stat", fixture_stat))
            runner = stack.enter_context(patch("thirtyna.reverse_peer.run"))
            def run(args, **kwargs):
                if args[0] == "ssh-keygen":
                    Path(args[-1]).write_text("fixture private")
                    Path(args[-1]+".pub").write_text(PUBLIC)
                if args[:2] == ["systemctl","is-active"]:
                    return "active" if not any(c.args[0][:2]==["systemctl","disable"] for c in runner.call_args_list) else "inactive"
                return ""
            runner.side_effect = run
            row = dict(self.row(), machine="1"*64)
            self.assertEqual(reverse_peer.execute("prepare", row)["public"], PUBLIC)
            definition = engine.service_definition(row)
            result = reverse_peer.execute("start", dict(row, definition=definition, known_hosts="fixture"))
            self.assertEqual(result["active"], "active")
            unit = units/engine.unit(row)
            self.assertEqual(unit.read_text(), definition)
            foreign = units/"foreign.service"
            foreign.write_text("preserve")
            self.assertTrue(reverse_peer.execute("stop", row)["stopped"])
            self.assertFalse(unit.exists())
            self.assertFalse((base/TOKEN).exists())
            self.assertEqual(foreign.read_text(), "preserve")


    def test_missing_include_preserves_config_and_independent_tunnels(self):
        with tempfile.TemporaryDirectory() as tmp:
            main = Path(tmp) / "sshd_config"
            original = b"# Include /etc/ssh/sshd_config.d/*.conf\nPasswordAuthentication no\nMatch User legacy\n    PermitTTY no"
            main.write_bytes(original)
            main.chmod(0o640)
            row = self.row()
            second = dict(row, id="b"*24, local_port=1221)
            with patch.object(engine, "SSHD_CONFIG", main), \
                 patch.object(engine, "command"), patch.object(engine, "effective_policy", return_value=["authenticationmethods any"]):
                calls = []
                engine.ensure_policy_loaded(row, "192.0.2.2", lambda: calls.append(row["main_policy_attempt"]))
                engine.ensure_policy_loaded(second, "192.0.2.2", lambda: calls.append(second["main_policy_attempt"]))
                self.assertEqual(calls, [True, True])
                self.assertEqual(main.read_bytes(), original + engine.main_policy_block(row) + engine.main_policy_block(second))
                self.assertEqual(main.stat().st_mode & 0o777, 0o640)
                self.assertNotIn(b"\nInclude /etc/ssh/sshd_config.d/*.conf", main.read_bytes())
                engine.remove_main_policy(row)
                self.assertEqual(main.read_bytes(), original + engine.main_policy_block(second))
                engine.remove_main_policy(second)
                self.assertEqual(main.read_bytes(), original)

    def test_effective_dropin_never_edits_main(self):
        row = self.row()
        with patch.object(engine, "command"), \
             patch.object(engine, "effective_policy", return_value=[f"authorizedkeysfile {engine.keys_path(row)}"]), \
             patch.object(engine, "read_main_config", side_effect=AssertionError("unexpected edit")):
            engine.ensure_policy_loaded(row, "192.0.2.2", lambda: self.fail("unexpected persistence"))
        self.assertNotIn("main_policy_attempt", row)

    def test_changed_managed_block_is_not_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            main = Path(tmp) / "sshd_config"
            row = dict(self.row(), main_policy_attempt=True)
            changed = engine.main_policy_block(row).replace(b"Match all", b"Match User legacy")
            main.write_bytes(changed)
            with patch.object(engine, "SSHD_CONFIG", main):
                with self.assertRaisesRegex(RuntimeError, "changed"):
                    engine.remove_main_policy(row)
            self.assertEqual(main.read_bytes(), changed)
