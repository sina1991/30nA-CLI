import contextlib
import io
import unittest
from unittest.mock import patch

from thirtyna.remote_probe import parse_exec, listening
from thirtyna.tunnel_inventory import render, validate
from thirtyna.agents import tunnel
from thirtyna.core import UsageError


def spec(flag, peer, listen):
    return parse_exec(f"{{ path=/usr/bin/ssh ; argv[]=/usr/bin/ssh -NT -o ExitOnForwardFailure=yes {flag} 0.0.0.0:{listen}:127.0.0.1:443 root@{peer} ; ignore_errors=no ; }}")


def row(flag, peer, listen, unit, ips, pid):
    return dict(spec(flag, peer, listen), unit=unit, recognized=True,
                state="active", peer_ips=set(ips), pid=pid)


def node(machine, ips, units, listeners):
    return dict(machine=machine*64, ips=set(ips), units=units,
                complete=True, listeners=listeners)


class InventoryTests(unittest.TestCase):
    def test_reference_forward_and_reverse_same_port_roles(self):
        for flag, mode in (("-L", "forward"), ("-R", "reverse")):
            result = spec(flag, "example.test", 6677)
            self.assertEqual(result["mode"], mode)
            self.assertEqual(result["local_port"], 6677)
            self.assertEqual(result["remote_port"], 443)
        for command in ("argv[]=/bin/sh -c evil ;", "argv[]=/usr/bin/ssh -L 127.0.0.1:0:127.0.0.1:443 root@example.test ;",
                        "argv[]=/usr/bin/ssh -L 0.0.0.0:1234:127.0.0.1:443 -R 0.0.0.0:6677:127.0.0.1:443 root@example.test ;"):
            self.assertIsNone(parse_exec(command))

    @patch("thirtyna.remote_probe.run")
    def test_listener_owners(self, run):
        run.return_value = 'LISTEN 0 128 0.0.0.0:6677 0.0.0.0:* users:(("sshd",pid=123,fd=4))\nLISTEN 0 128 0.0.0.0:443 0.0.0.0:* users:(("ssh",pid=456,fd=4))\n'
        self.assertEqual(listening(), [
            dict(port=6677, addr="0.0.0.0", owners=[["sshd", 123]]),
            dict(port=443, addr="0.0.0.0", owners=[["ssh", 456]])])

    def test_local_alias_and_reverse_client_id(self):
        a, b = "192.0.2.1", "192.0.2.2"
        local = node("a", [a], [row("-L", "peer.example.test", 443, "ssh-tunnel-1.service", [b], 42)],
                     [dict(port=443, addr="0.0.0.0", owners=[["ssh",42]]),
                      dict(port=6677, addr="0.0.0.0", owners=[["sshd",43]])])
        remote = node("b", [b], [row("-R", "local.example.test", 6677, "nt-123.service", [a], 55)], [])
        nodes = {1: ("LOCAL", local), 2: (b, remote), 3: ("local.example.test", local)}
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(render(nodes), 0)
        text = out.getvalue()
        self.assertIn("forward local_id=1 local_port=443 remote_id=2 remote_port=443 ssh_client_id=1", text)
        self.assertIn("reverse local_id=1 local_port=6677 remote_id=2 remote_port=443 ssh_client_id=2", text)
        self.assertIn("listener=MATCHED_PID", text)
        self.assertIn("listener=SSHD_OBSERVED", text)
        self.assertIn("inventory=LOCAL_ALIAS canonical_id=1", text)
        self.assertEqual(text.count("ownership=external"), 2)

    def test_unreachable_unknown_and_no_ready_claim(self):
        local = node("a", ["192.0.2.1"], [row("-L", "peer.example.test", 443, "ssh-tunnel-1.service", [], 42)], [])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(render({1: ("LOCAL", local), 2: ("peer.example.test", None)}), 1)
        self.assertIn("remote_id=?", out.getvalue())
        self.assertIn("inventory=UNKNOWN", out.getvalue())
        self.assertIn("listener=ABSENT", out.getvalue())
        self.assertNotIn("state=ready", out.getvalue())

    def test_remote_schema_rejects_invalid_unit_and_ports(self):
        obj = dict(machine="a"*64, ips=["192.0.2.1"], complete=True,
                   listeners=[], units=[dict(unit="evil.service", recognized=False)])
        with self.assertRaises(ValueError):
            validate(obj)
        obj["units"] = [dict(unit="nt-abc.service", recognized=True, mode="reverse",
                             bind="0.0.0.0", local_port=70000, remote_port=443,
                             state="active", ssh_peer="peer.example.test", ssh_port=22,
                             pid=1, peer_ips=[])]
        with self.assertRaises(ValueError):
            validate(obj)

    @patch("thirtyna.tunnel_inventory.discover", return_value=0)
    def test_discover_cli_no_mutating_options(self, discover):
        self.assertEqual(tunnel.run(["-discover", "-remote-id", "2"]), 0)
        discover.assert_called_once_with(2)
        for args in (["-discover", "-remote-id", "1"], ["-discover", "-restore"],
                     ["-discover", "-local-port", "443"], ["-discover", "-remote-ip", "192.0.2.1"]):
            with self.assertRaises(UsageError):
                tunnel.run(args)
        discover.assert_called_once()
