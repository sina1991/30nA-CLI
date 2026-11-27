import contextlib
import io
import socket
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from thirtyna.agents import port
from thirtyna.core import UsageError


class PortTests(unittest.TestCase):
    @patch("thirtyna.agents.port.service_unit", return_value="ssh.service")
    def test_parse_ipv4_ipv6_and_owner(self, unit):
        rows = port.parse_sockets('tcp LISTEN 0 128 127.0.0.1:22 0.0.0.0:* users:(("sshd",pid=17,fd=3))\n'
                                  'tcp LISTEN 0 128 [::]:22 [::]:*\n'
                                  'udp UNCONN 0 0 0.0.0.0:53 0.0.0.0:*\n')
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].unit, "ssh.service")
        self.assertEqual(rows[1].unit, "?")
        self.assertEqual(rows[2].protocol, "udp")

    @patch("thirtyna.agents.port.sockets")
    def test_invalid_and_distinct_summary(self, sockets):
        for args in (["-check", "0"], ["-check", "65536"], ["-summary", "-tcp"], ["-list", "-all"]):
            with self.assertRaises(UsageError):
                port.run(args)
        sockets.assert_not_called()
        sockets.return_value = port.parse_sockets("tcp LISTEN 0 128 127.0.0.1:22 0.0.0.0:*\ntcp LISTEN 0 128 [::]:22 [::]:*\n")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            port.run(["-summary"])
        self.assertEqual(out.getvalue(), "tcp 1\nudp 0\n")

    def test_real_tcp_udp_sockets(self):
        with socket.socket() as tcp, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            tcp.bind(("127.0.0.1", 0))
            tcp.listen()
            udp.bind(("127.0.0.1", 0))
            rows = port.sockets()
            self.assertTrue(any(r.protocol == "tcp" and r.port == tcp.getsockname()[1] for r in rows))
            self.assertTrue(any(r.protocol == "udp" and r.port == udp.getsockname()[1] for r in rows))
            with contextlib.redirect_stdout(io.StringIO()) as out:
                port.run(["-check", str(tcp.getsockname()[1]), "-tcp"])
            self.assertIn("port=" + str(tcp.getsockname()[1]), out.getvalue())

    @patch("thirtyna.agents.port.release")
    def test_force_requires_exact_owner_and_protocol(self, release):
        for args in (["-force", "5555"], ["-force", "5555", "-tcp"],
                     ["-force", "5555", "-pid", "4"],
                     ["-force", "5555", "-tcp", "-pid", "1"],
                     ["-list", "-pid", "4"], ["-force", "0", "-tcp", "-unit", "test.service"]):
            with self.subTest(args=args), self.assertRaises(UsageError):
                port.run(args)
        release.assert_not_called()

    @patch("thirtyna.agents.port.matching")
    @patch("thirtyna.agents.port.guard_pid")
    @patch("thirtyna.agents.port.service_unit", return_value=None)
    def test_unknown_shared_or_wrong_owner_refused(self, unit, guard, matching):
        for owner in ("?", "users:((\"app\",pid=33,fd=4))",
                      "users:((\"app\",pid=42,fd=3),(\"other\",pid=43,fd=4))"):
            matching.return_value = [port.Endpoint("tcp", "LISTEN", "127.0.0.1", 5555, owner, "?")]
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(UsageError):
                port.release(5555, "tcp", pid=42)
        guard.assert_called()

    @patch("thirtyna.agents.port.matching")
    @patch("thirtyna.agents.port.guard_pid")
    @patch("thirtyna.agents.port.ancestors", return_value={1, 2})
    @patch("thirtyna.agents.port.unit_group", return_value="/system.slice/test.service")
    @patch("thirtyna.agents.port.in_group", side_effect=lambda pid, group: pid == 42)
    @patch("thirtyna.agents.systemctl.run", return_value=0)
    def test_verified_unit_release_and_output(self, service, group_member, group, ancestors, guard, matching):
        row = port.Endpoint("tcp", "LISTEN", "127.0.0.1", 5555, "users:((\"app\",pid=42,fd=3))", "test.service")
        matching.side_effect = [[row], [row], []]
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(port.release(5555, "tcp", unit="test.service"), 0)
        service.assert_called_once_with(["-stop", "-unit", "test.service"])
        for expected in ("BEFORE", "unit=test.service", "pid=42", "AFTER", "RELEASED"):
            self.assertIn(expected, out.getvalue())

    @patch("thirtyna.agents.port.matching")
    @patch("thirtyna.agents.systemctl.run")
    def test_protected_unit_never_stopped(self, service, matching):
        matching.return_value = [port.Endpoint("tcp", "LISTEN", "*", 22, "users:((\"sshd\",pid=42,fd=3))", "ssh.service")]
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(UsageError):
            port.release(22, "tcp", unit="ssh.service")
        service.assert_not_called()

    def test_real_pidfd_release_isolated_child(self):
        # Only the fixture child can be signalled. Mock cgroup classification
        # because CI itself runs inside a service; socket and pidfd are real.
        with subprocess.Popen([sys.executable, "-u", "-c",
                               "import socket,time; s=socket.socket(); s.bind(('127.0.0.1',0)); s.listen(); print(s.getsockname()[1],flush=True); time.sleep(30)"],
                              stdout=subprocess.PIPE, text=True) as child:
            try:
                number = int(child.stdout.readline())
                with patch("thirtyna.agents.port.service_unit", return_value=None), contextlib.redirect_stdout(io.StringIO()) as out:
                    self.assertEqual(port.release(number, "tcp", pid=child.pid), 0)
                child.wait(timeout=5)
                self.assertIn("RELEASED", out.getvalue())
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()
