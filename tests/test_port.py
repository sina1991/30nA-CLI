import contextlib
import io
import socket
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
