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
        row = self.lines.get(y, "").ljust(self.width-1)
        value = value[:width]
        self.lines[y] = row[:x] + value + row[x+len(value):]

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
        if args == ["-host", "-list", "-ids"]:
            return Result(0, "1 LOCAL testhost 192.0.2.55\n" + "".join(f"{i} REMOTE {host}\n" for i, host in enumerate(self.hosts, 2)))
        if args == ["-host", "-list"]:
            return Result(0, "\n".join(self.hosts) + "\n")
        if args == ["-tunnel", "-list"]:
            return Result(0, self.listing)
        if args == ["-port", "-list"]:
            return Result(0, "tcp LISTEN 127.0.0.1 port=22 unit=ssh.service owner=?\ntcp LISTEN [::] port=22 unit=ssh.service owner=?\nudp UNCONN 0.0.0.0 port=53 unit=? owner=?\n")
        if args == ["-service", "-active"]:
            return Result(0, "ssh.service loaded active running SSH\nother.service loaded active running Other\n")
        if args == ["-service", "-managed"]:
            return Result(0, "ssh.service\n")
        if args == ["-service", "-workers"]:
            return Result(0, "host ready\nsupervisor running\nport reported\ntunnel ready\n")
        if args in (["-service", "-installed"], ["-service", "-list"]):
            return Result(0, "ssh.service enabled\n")
        if args == ["-sys", "-ip"]:
            return Result(0, "192.0.2.55 2001:db8::55\n")
        if args[0] == "-sys":
            return Result(0, "testhost\nUbuntu\n6.8\n100 seconds\nCPU\nRAM\nDisk\n")
        if args[:2] == ["-calc", "-div"]:
            return Result(2, stderr="30na: Division by zero")
        return Result(0, "42\n")

    def keys(self, *keys):
        for key in keys:
            self.assertTrue(self.ui.handle(key))

    def field(self, value):
        self.keys("\n", "\x15", *value, "\n", "\t")

    def test_status_styles_follow_command_state(self):
        class Colors:
            COLOR_PAIRS = 8
            COLOR_BLACK = 0
            COLOR_YELLOW = 3
            COLOR_GREEN = 2
            COLOR_WHITE = 7
            COLOR_RED = 1
            A_BOLD = 256
            error = curses.error

            def __init__(self):
                self.pairs = {}

            def has_colors(self):
                return True

            def init_pair(self, number, fg, bg):
                self.pairs[number] = (fg, bg)

            def color_pair(self, number):
                return number

        colors = Colors()
        self.ui.c = colors
        self.ui.init_status_colors()
        self.assertEqual(colors.pairs, {5: (0, 3), 6: (0, 2), 7: (7, 1)})
        self.assertEqual(self.ui.status_styles["OK"], 6 | 256)
        self.assertEqual(self.ui.status_styles["ERROR"], 7 | 256)

    def test_catalog_covers_public_operations(self):
        self.assertEqual([name for name, _ in CATALOG],
                         ["Calculator", "System", "Host", "Tunnel", "Files", "Help", "Services", "Ports"])
        actions = dict(CATALOG)
        self.assertEqual(len(actions["Calculator"]), 5)
        self.assertEqual(len(actions["System"]), 9)
        self.assertEqual(len(actions["Host"]), 5)
        self.assertEqual(len(actions["Tunnel"]), 4)
        self.assertEqual(len(actions["Help"]), 8)
        self.assertEqual(len(actions["Ports"]), 8)
        self.assertEqual(len(actions["Services"]), 14)
        self.assertEqual(actions["Calculator"][4].command(["8", "2"]),
                         ["-calc", "-add", "8", "2", "-sub", "8", "2",
                          "-mul", "8", "2", "-div", "8", "2"])
        self.assertEqual(actions["Tunnel"][1].command(["1", "8080", "3", "443"]),
                         ["-tunnel", "-forward", "-localhost", "-id", "1", "-local-port", "8080",
                          "-remote-id", "3", "-remote-port", "443"])
        self.assertEqual(actions["Tunnel"][2].command(["192.0.2.55", "8080", "ssh.example.test", "443"]),
                         ["-tunnel", "-reverse", "-ip", "192.0.2.55", "-local-port", "8080",
                          "-remote-ip", "ssh.example.test", "-remote-port", "443"])
        with self.assertRaises(ValueError):
            actions["Tunnel"][2].command(["1", "8080", "", "443"])

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
        self.keys("4", curses.KEY_DOWN, curses.KEY_RIGHT, curses.KEY_DOWN, curses.KEY_DOWN, "f")
        self.assertEqual(self.ui.page, "picker")
        self.keys(curses.KEY_DOWN, curses.KEY_RIGHT)
        self.assertEqual(self.ui.values[2], "3")
        self.assertEqual(self.ui.snapshot.hosts, 2)
        self.keys(curses.KEY_DOWN, curses.KEY_DOWN, curses.KEY_RIGHT)
        self.assertTrue(self.ui.confirming)
        self.keys("y")
        self.assertEqual(self.calls[-1][0], ["-tunnel", "-forward", "-localhost", "-id", "1",
                                             "-local-port", "8080", "-remote-id", "3", "-remote-port", "443"])
        self.assertIsNone(self.ui.snapshot.tunnels)
        self.keys(curses.KEY_LEFT, curses.KEY_LEFT, curses.KEY_LEFT)
        self.assertEqual(self.ui.page, "home")

    def test_stop_requires_confirmation_and_picker(self):
        self.keys("4", "k", "\n", "f", "j", "\n", "j", "\n")
        self.assertTrue(self.ui.confirming)
        self.keys("n")
        self.assertEqual(self.calls, [(["-tunnel", "-list"], False)])
        self.keys("\n", "y")
        self.assertEqual(self.calls[-1], (["-tunnel", "-stop", "-id", "def"], False))
        self.assertEqual(self.ui.page, "result")

    def test_header_context_and_panels(self):
        self.keys("r")
        self.ui.render()
        self.assertIn("SYSTEM / testhost", self.screen.lines[1])
        self.assertIn("IP 192.0.2.55", self.screen.lines[2])
        self.assertIn("CONTEXT HELP / Calculator", self.screen.lines[1])
        self.keys("j", "j", "j")
        self.ui.render()
        self.assertIn("CONTEXT HELP / Tunnel", self.screen.lines[1])
        self.assertTrue(any("OBSERVED STATUS" in line for line in self.screen.lines.values()))
        self.assertIn("supervisor: running", self.ui.side_lines())
        self.assertIn("ssh.service", self.ui.side_lines())
        self.assertNotIn("other.service", self.ui.side_lines())
        self.keys("h")
        self.assertIn("other.service", self.ui.side_lines())
        self.keys("h")
        self.assertNotIn("other.service", self.ui.side_lines())
        self.keys("v")
        self.assertEqual(self.ui.page, "overview")
        self.keys("\x1b")
        self.assertEqual(self.ui.page, "home")

    def test_all_tunnel_fields_have_picker(self):
        self.keys("4", "j", "\n")
        for index, expected in enumerate(("1", "5555", "2", "5555")):
            self.assertEqual(self.ui.index, index)
            self.keys("f")
            self.assertEqual(self.ui.page, "picker")
            self.keys(curses.KEY_RIGHT)
            self.assertEqual(self.ui.values[index], expected)
            self.keys(curses.KEY_DOWN)
        self.keys(curses.KEY_UP, curses.KEY_UP, "f", curses.KEY_UP, curses.KEY_RIGHT)
        self.assertTrue(self.ui.editing)
        self.keys("\x15", *"ssh.example.test", "\n")
        self.assertEqual(self.ui.values[2], "ssh.example.test")

    def test_local_picker_reads_interfaces_without_host_registration(self):
        self.hosts = []
        self.keys("4", "j", "\n", "f")
        self.assertEqual(self.calls, [(["-sys", "-ip"], False)])
        self.assertIn(("192.0.2.55", "1 LOCAL 192.0.2.55"), self.ui.choices)
        self.keys(curses.KEY_DOWN, curses.KEY_RIGHT)
        self.assertEqual(self.ui.values[0], "192.0.2.55")

    def test_color_roles_and_tunnel_states(self):
        self.ui.row_styles = {"local": 10, "remote": 11, "ready": 12, "starting": 13, "failed": 14}
        self.assertEqual(self.ui.line_style("1 LOCAL testhost"), 10)
        self.assertEqual(self.ui.line_style("3 REMOTE ssh.example.test"), 11)
        self.assertEqual(self.ui.line_style("F READY #3 :8080"), 12)
        self.assertEqual(self.ui.line_style("R STARTING #3 :443"), 13)
        self.assertEqual(self.ui.line_style("abc forward ssh.example.test 80 127.0.0.1:443 state=failed"), 14)

    def test_service_picker_and_confirmation(self):
        self.keys("7", "j", "j", "j", "j", "j", "j", "\n", "f", "\n", "j", "\n")
        self.assertTrue(self.ui.confirming)
        self.keys("n")
        self.assertFalse(any(args[:2] == ["-service", "-start"] for args, _ in self.calls))
        self.keys("\n", "y")
        self.assertEqual(self.calls[-1], (["-service", "-start", "-unit", "ssh.service"], False))

    def test_host_key_error_shows_safe_guidance(self):
        self.ui.set_result(["-tunnel", "-reverse"], Result(1, stderr="30na: SSH tunnel failed: host_key_failed"))
        self.assertTrue(any("verify the SSH server fingerprint" in line for line in self.ui.output))
        self.assertTrue(any("Do not disable" in line for line in self.ui.output))

    def test_ports_status_and_picker(self):
        self.keys("r")
        self.assertEqual(self.ui.snapshot.ports, {"tcp": 1, "udp": 1})
        self.ui.render()
        self.assertIn("Ports T/U 1/1", self.screen.lines[20])
        self.assertIn("tcp 22 ssh.service", self.ui.side_lines())
        self.keys("8", "k", "k", "k", "\n", "f", "\n", "j", "\n")
        self.assertEqual(self.calls[-1], (["-port", "-check", "5555"], False))

    def test_emergency_port_action_requires_confirmation(self):
        self.keys("8", "k", "\n")
        self.keys("j", "f", "j", "\n", "j")
        self.field("12345")
        self.keys("\n")
        self.assertTrue(self.ui.confirming)
        self.keys("n")
        self.assertFalse(any(args[:2] == ["-port", "-force"] for args, _ in self.calls))
        self.keys("\n", "y")
        self.assertEqual(self.calls[-1], (["-port", "-force", "5555", "-udp", "-pid", "12345"], False))

    def test_port_snapshot_unknown_on_failure(self):
        snap = Snapshot()
        snap.observe(["-port", "-list"], Result(0, "garbled"))
        self.assertIsNone(snap.ports)
        snap.observe(["-port", "-list"], Result(0, ""))
        self.assertEqual(snap.ports, {"tcp": 0, "udp": 0})
        snap.observe(["-port", "-list"], Result(1, stderr="ss failed"))
        self.assertIsNone(snap.ports)

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
