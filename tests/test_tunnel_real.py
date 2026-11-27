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
        self.config.write_text(f"""Host ssh.example.test
    HostName 127.0.0.1
Host 127.0.0.1 ssh.example.test
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

    def test_domain_name_real_ssh_forwarding(self):
        self.cli("-host", "-add", "-domain", "SSH.EXAMPLE.TEST.")
        with socket.socket() as target:
            target.bind(("127.0.0.1", 0))
            target.listen()
            target.settimeout(4)
            listen = unused_port()
            result = self.cli("-tunnel", "-forward", "-domain", "ssh.example.test",
                              "-listen", str(listen), "-target", "127.0.0.1",
                              "-target-port", str(target.getsockname()[1]))
            token = result.stdout.split()[0].split("=")[1]
            self.assertIn("ssh.example.test", self.wait_state(token, "ready"))
            with socket.create_connection(("127.0.0.1", listen), timeout=4) as client:
                client.sendall(b"domain")
                peer, _ = target.accept()
                with peer:
                    peer.settimeout(4)
                    self.assertEqual(peer.recv(6, socket.MSG_WAITALL), b"domain")
                    peer.sendall(b"ok")
                    self.assertEqual(client.recv(2, socket.MSG_WAITALL), b"ok")
            self.cli("-tunnel", "-stop", "-id", token)

    def test_numbered_endpoint_real_forward_transfer(self):
        with socket.socket() as target:
            local = "127.0.0.2"
            target.bind(("127.0.0.1", 0))
            target.listen()
            target.settimeout(4)
            listen = unused_port()
            result = self.cli("-tunnel", "-forward", "-ip", local, "-local-port", str(listen),
                              "-remote-domain", "ssh.example.test", "-remote-port", str(target.getsockname()[1]))
            token = result.stdout.split()[0].split("=")[1]
            line = self.wait_state(token, "ready")
            self.assertIn("remote_id=", line)
            with socket.create_connection((local, listen), timeout=4) as client:
                client.sendall(b"endpoint")
                peer, _ = target.accept()
                with peer:
                    peer.settimeout(4)
                    self.assertEqual(peer.recv(8, socket.MSG_WAITALL), b"endpoint")
                    peer.sendall(b"ok")
                    self.assertEqual(client.recv(2, socket.MSG_WAITALL), b"ok")
            self.cli("-tunnel", "-stop", "-id", token)

    def test_two_vps_reverse_spec_real_openssh_payload(self):
        # Exercise the production reverse argument against the fixture sshd.
        # This does not execute root provisioning or systemd in CI.
        from thirtyna.two_vps import reverse_spec
        with socket.socket() as target:
            target.bind(("127.0.0.1", 0))
            target.listen()
            target.settimeout(5)
            listen = unused_port()
            spec = reverse_spec(dict(local="127.0.0.1", local_port=listen,
                                     remote_port=target.getsockname()[1]))
            proc = subprocess.Popen([self.real_ssh, "-F", str(self.config), "-NT",
                                     "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
                                     "-R", spec, "127.0.0.1"],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            self.addCleanup(proc.stderr.close)
            self.addCleanup(self.stop_daemon, proc)
            deadline = time.monotonic() + 5
            client = None
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    self.fail(proc.stderr.read().decode(errors="replace"))
                try:
                    client = socket.create_connection(("127.0.0.1", listen), timeout=0.2)
                    break
                except OSError:
                    time.sleep(0.05)
            self.assertIsNotNone(client)
            with client:
                client.settimeout(5)
                client.sendall(b"reverse")
                peer, _ = target.accept()
                with peer:
                    peer.settimeout(5)
                    self.assertEqual(peer.recv(7, socket.MSG_WAITALL), b"reverse")
                    peer.sendall(b"ok")
                    self.assertEqual(client.recv(2, socket.MSG_WAITALL), b"ok")

    def test_reverse_scoped_sshd_policy_parses_with_real_sshd(self):
        from thirtyna.two_vps import policy
        config = self.root / "policy_config"
        original = (self.root / "sshd_config").read_text()
        row = dict(id="a"*24, local="127.0.0.1", local_port=5555)
        config.write_text(original + "\n" + policy(row))
        sshd = shutil.which("sshd") or "/usr/sbin/sshd"
        result = subprocess.run(["sudo", "-n", sshd, "-T", "-f", str(config), "-C",
                                 "user=ntr-" + row["id"] + ",host=peer,addr=127.0.0.1"],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        for setting in ("allowtcpforwarding remote", "gatewayports clientspecified",
                        "maxsessions 0", "permitlisten 127.0.0.1:5555", "permitopen none"):
            self.assertIn(setting, result.stdout.splitlines())

    def test_numbered_forward_uses_imported_management_key_without_identityfile(self):
        # Simulate a freshly enrolled controller: SSH config specifies
        # transport/known_hosts only, and the sole authorized key is managed.
        import shutil
        self.shutdown()
        home = self.root / "fresh_home"
        directory = home / ".ssh" / "30na-management"
        directory.mkdir(parents=True, mode=0o700)
        (home / ".ssh").chmod(0o700)
        key = directory / "identity"
        shutil.copyfile(self.root / "client_key", key)
        shutil.copyfile(self.root / "client_key.pub", key.with_suffix(".pub"))
        key.chmod(0o600)
        key.with_suffix(".pub").chmod(0o600)
        self.config.write_text("\n".join(line for line in self.config.read_text().splitlines()
                                        if not line.strip().startswith("IdentityFile ")) + "\n")
        self.env["HOME"] = str(home)
        self.cli("-host", "-add", "-domain", "ssh.example.test")
        with socket.socket() as target:
            target.bind(("127.0.0.1", 0))
            target.listen()
            target.settimeout(4)
            listen = unused_port()
            result = self.cli("-tunnel", "-forward", "-ip", "127.0.0.1",
                              "-local-port", str(listen), "-remote-domain", "ssh.example.test",
                              "-remote-port", str(target.getsockname()[1]))
            token = result.stdout.split()[0].split("=")[1]
            self.wait_state(token, "ready")
            with socket.create_connection(("127.0.0.1", listen), timeout=4) as client:
                client.sendall(b"managed")
                peer, _ = target.accept()
                with peer:
                    peer.settimeout(4)
                    self.assertEqual(peer.recv(7, socket.MSG_WAITALL), b"managed")
                    peer.sendall(b"ok")
                    self.assertEqual(client.recv(2, socket.MSG_WAITALL), b"ok")
            self.cli("-tunnel", "-stop", "-id", token)


    def test_reverse_missing_include_real_sshd_effective_policy(self):
        from unittest.mock import patch
        from thirtyna import two_vps as engine
        config = self.root / "cloud_sshd_config"
        directory = self.root / "dropins"
        directory.mkdir()
        original = ((self.root / "sshd_config").read_text()
                    + "\n# Include /etc/ssh/sshd_config.d/*.conf\n"
                    + "Match User unrelated\n    PermitTTY no\n").encode()
        config.write_bytes(original)
        row = dict(id="a"*24, local="127.0.0.1", local_port=5555, gateway="127.0.0.1")
        sshd = shutil.which("sshd") or "/usr/sbin/sshd"
        def run(args):
            if args[0] != engine.SSHD:
                self.assertEqual(args, ["systemctl", "reload", "ssh.service"])
                return ""
            result = subprocess.run(["sudo", "-n", sshd, "-f", str(config), *args[1:]],
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout.strip()
        with patch.object(engine, "SSHD_CONFIG", config), patch.object(engine, "CONFIG", directory), \
             patch.object(engine, "command", side_effect=run):
            engine.config_path(row).write_text(engine.policy(row))
            before = run([engine.SSHD, "-T", "-C", "user=root,host=peer,addr=127.0.0.1,laddr=127.0.0.1,lport=22"])
            self.assertIn("authenticationmethods any", engine.effective_policy(row, "127.0.0.1"))
            self.assertNotIn("gatewayports clientspecified", engine.effective_policy(row, "127.0.0.1"))
            engine.ensure_policy_loaded(row, "127.0.0.1", lambda: None)
            self.assertTrue(row["main_policy_attempt"])
            effective = engine.effective_policy(row, "127.0.0.1")
            for setting in ("authenticationmethods publickey", "allowtcpforwarding remote",
                            "gatewayports clientspecified", "maxsessions 0",
                            "permitlisten 127.0.0.1:5555", "permitopen none",
                            f"authorizedkeysfile {engine.keys_path(row)}"):
                self.assertIn(setting, effective)
            run([engine.SSHD, "-t"])
            after = run([engine.SSHD, "-T", "-C", "user=root,host=peer,addr=127.0.0.1,laddr=127.0.0.1,lport=22"])
            self.assertEqual(before, after)
            engine.remove_main_policy(row)
            self.assertEqual(config.read_bytes(), original)
            run([engine.SSHD, "-t"])
