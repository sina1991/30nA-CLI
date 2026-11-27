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
flag='-L' if '-L' in args else '-R'
spec=args[args.index(flag)+1]
port=int(spec.split(':')[1])
with open(os.environ['XDG_DATA_HOME']+'/ssh_calls', 'a') as out:
    out.write(json.dumps({'args':args, 'pid':os.getpid()})+'\\n')
try:
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',port))
        listener.listen()
        while True: time.sleep(0.1)
except OSError:
    sys.stderr.write('bind: Address already in use\\n')
    sys.exit(255)
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
        self.assertIn("state=starting", output)
        return self.tunnels()[0]

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
        args = json.loads((self.root / "ssh_calls").read_text().splitlines()[0])["args"]
        self.assertIn("-L", args)
        self.assertIn(self.host, args)
        self.assertIn("ExitOnForwardFailure=yes", args)
        self.assertIn(item["id"], self.cli("-tunnel", "-list").stdout)
        self.cli("-tunnel", "-stop", "-id", item["id"])
        self.assertEqual(self.tunnels(), [])
        self.assertFalse(running(item["pid"]))

    def test_reverse_tunnel(self):
        self.register()
        item = self.start(mode="reverse")
        args = json.loads((self.root / "ssh_calls").read_text().splitlines()[0])["args"]
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


if __name__ == "__main__":
    unittest.main()
