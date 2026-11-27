"""Tunnel CLI/runtime integration with a deterministic OpenSSH stand-in.

The fake ssh binds local TCP sockets for both -L and -R; a real remote SSH
server is not exercised by this test suite.
"""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from thirtyna.runtime.service import control

ROOT = Path(__file__).resolve().parents[1]
CLI = str(ROOT / "30na")

MOCK_SSH = '''#!/usr/bin/env python3
import json, os, socket, sys, time
args=sys.argv[1:]
path=args[args.index('-S')+1]
with open(os.environ['XDG_DATA_HOME']+'/ssh_calls', 'a') as out:
    out.write(json.dumps({'args':args, 'pid':os.getpid()})+'\\n')
if '-O' in args:
    flag='-L' if '-L' in args else '-R'
    port=int(args[args.index(flag)+1].split(':')[1])
    with socket.socket(socket.AF_UNIX) as client:
        client.connect(path)
        client.sendall(str(port).encode())
        client.shutdown(socket.SHUT_WR)
        result=client.recv(100)
    if result != b'ok':
        sys.stderr.write('bind: Address already in use\\n')
        sys.exit(255)
    sys.exit(0)
time.sleep(float(os.environ.get('MOCK_AUTH_DELAY', '0')))
if os.environ.get('MOCK_AUTH_FAILURE'):
    sys.stderr.write('Permission denied (publickey).\\n')
    sys.exit(255)
listeners=[]
with socket.socket(socket.AF_UNIX) as control:
    control.bind(path)
    control.listen()
    while True:
        conn,_=control.accept()
        with conn:
            port=int(conn.recv(100))
            time.sleep(float(os.environ.get('MOCK_FORWARD_DELAY', '0')))
            listener=socket.socket()
            try:
                listener.bind(('127.0.0.1',port))
                listener.listen()
                listeners.append(listener)
                conn.sendall(b'ok')
            except OSError:
                listener.close()
                conn.sendall(b'collision')
'''


def unused_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def running(pid):
    try:
        return "State:\tZ" not in (Path("/proc") / str(pid) / "status").read_text()
    except (FileNotFoundError, ProcessLookupError):
        return False


class TunnelTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        mock = self.root / "ssh"
        mock.write_text(MOCK_SSH)
        mock.chmod(0o755)
        self.env = dict(os.environ, XDG_DATA_HOME=tmp.name,
                        PATH=str(self.root) + os.pathsep + os.environ.get("PATH", ""))
        self.addCleanup(self.shutdown)
        self.host = "192.0.2.41"

    def shutdown(self):
        subprocess.run([sys.executable, "-m", "thirtyna.runtime.service", "shutdown"],
                       cwd=ROOT, env=self.env, stdout=subprocess.DEVNULL, timeout=10)

    def cli(self, *args, code=0):
        result = subprocess.run([CLI, *args], cwd=ROOT, env=self.env,
                                capture_output=True, text=True, timeout=12)
        self.assertEqual(result.returncode, code, result.stderr)
        return result

    def register(self):
        self.cli("-host", "-add", "-ip", self.host)

    def start(self, mode="forward", listen=None):
        listen = listen or unused_port()
        output = self.cli("-tunnel", "-" + mode, "-ip", self.host, "-listen", str(listen),
                          "-target", "127.0.0.1", "-target-port", "80").stdout
        token = output.split()[0].split("=")[1]
        self.assertRegex(output, r"state=(starting|ready)")
        return self.wait_state(token, "ready")

    def wait_state(self, token, state, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for item in self.tunnels():
                if item["id"] == token and item["state"] == state:
                    return item
            time.sleep(0.05)
        self.fail(f"{token} did not reach {state}: {self.tunnels()}")

    def tunnels(self):
        from unittest.mock import patch
        with patch.dict(os.environ, self.env):
            agent = control("ensure", "tunnel", bootstrap=True)
            self.assertEqual(agent["state"], "ready")
            from thirtyna.runtime.service import request
            return request(agent, "list")["value"]

    def test_help_and_contract(self):
        self.assertIn("-forward", self.cli("-tunnel", "-help").stdout)
        self.assertIn("-reverse", self.cli("-tunnel", "-help").stdout)
        self.cli("-tunnel", "-forward", code=2)
        self.cli("-tunnel", "-list", "-ip", self.host, code=2)
        self.cli("-tunnel", "-stop", code=2)
        self.cli("-tunnel", "-forward", "-ip", self.host, "-listen", "0",
                 "-target", "127.0.0.1", "-target-port", "80", code=2)

    def test_unregistered_host_rejected(self):
        p = unused_port()
        self.cli("-tunnel", "-forward", "-ip", self.host, "-listen", str(p),
                 "-target", "127.0.0.1", "-target-port", "80", code=2)
        self.assertFalse((self.root / "ssh_calls").exists())

    def test_forward_tunnel_and_stop(self):
        self.register()
        item = self.start()
        self.assertEqual(item["mode"], "forward")
        with socket.create_connection(("127.0.0.1", item["listen"]), timeout=2):
            pass
        calls = [json.loads(line)["args"] for line in (self.root / "ssh_calls").read_text().splitlines()]
        args = next(args for args in calls if "-L" in args)
        self.assertIn("-L", args)
        self.assertIn(self.host, args)
        self.assertIn("ExitOnForwardFailure=yes", args)
        listing = self.cli("-tunnel", "-list").stdout
        self.assertIn(item["id"], listing)
        self.assertIn("state=ready", listing)
        self.cli("-tunnel", "-stop", "-id", item["id"])
        self.assertEqual(self.tunnels(), [])
        self.assertFalse(running(item["pid"]))

    def test_reverse_tunnel(self):
        self.register()
        item = self.start(mode="reverse")
        calls = [json.loads(line)["args"] for line in (self.root / "ssh_calls").read_text().splitlines()]
        args = next(args for args in calls if "-R" in args)
        self.assertIn("-R", args)
        self.assertEqual(item["mode"], "reverse")
        self.assertTrue(running(item["pid"]))

    def test_shared_agents_and_process_isolation(self):
        self.register()
        item = self.start()
        from unittest.mock import patch
        with patch.dict(os.environ, self.env):
            tunnel = control("status", "tunnel")
            host = control("status", "host")
        self.assertEqual(tunnel["service_pid"], host["service_pid"])
        self.assertEqual(tunnel["port_pid"], host["port_pid"])
        self.assertNotEqual(tunnel["pid"], host["pid"])
        self.assertNotEqual(item["pid"], tunnel["pid"])
        self.assertNotIn("key", control_check := self._status_without_key())

    def _status_without_key(self):
        from unittest.mock import patch
        with patch.dict(os.environ, self.env):
            return control("status", "tunnel")

    def test_port_collision(self):
        self.register()
        with socket.socket() as blocker:
            blocker.bind(("127.0.0.1", 0))
            blocker.listen()
            port = blocker.getsockname()[1]
            result = self.cli("-tunnel", "-forward", "-ip", self.host,
                              "-listen", str(port), "-target", "127.0.0.1",
                              "-target-port", "80", code=2)
            self.assertIn("collision", result.stderr)
            self.assertEqual(self.tunnels(), [])
            with socket.create_connection(blocker.getsockname(), timeout=2):
                conn, _ = blocker.accept()
                conn.close()

    def test_worker_recovery_and_cleanup(self):
        self.register()
        first = self.start()
        from unittest.mock import patch
        with patch.dict(os.environ, self.env):
            agent = control("status", "tunnel")
        os.kill(agent["pid"], signal.SIGKILL)
        for _ in range(50):
            if not running(first["pid"]):
                break
            time.sleep(0.1)
        self.assertFalse(running(first["pid"]))
        self.assertEqual(self.cli("-tunnel", "-list").stdout.strip(), "")
        second = self.start()
        self.assertNotEqual(first["pid"], second["pid"])

    def test_invalid_id_and_authentication(self):
        self.register()
        self.start()
        result = self.cli("-tunnel", "-stop", "-id", "missing", code=2)
        self.assertIn("Tunnel not found", result.stderr)
        from unittest.mock import patch
        from thirtyna.runtime.service import request
        with patch.dict(os.environ, self.env):
            agent = control("ensure", "tunnel", bootstrap=True)
            bogus = dict(agent, key="0" * 64)
            with self.assertRaises(RuntimeError):
                request(bogus, "list")

    def test_delayed_authentication_failure(self):
        self.env.update(MOCK_AUTH_DELAY="1.5", MOCK_AUTH_FAILURE="1")
        self.register()
        output = self.cli("-tunnel", "-forward", "-ip", self.host, "-listen", str(unused_port()),
                          "-target", "127.0.0.1", "-target-port", "80").stdout
        self.assertIn("state=starting", output)
        token = output.split()[0].split("=")[1]
        item = self.wait_state(token, "failed")
        self.assertEqual(item["reason"], "authentication_failed")
        self.assertFalse(running(item["pid"]))
        self.assertIn("reason=authentication_failed", self.cli("-tunnel", "-list").stdout)
        self.cli("-tunnel", "-stop", "-id", token)
        self.assertEqual(self.tunnels(), [])

    def test_waits_for_forward_confirmation(self):
        self.env["MOCK_FORWARD_DELAY"] = "1.5"
        self.register()
        output = self.cli("-tunnel", "-reverse", "-ip", self.host, "-listen", str(unused_port()),
                          "-target", "127.0.0.1", "-target-port", "80").stdout
        self.assertIn("state=starting", output)
        self.wait_state(output.split()[0].split("=")[1], "ready")

    def test_late_forwarding_failure(self):
        self.env["MOCK_FORWARD_DELAY"] = "1.5"
        self.register()
        with socket.socket() as blocker:
            blocker.bind(("127.0.0.1", 0))
            blocker.listen()
            output = self.cli("-tunnel", "-reverse", "-ip", self.host, "-listen",
                              str(blocker.getsockname()[1]), "-target", "127.0.0.1",
                              "-target-port", "80").stdout
            self.assertIn("state=starting", output)
            item = self.wait_state(output.split()[0].split("=")[1], "failed")
            self.assertEqual(item["reason"], "port_collision")
            with socket.create_connection(blocker.getsockname(), timeout=2):
                conn, _ = blocker.accept()
                conn.close()

    def test_exit_after_ready(self):
        self.register()
        item = self.start()
        os.kill(item["pid"], signal.SIGKILL)
        failed = self.wait_state(item["id"], "failed")
        self.assertEqual(failed["reason"], "ssh_exited")

    def test_startup_timeout(self):
        self.env["MOCK_AUTH_DELAY"] = "30"
        self.register()
        output = self.cli("-tunnel", "-forward", "-ip", self.host, "-listen", str(unused_port()),
                          "-target", "127.0.0.1", "-target-port", "80").stdout
        self.assertIn("state=starting", output)
        failed = self.wait_state(output.split()[0].split("=")[1], "failed", timeout=15)
        self.assertEqual(failed["reason"], "startup_timeout")
        self.assertFalse(running(failed["pid"]))



if __name__ == "__main__":
    unittest.main()
