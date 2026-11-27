import os
from pathlib import Path
import pty
import subprocess
import sys
import tempfile
import unittest

from thirtyna.core import discover, main

ROOT = Path(__file__).resolve().parents[1]
CLI = str(ROOT / "30na")


class CLITests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.env = dict(os.environ, XDG_DATA_HOME=tmp.name)
        self.addCleanup(subprocess.run, [sys.executable, "-m", "thirtyna.runtime.service", "shutdown"], cwd=ROOT, env=self.env, stdout=subprocess.DEVNULL)

    def invoke(self, *args, data="", code=0):
        result = subprocess.run([CLI, *args], input=data, capture_output=True,
                                text=True, env=self.env, timeout=5)
        self.assertEqual(result.returncode, code, result.stderr)
        if code:
            self.assertTrue(result.stderr)
            self.assertFalse(result.stdout)
        return result.stdout.strip()

    def test_registry(self):
        self.assertEqual(set(discover()), {"-calc", "-sys", "-host", "-menu", "-tunnel"})

    def test_extension(self):
        pkg = self.dir / "sample"
        pkg.mkdir()
        (pkg / "__init__.py").touch()
        (pkg / "extra.py").write_text("SWITCH='-extra'\nNAME='Test'\ndef run(argv): return 17\n")
        sys.path.insert(0, str(self.dir))
        self.addCleanup(sys.path.remove, str(self.dir))
        from unittest.mock import patch
        registry = discover(__import__("sample"))
        with patch("thirtyna.core.discover", return_value=registry):
            self.assertEqual(main(["-extra"]), 17)

    def test_help_and_errors(self):
        for args in [[], ["-calc"], ["-host"], ["-sys"]]:
            self.assertTrue(self.invoke(*args, "-help"))
        for args in [["-unknown"], ["-sys", "-bad"], ["-host", "-add"],
                     ["-calc", "-sub", "2"]]:
            self.invoke(*args, code=2)

    def test_calculator(self):
        for flag, result in [("-add", "12"), ("-sub", "8"), ("-mul", "20"), ("-div", "5")]:
            self.assertEqual(self.invoke("-calc", flag, "10", "2"), result)
        self.assertEqual(self.invoke("-calc", "-add", data="1.2 -0.1"), "1.1")
        for flag, values in [("-div", "1 0"), ("-add", "invalid 4"), ("-add", "")]:
            self.invoke("-calc", flag, data=values, code=2)

    def test_system(self):
        for flag in ["hostname", "os", "kernel", "uptime", "cpu", "ram", "disk"]:
            self.assertTrue(self.invoke("-sys", "-" + flag))
        self.assertEqual(len(self.invoke("-sys", "-hostname", "-kernel").splitlines()), 2)

    def test_host_and_mock_ssh(self):
        mock = self.dir / "ssh"
        mock.write_text('#!/bin/sh\necho "$@" >> "$XDG_DATA_HOME/calls"\nexit "${STATUS:-0}"\n')
        mock.chmod(0o755)
        self.env["PATH"] = str(self.dir) + ":" + self.env["PATH"]
        ip = "192.0.2.5"
        self.invoke("-host", "-add", "-ip", "-ssh", data=ip)
        self.assertEqual(self.invoke("-host", "-list"), ip)
        self.invoke("-host", "-add", "-ip", ip, "-ssh", code=2)
        self.invoke("-host", "-add", "-ip", "bad", "-ssh", code=2)
        calls = self.dir / "calls"
        self.assertEqual(calls.read_text().splitlines(), ["-o BatchMode=yes -- " + ip])
        self.env["STATUS"] = "255"
        self.invoke("-host", "-ssh", "-ip", ip, code=1)
        self.invoke("-host", "-remove", "-ip", ip)
        self.invoke("-host", "-remove", "-ip", ip, code=2)
        self.assertEqual(self.invoke("-host", "-list"), "")


    def test_domain_host_lifecycle_and_ssh(self):
        mock = self.dir / "ssh"
        mock.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$XDG_DATA_HOME/domain_calls"\n')
        mock.chmod(0o755)
        self.env["PATH"] = str(self.dir) + ":" + self.env["PATH"]
        self.invoke("-host", "-add", "-ip", "192.0.2.5")
        self.invoke("-host", "-add", "-domain", "SSH.Example.TEST.")
        self.assertEqual(self.invoke("-host", "-list").splitlines(),
                         ["192.0.2.5", "ssh.example.test"])
        self.invoke("-host", "-add", "-ip", "ssh.example.test", code=2)
        self.invoke("-host", "-ssh", "-domain", data="SSH.EXAMPLE.TEST\n")
        self.assertEqual((self.dir / "domain_calls").read_text().splitlines(),
                         ["-o", "BatchMode=yes", "--", "ssh.example.test"])
        self.invoke("-host", "-ssh", "-domain", "unregistered.example", code=2)
        self.invoke("-host", "-add", "-domain", "root@ssh.example.test", code=2)
        self.invoke("-host", "-add", "-ip", "192.0.2.6", "-domain", "ssh.example.test", code=2)
        self.invoke("-host", "-remove", "-ip", "SSH.EXAMPLE.TEST.")
        self.assertEqual(self.invoke("-host", "-list"), "192.0.2.5")

    def test_storage_failure(self):
        (self.dir / "30na").touch()
        self.invoke("-host", "-list", code=1)

    def test_interactive(self):
        master, slave = pty.openpty()
        try:
            os.write(master, b"2 7\n")
            result = subprocess.run([CLI, "-calc", "-mul"], stdin=slave,
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.stdout.strip(), "14")
            self.assertIn("Two numbers", result.stderr)
        finally:
            os.close(master)
            os.close(slave)

    def test_install_shell_and_reinstall(self):
        prefix = self.dir / "prefix"
        env = dict(self.env, INSTALL_DEPS="0", PREFIX=str(prefix), PATH=str(prefix / "bin") + ":" + self.env["PATH"])
        def shell(command):
            return subprocess.check_output(["bash", "-ec", command], env=env,
                                           cwd=self.dir, text=True).strip()
        subprocess.run([ROOT / "install.sh"], env=env, check=True)
        shell("echo 192.0.2.9 | 30na -host -add -ip")
        (self.dir / "numbers").write_text("4 5")
        self.assertEqual(shell("30na -calc -mul < numbers"), "20")
        subprocess.run([ROOT / "install.sh"], env=env, check=True)
        self.assertEqual(shell("30na -host -list"), "192.0.2.9")
