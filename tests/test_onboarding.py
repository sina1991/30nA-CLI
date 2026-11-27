import contextlib
import hashlib
import io
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from thirtyna import onboarding
from thirtyna.agents import host
from thirtyna.core import UsageError

KEY = Path("/tmp/fixture/.ssh/30na-management/identity")
CONTROLLER = "0" * 64
REMOTE_MACHINE = b"1234567890abcdef1234567890abcdef"


class EnrollmentTests(unittest.TestCase):
    @patch("thirtyna.onboarding.configure_login")
    @patch("thirtyna.onboarding.authenticate")
    @patch("thirtyna.onboarding.import_identity", return_value=KEY)
    @patch("thirtyna.onboarding.subprocess.run")
    def test_enrollment_requires_only_ssh_access(self, run, key, auth, configure):
        onboarding.enroll("ssh.example.test")
        auth.assert_called_once()
        self.assertEqual(auth.call_args.args[:2], ("ssh.example.test", KEY))
        self.assertFalse(auth.call_args.args[-1])
        run.assert_not_called()

    @patch("thirtyna.onboarding.verify_identity_config")
    @patch("thirtyna.onboarding.distinct_probe")
    @patch("thirtyna.onboarding.subprocess.run")
    def test_password_fallback_copies_only_public_key_then_verifies(self, run, probe, config):
        probe.side_effect = [False, True, True]
        run.return_value = subprocess.CompletedProcess([], 0)
        with contextlib.redirect_stderr(io.StringIO()):
            onboarding.authenticate("ssh.example.test", KEY, CONTROLLER, True)
        argv = run.call_args.args[0]
        self.assertEqual(argv[:3], ["ssh-copy-id", "-i", str(KEY.with_suffix(".pub"))])
        self.assertIn("BatchMode=no", argv)
        self.assertIn("StrictHostKeyChecking=yes", argv)
        self.assertIn("PreferredAuthentications=publickey,password,keyboard-interactive", argv)
        self.assertNotIn(str(KEY), argv)
        self.assertEqual(argv[-1], "ssh.example.test")
        self.assertNotIn("input", run.call_args.kwargs)
        self.assertEqual(probe.call_count, 3)
        self.assertTrue(probe.call_args_list[1].kwargs["interactive"])
        self.assertFalse(probe.call_args_list[-1].kwargs)
        config.assert_called_once_with("ssh.example.test", KEY)

    @patch("thirtyna.onboarding.verify_identity_config")
    @patch("thirtyna.onboarding.distinct_probe", return_value=True)
    @patch("thirtyna.onboarding.subprocess.run")
    def test_already_authorized_key_never_changes_remote(self, run, probe, config):
        onboarding.authenticate("ssh.example.test", KEY, CONTROLLER, True)
        run.assert_not_called()

    @patch("thirtyna.onboarding.verify_identity_config")
    @patch("thirtyna.onboarding.distinct_probe")
    @patch("thirtyna.onboarding.subprocess.run")
    def test_failed_reverification_and_no_password_without_consent(self, run, probe, config):
        probe.return_value = False
        with self.assertRaisesRegex(RuntimeError, "SSH key login failed"):
            onboarding.authenticate("ssh.example.test", KEY, CONTROLLER, False)
        run.assert_not_called()
        probe.side_effect = [False, True, False]
        run.return_value = subprocess.CompletedProcess([], 0)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaisesRegex(RuntimeError, "noninteractive login"):
            onboarding.authenticate("ssh.example.test", KEY, CONTROLLER, True)

    @patch("thirtyna.onboarding.subprocess.run")
    def test_self_identity_refused_and_native_interactive_options(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, REMOTE_MACHINE + b"\n", None)
        with self.assertRaisesRegex(RuntimeError, "local machine"):
            onboarding.distinct_probe("ssh.example.test", KEY, hashlib.sha256(REMOTE_MACHINE).hexdigest(), True)
        argv = run.call_args.args[0]
        self.assertIn("StrictHostKeyChecking=ask", argv)
        self.assertIn("BatchMode=no", argv)
        self.assertIsNone(run.call_args.kwargs["stderr"])
        self.assertTrue(onboarding.distinct_probe("ssh.example.test", KEY, CONTROLLER))

    @patch("thirtyna.onboarding.subprocess.run")
    def test_config_must_not_select_other_key(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, f"identityfile {KEY}\n", "")
        onboarding.verify_identity_config("ssh.example.test", KEY)
        run.return_value = subprocess.CompletedProcess([], 0, f"identityfile {KEY}\nidentityfile /tmp/other\n", "")
        with self.assertRaisesRegex(RuntimeError, "another IdentityFile"):
            onboarding.verify_identity_config("ssh.example.test", KEY)

    @patch("thirtyna.onboarding.sys.stdin.isatty", return_value=False)
    @patch("thirtyna.onboarding.subprocess.run")
    def test_interactive_requires_terminal(self, run, tty):
        with self.assertRaisesRegex(RuntimeError, "interactive terminal"):
            onboarding.enroll("ssh.example.test", interactive=True)
        run.assert_not_called()

    @patch("thirtyna.agents.host.request")
    @patch("thirtyna.agents.host.control", return_value={"endpoint_protocol": 1, "domain_support": True})
    @patch("thirtyna.onboarding.enroll")
    def test_register_only_after_success_and_repeat_is_idempotent(self, enroll, control, request):
        request.return_value = {"value": 3}
        args = ["-add", "-domain", "SSH.Example.Test", "-onboard", "-password"]
        enroll.side_effect = RuntimeError("SSH failure")
        with self.assertRaises(RuntimeError):
            host.run(args)
        request.assert_not_called()
        enroll.side_effect = None
        with contextlib.redirect_stdout(io.StringIO()) as out:
            host.run(args)
            host.run(args)
        self.assertEqual(out.getvalue().count("HOST_ID 3 REMOTE ssh.example.test"), 2)
        self.assertEqual(request.call_count, 2)
        enroll.assert_called_with("ssh.example.test", interactive=True, install=True)
        request.assert_called_with(control.return_value, "register", "ssh.example.test")

    @patch("thirtyna.agents.host.control")
    def test_invalid_options_do_not_connect(self, control):
        for args in (["-list", "-onboard"], ["-add", "-ip", "192.0.2.1", "-onboard", "-ssh"],
                     ["-list", "-password"]):
            with self.assertRaises(UsageError):
                host.run(args)
        control.assert_not_called()

class RequiredEnrollmentTests(unittest.TestCase):
    @patch("thirtyna.agents.host.request")
    @patch("thirtyna.agents.host.control", return_value={"endpoint_protocol": 1, "domain_support": True})
    @patch("thirtyna.onboarding.enroll", side_effect=RuntimeError("SSH key login failed"))
    def test_plain_add_requires_authentication(self, enroll, control, request):
        with self.assertRaisesRegex(RuntimeError, "SSH key login failed"):
            host.run(["-add", "-ip", "192.0.2.1"])
        request.assert_not_called()


class OrdinaryLoginTests(unittest.TestCase):
    def test_config_is_parsed_by_openssh_and_repeated_registration_is_stable(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            ssh = Path(temp)
            directory = ssh / "30na-management"
            directory.mkdir()
            key = directory / "identity"
            config = ssh / "config"
            config.write_text("Host existing.example\n    User operator\n")
            original = config.read_text()
            with patch("thirtyna.onboarding.subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess([], 0)
                onboarding.configure_login("new.example", key)
                first = config.read_text()
                onboarding.configure_login("new.example", key)
                self.assertEqual(config.read_text(), first)
            result = subprocess.run(["ssh", "-G", "-F", str(config), "root@new.example"],
                                    capture_output=True, text=True, check=True)
            self.assertIn("identityfile " + str(key), result.stdout)
            self.assertIn("identitiesonly yes", result.stdout)
            self.assertTrue(config.read_text().endswith(original))
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)


class RemoteInstallTests(unittest.TestCase):
    def test_remote_install_script_parses_and_has_upgrade_guard(self):
        subprocess.run(["bash", "-n"], input=onboarding.REMOTE_INSTALL,
                       text=True, check=True)
        self.assertIn("merge-base --is-ancestor", onboarding.REMOTE_INSTALL)
        self.assertIn('test "$(cat "$(dirname "$installed")/.revision")" = "$requested"',
                      onboarding.REMOTE_INSTALL)

    @patch("thirtyna.onboarding.subprocess.run")
    def test_install_failure_propagates(self, run):
        run.return_value = subprocess.CompletedProcess([], 1)
        with self.assertRaisesRegex(RuntimeError, "installation failed"):
            onboarding.install_remote("ssh.example.test", KEY)
        self.assertEqual(run.call_args.args[0][-3:], ["root@ssh.example.test", "bash", "-s"])
