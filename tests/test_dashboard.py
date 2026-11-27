"""Dashboard contract, actual CLI delegation and real curses PTY coverage."""
import curses
import fcntl
import os
from pathlib import Path
import pty
import select
import struct
import subprocess
import tempfile
import termios
import time
import unittest
from unittest.mock import patch

from thirtyna.menus.dashboard import CATALOG, Dashboard, Result, Snapshot, invoke

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "30na"


class Screen:
    def __init__(self, height=24, width=100):
        self.height, self.width = height, width
        self.lines = {}

    def getmaxyx(self):
        return self.height, self.width

    def erase(self):
        self.lines.clear()

    def addnstr(self, y, x, value, width, style):
        self.lines[y] = value[:width]

    def refresh(self):
        pass


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.screen = Screen()
        self.hosts = ["192.0.2.1", "ssh.example.test"]
        self.listing = ("abc forward ssh.example.test 5555 127.0.0.1:443 "
                        "pid=10 state=ready\n"
                        "def reverse 192.0.2.1 5556 127.0.0.1:443 "
                        "pid=11 state=failed reason=ssh_exited\n")
        self.ui = Dashboard(self.screen, curses, (1, 2, 3, 4), ROOT, self.runner)

    def runner(self, args, interactive=False):
        self.calls.append((args, interactive))
        if args == ["-host", "-list"]:
            return Result(0, "\n".join(self.hosts) + "\n")
        if args == ["-tunnel", "-list"]:
            return Result(0, self.listing)
        if args[:2] == ["-calc", "-div"]:
            return Result(2, stderr="30na: Division by zero")
        return Result(0, "42\n")

    def keys(self, *keys):
        for key in keys:
            self.assertTrue(self.ui.handle(key))

    def field(self, value):
        self.keys("\n", "\x15", *value, "\n", "\t")

    def test_catalog_covers_public_operations(self):
        self.assertEqual([name for name, _ in CATALOG],
                         ["Calculator", "System", "Host", "Tunnel", "Files", "Help"])
        actions = dict(CATALOG)
        self.assertEqual(len(actions["Calculator"]), 5)
        self.assertEqual(len(actions["System"]), 8)
        self.assertEqual(len(actions["Host"]), 5)
        self.assertEqual(len(actions["Tunnel"]), 4)
        self.assertEqual(len(actions["Help"]), 6)
        self.assertEqual(actions["Calculator"][4].command(["8", "2"]),
                         ["-calc", "-add", "8", "2", "-sub", "8", "2",
                          "-mul", "8", "2", "-div", "8", "2"])
        self.assertEqual(actions["Tunnel"][1].command(
            ["ssh.example.test", "5555", "127.0.0.1", "443", "yes"]),
            ["-tunnel", "-forward", "-domain", "ssh.example.test", "-listen", "5555",
             "-target", "127.0.0.1", "-target-port", "443", "-restore"])
        with self.assertRaises(ValueError):
            actions["Tunnel"][2].command(["", "5555", "127.0.0.1", "443", "no"])
        with self.assertRaises(ValueError):
            actions["Tunnel"][2].command(["ssh.example.test", "5555", "127.0.0.1", "443", "maybe"])

    def test_calculator_form_result_and_back(self):
        self.keys("1", "\n")
        self.field("20")
        self.field("22")
        self.keys("\n")
        self.assertEqual(self.calls, [(["-calc", "-add", "20", "22"], False)])
        self.assertEqual(self.ui.page, "result")
        self.ui.render()
        self.assertIn("OK exit=0", self.screen.lines[21])
        self.assertTrue(any("42" in line for line in self.screen.lines.values()))
        self.keys("\x1b", "\x1b", "\x1b")
        self.assertEqual(self.ui.page, "home")
        self.assertFalse(self.ui.handle("q"))

    def test_required_input_and_error_result(self):
        self.keys("1", "j", "j", "j", "\n", "j", "j", "\n")
        self.assertEqual(self.ui.status, "ERROR input")
        self.assertEqual(self.calls, [])
        self.keys("k", "k")
        self.field("1")
        self.field("0")
        self.keys("\n")
        self.assertEqual(self.ui.status, "ERROR exit=2")
        self.assertIn("30na: Division by zero", self.ui.output)

    def test_snapshot_refresh_and_small_terminal(self):
        self.ui.render()
        self.assertIn("Hosts ?", self.screen.lines[20])
        self.keys("r")
        self.assertEqual(self.ui.snapshot.hosts, 2)
        self.assertEqual(self.ui.snapshot.tunnels, {"ready": 1, "starting": 0, "failed": 1})
        self.ui.render()
        self.assertIn("Tunnels R/S/F 1/0/1", self.screen.lines[20])
        self.screen.width, self.screen.height = 32, 12
        self.ui.render()
        self.assertIn("H 2 | R/S/F 1/0/1", self.screen.lines[8])
        self.assertIn("STATUS | OK", self.screen.lines[9])
        self.assertTrue(all(len(line) <= 31 for line in self.screen.lines.values()))
        self.screen.width, self.screen.height = 18, 5
        self.ui.render()
        self.assertFalse(self.ui.handle("q"))

    def test_host_picker_tunnel_form_and_invalidation(self):
        self.keys("4", "j", "\n", "f")
        self.assertEqual(self.ui.page, "picker")
        self.keys("j", "\n")
        self.assertEqual(self.ui.values[0], "ssh.example.test")
        self.assertEqual(self.ui.snapshot.hosts, 2)
        self.keys("j", "j", "j", "j")
        self.field("yes")
        self.keys("\n")
        self.assertEqual(self.calls[-1][0], ["-tunnel", "-forward", "-domain",
                                             "ssh.example.test", "-listen", "5555",
                                             "-target", "127.0.0.1", "-target-port", "443",
                                             "-restore"])
        self.assertIsNone(self.ui.snapshot.tunnels)

    def test_stop_requires_confirmation_and_picker(self):
        self.keys("4", "k", "\n", "f", "j", "\n", "j", "\n")
        self.assertTrue(self.ui.confirming)
        self.keys("n")
        self.assertEqual(self.calls, [(["-tunnel", "-list"], False)])
        self.keys("\n", "y")
        self.assertEqual(self.calls[-1], (["-tunnel", "-stop", "-id", "def"], False))
        self.assertEqual(self.ui.page, "result")

    def test_snapshot_does_not_invent_counts(self):
        snapshot = Snapshot()
        snapshot.observe(["-host", "-list"], Result(0, "", truncated=True))
        self.assertIsNone(snapshot.hosts)
        snapshot.observe(["-tunnel", "-list"], Result(0, "old output without state\n"))
        self.assertIsNone(snapshot.tunnels)
        snapshot.observe(["-tunnel", "-list"], Result(1, "anything"))
        self.assertIsNone(snapshot.tunnels)
        snapshot.observe(["-tunnel", "-list"], Result(0))
        self.assertEqual(snapshot.tunnels, dict(ready=0, starting=0, failed=0))
        snapshot.invalidate(["-tunnel", "-stop", "-id", "a"])
        self.assertIsNone(snapshot.tunnels)

    def test_output_escapes_terminal_control(self):
        self.ui.set_result(["-help"], Result(0, "safe\x1b[2J\n", "warning\n"))
        self.ui.render()
        self.assertFalse(any("\x1b" in line for line in self.screen.lines.values()))
        self.assertIn("stderr", self.ui.detail)

    def test_real_cli_delegation(self):
        self.assertEqual(invoke(["-calc", "-mul", "6", "7"]).stdout.strip(), "42")
        result = invoke(["-calc", "-div", "1", "0"])
        self.assertEqual(result.code, 2)
        self.assertIn("Division by zero", result.stderr)
        self.assertEqual(invoke(["-sys", "-hostname"]).code, 0)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"XDG_DATA_HOME": tmp}):
            try:
                self.assertEqual(invoke(["-host", "-add", "-domain", "ssh.example.test"]).code, 0)
                self.assertEqual(invoke(["-host", "-list"]).stdout.strip(), "ssh.example.test")
                self.assertEqual(invoke(["-tunnel", "-list"]).code, 0)
            finally:
                from thirtyna.runtime.service import control
                control("shutdown")


class PTYDashboardTests(unittest.TestCase):
    def start(self, *args, width=100):
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, width, 0, 0))
        env = dict(os.environ, TERM="xterm-256color", PYTHONUNBUFFERED="1")
        try:
            proc = subprocess.Popen([str(CLI), "-menu", *args], cwd=ROOT, env=env,
                                    stdin=slave, stdout=slave, stderr=slave)
        finally:
            os.close(slave)
        self.addCleanup(self.stop, proc)
        return master, proc

    @staticmethod
    def stop(proc):
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)

    def read_until(self, master, needle, timeout=8):
        deadline = time.monotonic() + timeout
        data = b""
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.1)
            if ready:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                data += chunk
                if needle in data:
                    return data
        self.fail(f"Missing {needle!r} in PTY output {data[-4000:]!r}")

    def test_real_tui_calculator_keyboard(self):
        master, proc = self.start("-tui")
        self.read_until(master, b"AGENT CONTROL CENTER")
        os.write(master, b"1\r")
        self.read_until(master, b"First number")
        os.write(master, b"\r20\rj\r22\rj\r")
        output = self.read_until(master, b"OK exit=0")
        self.assertIn(b"42", output)
        os.write(master, b"q")
        self.assertEqual(proc.wait(timeout=5), 0)

    def test_direct_file_manager_preserved(self):
        master, proc = self.start("-dir", "/tmp", "-tui", width=40)
        self.read_until(master, b"FILE MANAGER")
        os.write(master, b"q")
        self.assertEqual(proc.wait(timeout=5), 0)
