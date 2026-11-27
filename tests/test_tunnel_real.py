"""Opt-in real OpenSSH acceptance: isolated loopback sshd and ephemeral keys.

CI enables THIRTYNA_REAL_SSH=1; local runs skip unless explicitly enabled.
Requires Linux, sshd, ssh-keygen and passwordless sudo for the fixture only.
"""
import getpass
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = str(ROOT / "30na")


def unused_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(os.environ.get("THIRTYNA_REAL_SSH") == "1",
                     "real sshd fixture is explicitly opt-in")
class RealTunnelTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="30na-real-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.env = dict(os.environ, XDG_DATA_HOME=str(self.root),
                        PATH=str(self.root) + os.pathsep + os.environ["PATH"])
        self.user = getpass.getuser()
        if os.getuid() == 0:
            self.fail("Run the real SSH fixture as a non-root user with sudo")
        self.real_ssh = shutil.which("ssh")
        sshd = shutil.which("sshd") or "/usr/sbin/sshd"
        for name in ("host_key", "client_key", "bad_key"):
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "",
                            "-f", str(self.root / name)], check=True)
        port = unused_port()
        (self.root / "authorized_keys").write_text((self.root / "client_key.pub").read_text())
        config = self.root / "sshd_config"
        config.write_text(f"""Port {port}
ListenAddress 127.0.0.1
HostKey {self.root / 'host_key'}
PidFile {self.root / 'sshd.pid'}
AuthorizedKeysFile {self.root / 'authorized_keys'}
StrictModes no
AllowUsers {self.user}
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
UsePAM yes
AllowTcpForwarding yes
GatewayPorts no
X11Forwarding no
AllowAgentForwarding no
PermitTTY no
MaxSessions 0
LogLevel ERROR
""")
        log = (self.root / "sshd.log").open("w+")
        self.addCleanup(log.close)
        daemon = subprocess.Popen(["sudo", "-n", sshd, "-D", "-e", "-f", str(config)],
                                  stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        self.addCleanup(self.stop_daemon, daemon)
        self.addCleanup(self.shutdown)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if daemon.poll() is not None:
                break
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            self.fail("sshd did not listen")
        if daemon.poll() is not None:
            log.seek(0)
            self.fail("isolated sshd exited: " + log.read(1000))
        public = (self.root / "host_key.pub").read_text().split()[:2]
        (self.root / "known_hosts").write_text(f"[127.0.0.1]:{port} {' '.join(public)}\n")
        self.config = self.root / "ssh_config"
        self.config.write_text(f"""Host 127.0.0.1
    User {self.user}
    Port {port}
    IdentityFile {self.root / 'client_key'}
    IdentitiesOnly yes
    IdentityAgent none
    UserKnownHostsFile {self.root / 'known_hosts'}
    GlobalKnownHostsFile /dev/null
    StrictHostKeyChecking yes
""")
        wrapper = self.root / "ssh"
        wrapper.write_text("#!" + sys.executable + "\nimport os, sys\n"
                           + f"real={self.real_ssh!r}\nconfig={str(self.config)!r}\n"
                           + "args=sys.argv[1:]\n"
                           + "os.execv(real,[real]+([] if '-F' in args else ['-F',config])+args)\n")
        wrapper.chmod(0o700)
        self.cli("-host", "-add", "-ip", "127.0.0.1")

    def stop_daemon(self, daemon):
        if daemon.poll() is None:
            daemon.terminate()
            try:
                daemon.wait(timeout=4)
            except subprocess.TimeoutExpired:
                daemon.kill()
                daemon.wait()

    def shutdown(self):
        subprocess.run([sys.executable, "-m", "thirtyna.runtime.service", "shutdown"],
                       cwd=ROOT, env=self.env, stdout=subprocess.DEVNULL, timeout=10, check=True)

    def cli(self, *args, code=0):
        result = subprocess.run([CLI, *args], cwd=ROOT, env=self.env,
                                capture_output=True, text=True, timeout=12)
        if code is not None:
            self.assertEqual(result.returncode, code, result.stderr)
        return result

    def start(self, mode, listen, target, code=0, restore=False):
        return self.cli("-tunnel", "-" + mode, "-ip", "127.0.0.1", "-listen", str(listen),
                        "-target", "127.0.0.1", "-target-port", str(target),
                        *(["-restore"] if restore else []), code=code)

    def wait_state(self, token, state):
        deadline = time.monotonic() + 14
        while time.monotonic() < deadline:
            listing = self.cli("-tunnel", "-list").stdout
            for line in listing.splitlines():
                if line.startswith(token + " "):
                    if "state=" + state in line:
                        return line
                    if "state=failed" in line:
                        self.fail(line)
            time.sleep(0.05)
        self.fail(f"Tunnel {token} did not reach {state}")

    def test_forward_and_reverse_transfer(self):
        for mode in ("forward", "reverse"):
            with self.subTest(mode=mode), socket.socket() as target:
                target.bind(("127.0.0.1", 0))
                target.listen()
                target.settimeout(4)
                listen = unused_port()
                result = self.start(mode, listen, target.getsockname()[1])
                token = result.stdout.split()[0].split("=")[1]
                self.wait_state(token, "ready")
                with socket.create_connection(("127.0.0.1", listen), timeout=4) as client:
                    client.sendall(b"ping")
                    peer, _ = target.accept()
                    with peer:
                        peer.settimeout(4)
                        self.assertEqual(peer.recv(4, socket.MSG_WAITALL), b"ping")
                        peer.sendall(b"pong")
                        self.assertEqual(client.recv(4, socket.MSG_WAITALL), b"pong")
                self.cli("-tunnel", "-stop", "-id", token)
                self.assertEqual(self.cli("-tunnel", "-list").stdout, "")

    def test_authentication_failure(self):
        self.config.write_text(self.config.read_text().replace("client_key", "bad_key"))
        result = self.start("forward", unused_port(), 80, code=None)
        if result.returncode == 0:
            token = result.stdout.split()[0].split("=")[1]
            self.assertIn("reason=authentication_failed", self.wait_state(token, "failed"))
        else:
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("authentication_failed", result.stderr)

    def test_both_port_collisions_preserve_foreign_listener(self):
        for mode in ("forward", "reverse"):
            with self.subTest(mode=mode), socket.socket() as blocker:
                blocker.bind(("127.0.0.1", 0))
                blocker.listen()
                blocker.settimeout(4)
                result = self.start(mode, blocker.getsockname()[1], 80, code=None)
                if result.returncode == 0:
                    token = result.stdout.split()[0].split("=")[1]
                    line = self.wait_state(token, "failed")
                    self.assertRegex(line, r"reason=(port_collision|forwarding_rejected)")
                    self.cli("-tunnel", "-stop", "-id", token)
                else:
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertRegex(result.stderr, r"collision|forwarding rejected")
                with socket.create_connection(blocker.getsockname(), timeout=4):
                    conn, _ = blocker.accept()
                    conn.close()

    def test_opted_in_worker_crash_restores_real_data_transfer(self):
        self.check_real_recovery("forward")

    def test_opted_in_reverse_worker_crash_restores_real_data_transfer(self):
        self.check_real_recovery("reverse")

    def check_real_recovery(self, mode):
        from unittest.mock import patch
        from thirtyna.runtime.service import control
        with socket.socket() as target:
            target.bind(("127.0.0.1", 0))
            target.listen()
            target.settimeout(4)
            listen = unused_port()
            result = self.start(mode, listen, target.getsockname()[1], restore=True)
            token = result.stdout.split()[0].split("=")[1]
            before = self.wait_state(token, "ready")
            old_pid = next(s for s in before.split() if s.startswith("pid="))
            with patch.dict(os.environ, self.env):
                worker = control("status", "tunnel")["pid"]
            os.kill(worker, signal.SIGKILL)
            deadline = time.monotonic() + 14
            while time.monotonic() < deadline:
                listing = self.cli("-tunnel", "-list").stdout
                if token in listing and "state=failed" in listing:
                    self.fail(listing)
                if token in listing and "state=ready" in listing and old_pid not in listing:
                    break
                time.sleep(0.1)
            else:
                self.fail("opted-in real tunnel did not recover")
            with socket.create_connection(("127.0.0.1", listen), timeout=4) as client:
                client.sendall(b"restored")
                peer, _ = target.accept()
                with peer:
                    peer.settimeout(4)
                    self.assertEqual(peer.recv(8, socket.MSG_WAITALL), b"restored")
            self.cli("-tunnel", "-stop", "-id", token)
