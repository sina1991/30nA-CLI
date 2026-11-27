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
CLI = str(ROOT / "tests" / "fixture_cli.py")

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

    def start(self, mode="forward", listen=None, restore=False):
        listen = listen or unused_port()
        output = self.cli("-tunnel", "-" + mode, "-ip", self.host, "-listen", str(listen),
                          "-target", "127.0.0.1", "-target-port", "80",
                          *(["-restore"] if restore else [])).stdout
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
        self.cli("-tunnel", "-list", "-restore", code=2)
        self.cli("-tunnel", "-stop", "-id", "missing", "-restore", code=2)
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


    def worker_pid(self):
        from unittest.mock import patch
        with patch.dict(os.environ, self.env):
            return control("status", "tunnel")["pid"]

    def master_count(self):
        return sum("-M" in json.loads(line)["args"] for line in
                   (self.root / "ssh_calls").read_text().splitlines())

    def test_opt_in_restore_without_cli_trigger(self):
        self.register()
        first = self.start(restore=True)
        self.assertTrue(first["restore"])
        worker = self.worker_pid()
        calls = [json.loads(line)["args"] for line in (self.root / "ssh_calls").read_text().splitlines()]
        master = next(args for args in calls if "-M" in args)
        old_directory = Path(master[master.index("-S") + 1]).parent.parent
        os.kill(worker, signal.SIGKILL)
        deadline = time.monotonic() + 8
        # Observe the mock process log only; no CLI or supervisor request triggers recovery.
        while time.monotonic() < deadline and self.master_count() < 2:
            time.sleep(0.05)
        self.assertEqual(self.master_count(), 2)
        restored = self.wait_state(first["id"], "ready")
        self.assertNotEqual(first["pid"], restored["pid"])
        self.assertNotEqual(worker, self.worker_pid())
        self.assertFalse(running(first["pid"]))
        self.assertFalse(old_directory.exists())
        self.cli("-tunnel", "-stop", "-id", first["id"])

    def test_explicit_stop_discards_restore_intent(self):
        self.register()
        first = self.start(restore=True)
        self.cli("-tunnel", "-stop", "-id", first["id"])
        os.kill(self.worker_pid(), signal.SIGKILL)
        time.sleep(1)
        self.assertEqual(self.master_count(), 1)
        self.assertEqual(self.tunnels(), [])

    def test_worker_stop_discards_all_restore_intents(self):
        self.register()
        self.start(restore=True)
        from unittest.mock import patch
        with patch.dict(os.environ, self.env):
            control("stop", "tunnel")
        self.assertEqual(self.tunnels(), [])
        self.assertEqual(self.master_count(), 1)

    def test_removed_host_blocks_restore(self):
        self.register()
        first = self.start(restore=True)
        self.cli("-host", "-remove", "-ip", self.host)
        os.kill(self.worker_pid(), signal.SIGKILL)
        failed = self.wait_state(first["id"], "failed", timeout=8)
        self.assertEqual(failed["reason"], "host_not_registered")
        self.assertEqual(self.master_count(), 1)

    def test_parallel_starts_no_supervisor_lock_inversion(self):
        self.register()
        first, second = unused_port(), unused_port()
        while second == first:
            second = unused_port()
        procs = [subprocess.Popen([CLI, "-tunnel", "-forward", "-ip", self.host,
                                   "-listen", str(port), "-target", "127.0.0.1",
                                   "-target-port", "80"], cwd=ROOT, env=self.env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for port in (first, second)]
        for proc in procs:
            self.addCleanup(lambda p=proc: p.kill() if p.poll() is None else None)
            out, err = proc.communicate(timeout=10)
            self.assertEqual(proc.returncode, 0, err)
            self.wait_state(out.split()[0].split("=")[1], "ready")
        self.assertEqual(len(self.tunnels()), 2)

    def test_host_worker_replaced_before_new_tunnel(self):
        self.register()
        self.start()
        from unittest.mock import patch
        with patch.dict(os.environ, self.env):
            os.kill(control("status", "host")["pid"], signal.SIGKILL)
        time.sleep(0.2)
        self.start()
        self.assertEqual(len(self.tunnels()), 2)

    def test_opted_in_ssh_disconnect_does_not_retry(self):
        self.register()
        first = self.start(restore=True)
        os.kill(first["pid"], signal.SIGKILL)
        self.wait_state(first["id"], "failed")
        os.kill(self.worker_pid(), signal.SIGKILL)
        time.sleep(1)
        self.assertEqual(self.master_count(), 1)
        self.assertEqual(self.tunnels(), [])

    def test_service_shutdown_discards_restore_intent(self):
        self.register()
        self.start(restore=True)
        self.shutdown()
        self.assertEqual(self.tunnels(), [])
        self.assertEqual(self.master_count(), 1)

    def test_multiple_opted_in_sessions_restore(self):
        self.register()
        first = self.start(restore=True)
        second = self.start(mode="reverse", restore=True)
        os.kill(self.worker_pid(), signal.SIGKILL)
        for before in (first, second):
            after = self.wait_state(before["id"], "ready", timeout=8)
            self.assertNotEqual(before["pid"], after["pid"])
        self.assertEqual(self.master_count(), 4)

    def test_recovery_rate_limit(self):
        self.register()
        first = self.start(restore=True)
        for attempt in range(3):
            old = self.wait_state(first["id"], "ready")
            os.kill(self.worker_pid(), signal.SIGKILL)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline and self.master_count() < attempt + 2:
                time.sleep(0.05)
            self.assertEqual(self.master_count(), attempt + 2)
            new = self.wait_state(first["id"], "ready", timeout=8)
            self.assertNotEqual(old["pid"], new["pid"])
        os.kill(self.worker_pid(), signal.SIGKILL)
        from unittest.mock import patch
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with patch.dict(os.environ, self.env):
                status = control("status", "tunnel")
            if status.get("recovery_warning") == "recovery_rate_limit":
                break
            time.sleep(0.05)
        else:
            self.fail("Recovery rate limit not reached")
        self.assertEqual(status["state"], "down")
        self.assertEqual(self.master_count(), 4)
        result = self.cli("-tunnel", "-list")
        self.assertEqual(result.stdout, "")
        self.assertIn("recovery_rate_limit", result.stderr)

    def test_domain_forward_reverse_and_recovery(self):
        name = "ssh.example.test"
        self.cli("-host", "-add", "-domain", "SSH.Example.TEST.")
        self.cli("-tunnel", "-forward", "-domain", "other.example.test",
                 "-listen", str(unused_port()), "-target", "127.0.0.1",
                 "-target-port", "443", code=2)
        self.assertFalse((self.root / "ssh_calls").exists())
        for mode in ("forward", "reverse"):
            output = self.cli("-tunnel", "-" + mode, "-domain", "SSH.EXAMPLE.TEST.",
                              "-listen", str(unused_port()), "-target", "127.0.0.1",
                              "-target-port", "443", "-restore").stdout
            token = output.split()[0].split("=")[1]
            before = self.wait_state(token, "ready")
            self.assertEqual(before["host"], name)
            os.kill(self.worker_pid(), signal.SIGKILL)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                after = self.wait_state(token, "ready", timeout=5)
                if before["pid"] != after["pid"]:
                    break
                time.sleep(0.05)
            else:
                self.fail("Domain tunnel was not restored")
            self.assertEqual(after["host"], name)
            self.cli("-tunnel", "-stop", "-id", token)
        calls = [json.loads(line)["args"] for line in
                 (self.root / "ssh_calls").read_text().splitlines()]
        self.assertTrue(all(args[-1] == name for args in calls))
        self.cli("-tunnel", "-forward", "-domain", name, "-listen",
                 str(unused_port()), "-target", "bad.example.test",
                 "-target-port", "443", code=2)


    def test_stable_host_ids_migration_and_endpoint_validation(self):
        import sqlite3
        folder = self.root / "30na"
        folder.mkdir()
        with sqlite3.connect(folder / "hosts.db") as db:
            db.execute("CREATE TABLE hosts(ip TEXT PRIMARY KEY)")
            db.executemany("INSERT INTO hosts VALUES (?)", [("192.0.2.5",), ("ssh.example.test",)])
        listing = self.cli("-host", "-list", "-ids").stdout.splitlines()
        self.assertTrue(listing[0].startswith("1 LOCAL "))
        self.assertEqual(listing[1:], ["2 REMOTE 192.0.2.5", "3 REMOTE ssh.example.test"])
        self.cli("-host", "-remove", "-ip", "192.0.2.5")
        self.cli("-host", "-add", "-ip", "192.0.2.1")
        listing = self.cli("-host", "-list", "-ids").stdout.splitlines()
        self.assertEqual(listing[1:], ["3 REMOTE ssh.example.test", "4 REMOTE 192.0.2.1"])
        self.shutdown()
        self.assertEqual(self.cli("-host", "-list", "-ids").stdout.splitlines()[1:], listing[1:])
        self.cli("-tunnel", "-forward", "-localhost", "-id", "2", "-local-port", "8080",
                 "-remote-id", "3", "-remote-port", "443", code=2)
        self.cli("-tunnel", "-forward", "-local-port", "8080", "-remote-id", "2",
                 "-remote-port", "443", code=2)
        self.assertFalse((self.root / "ssh_calls").exists())

    def test_modern_reverse_dispatches_to_remote_engine_not_worker(self):
        import contextlib
        import io
        from unittest.mock import patch
        from thirtyna.agents import tunnel
        self.register()
        with patch.dict(os.environ, self.env), patch("thirtyna.two_vps.start") as start:
            start.side_effect = lambda p: dict(p, id="a"*24, pid=123, state="ready")
            with contextlib.redirect_stdout(io.StringIO()) as output:
                tunnel.run(["-reverse", "-localhost", "-id", "1", "-local-port", "5555",
                            "-remote-id", "2", "-remote-port", "443"])
            params = start.call_args.args[0]
            self.assertEqual(params["local_port"], 5555)
            self.assertEqual(params["remote_port"], 443)
            self.assertEqual(params["host"], self.host)
            self.assertIn("ssh_client=remote", output.getvalue())
        self.assertFalse((self.root / "ssh_calls").exists())

    def test_modern_direct_alias_and_clean_listing(self):
        self.register()
        listen = unused_port()
        result = self.cli("-tunnel", "-forward", "-ip", "127.0.0.1", "-listen", str(listen),
                          "-remote-ip/domain", self.host, "-remote-port", "443")
        token = result.stdout.split()[0].split("=")[1]
        self.wait_state(token, "ready")
        line = self.cli("-tunnel", "-list").stdout
        self.assertIn("local_id=1 local=127.0.0.1:" + str(listen), line)
        self.assertIn("remote_id=2 remote=" + self.host + ":443", line)
        self.assertNotIn("target=", line)
        help_text = self.cli("-tunnel", "-help").stdout
        self.assertNotIn("-target-port", help_text)
        self.cli("-tunnel", "-stop", "-id", token)


if __name__ == "__main__":
    unittest.main()
