import json
import os
from pathlib import Path
import pty
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = str(ROOT / "30na")
MODULE = "thirtyna.runtime.service"


def children(pid):
    # Some Linux containers omit /proc/PID/task/PID/children.
    result = set()
    for entry in Path("/proc").glob("[0-9]*/status"):
        try:
            fields = dict(line.split(":", 1) for line in entry.read_text().splitlines() if ":" in line)
            if int(fields["PPid"]) == pid:
                result.add(int(entry.parent.name))
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass
    return result


def listeners(info):
    fd_dir = Path("/proc") / str(info["pid"]) / "fd"
    inodes = {os.readlink(fd) for fd in fd_dir.iterdir()}
    return [int(row[1].split(":")[1], 16)
            for line in Path("/proc/net/tcp").read_text().splitlines()[1:]
            if (row := line.split())[3] == "0A" and f"socket:[{row[9]}]" in inodes]


class LayerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.env = dict(os.environ, XDG_DATA_HOME=tmp.name)
        self.addCleanup(self.admin, "shutdown")

    def admin(self, action="status"):
        return json.loads(subprocess.check_output(
            [sys.executable, "-m", MODULE, action], cwd=ROOT, env=self.env, timeout=6))

    def run_cli(self, *args, code=0):
        proc = subprocess.Popen([CLI, "-host", *args], env=self.env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out, err = proc.communicate(timeout=6)
        self.assertEqual((proc.returncode, bool(err)), (code, bool(code)), err)
        return proc.pid, out, err

    def ready(self):
        info = self.admin()
        self.assertEqual(info["state"], "ready")
        self.assertEqual(children(info["service_pid"]), {info["port_pid"], info["pid"]})
        self.assertEqual(listeners(info), [info["port"]])
        print(info, flush=True)
        return info

    def test_a_cold(self):
        self.assertEqual(self.admin()["state"], "down")
        _, out, err = self.run_cli(code=2)
        self.assertEqual((out, err), ("", "30na: Use -list, -add -ip, -remove -ip or -ssh -ip\n"))
        self.ready()
        self.admin("shutdown")
        self.env["XDG_DATA_HOME"] += "/other"
        self.assertEqual(self.admin()["state"], "down")
        self.assertEqual(self.run_cli("-list")[1], "")
        self.ready()

    def test_b_process(self):
        for op, args in [("add", ["-add", "-ip", "192.0.2.8"]), ("list", ["-list"])]:
            pid, out, _ = self.run_cli(*args)
            info = self.ready()
            self.assertEqual(info["last"], dict(requester=pid, processor=info["pid"], op=op))
            self.assertNotEqual(pid, info["pid"])
            self.assertEqual(out, "" if op == "add" else "192.0.2.8\n")

    def test_c_parallel(self):
        for valid in (False, True):
            self.assertEqual(self.admin()["state"], "down")
            r, w = os.pipe()
            code = "import os,sys;os.read(int(sys.argv[1]),1);os.execv(sys.argv[2],sys.argv[2:])"
            procs = [subprocess.Popen([sys.executable, "-c", code, str(r), CLI, "-host",
                                      *(["-add", "-ip", ip] if valid else [])], env=self.env,
                                      pass_fds=[r], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                     for ip in ("192.0.2.1", "192.0.2.2")]
            os.close(r)
            os.close(w)
            for proc in procs:
                out, err = proc.communicate(timeout=6)
                self.assertEqual(proc.returncode, 0 if valid else 2, err)
            print("callers", [p.pid for p in procs])
            self.ready()
            if valid:
                self.assertEqual(self.run_cli("-list")[1], "192.0.2.1\n192.0.2.2\n")
            self.admin("shutdown")

    def occupied(self, port):
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.addCleanup(sock.close)
        sock.bind(("127.0.0.1", port))
        sock.listen()
        sock.settimeout(2)
        return sock

    def verify_foreign(self, sock):
        with socket.create_connection(sock.getsockname(), timeout=2) as client:
            conn, _ = sock.accept()
            with conn:
                conn.sendall(str(os.getpid()).encode())
                self.assertEqual(int(client.recv(32)), os.getpid())
        print("foreign", os.getpid(), sock.getsockname())

    def test_d_collision(self):
        sock = self.occupied(0)
        port = sock.getsockname()[1]
        self.env["THIRTYNA_PREFERRED_PORT"] = str(port)
        self.run_cli("-list")
        info = self.ready()
        self.assertEqual(info["collision"], port)
        self.assertNotEqual(info["port"], port)
        self.verify_foreign(sock)

    def test_e_recovery(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.env["THIRTYNA_PREFERRED_PORT"] = str(probe.getsockname()[1])
        self.run_cli("-add", "-ip", "192.0.2.9")
        for crash in (False, True):
            info = self.ready()
            if crash:
                os.kill(info["pid"], signal.SIGKILL)
            else:
                self.admin("stop")
            self.assertEqual(self.admin()["state"], "down")
            with socket.socket() as probe:
                self.assertNotEqual(probe.connect_ex((info["address"], info["port"])), 0)
            sock = self.occupied(info["port"]) if crash else None
            self.assertEqual(self.run_cli("-list")[1], "192.0.2.9\n")
            new = self.ready()
            self.assertNotEqual(info["pid"], new["pid"])
            if sock:
                self.assertEqual(new["collision"], info["port"])
                self.verify_foreign(sock)

    def test_f_legacy_isolation_tty(self):
        folder = self.root / "30na"
        folder.mkdir()
        with sqlite3.connect(folder / "hosts.db") as db:
            db.execute("CREATE TABLE hosts (ip TEXT PRIMARY KEY)")
            db.execute("INSERT INTO hosts VALUES ('192.0.2.4')")
        self.assertEqual(self.run_cli("-list")[1], "192.0.2.4\n")
        mock = self.root / "ssh"
        mock.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        mock.chmod(0o755)
        self.env["PATH"] = str(self.root) + ":" + self.env["PATH"]
        master, slave = pty.openpty()
        try:
            os.write(master, b"192.0.2.4\n")
            proc = subprocess.run([CLI, "-host", "-ssh", "-ip"], stdin=slave, env=self.env,
                                  capture_output=True, text=True, timeout=5)
            self.assertEqual((proc.returncode, proc.stdout, proc.stderr),
                             (0, "--\n192.0.2.4\n", "IP address: "))
        finally:
            os.close(slave)
            os.close(master)
        old = self.env.copy()
        self.addCleanup(setattr, self, "env", old)
        self.env["XDG_DATA_HOME"] += "/other"
        self.addCleanup(self.admin, "shutdown")
        self.assertEqual(self.run_cli("-list")[1], "")
        self.assertEqual(self.run_cli("-ssh", "-ip", "192.0.2.4", code=2)[2], "30na: Host not found\n")
