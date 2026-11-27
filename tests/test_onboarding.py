import contextlib
import io
import subprocess
import unittest
from unittest.mock import patch

from thirtyna import onboarding
from thirtyna.agents import host
from thirtyna.core import UsageError

REV = "a" * 40


class EnrollmentTests(unittest.TestCase):
    @patch("thirtyna.onboarding.subprocess.run")
    @patch("thirtyna.onboarding.controller_revision", return_value=REV)
    def test_key_enrollment_pins_revision_and_strict_identity(self, revision, run):
        run.return_value = subprocess.CompletedProcess([], 0, "INSTALLED\nENROLLMENT_OK\n", "")
        with contextlib.redirect_stdout(io.StringIO()):
            onboarding.enroll("ssh.example.test")
        argv = run.call_args.args[0]
        self.assertIn("StrictHostKeyChecking=yes", argv)
        self.assertIn("BatchMode=yes", argv)
        self.assertIn("PreferredAuthentications=publickey", argv)
        self.assertIn("ForwardAgent=no", argv)
        self.assertEqual(argv[-4:], ["--", "ssh.example.test", "python3", "-"])
        script = run.call_args.kwargs["input"]
        compile(script, "<remote>", "exec")
        self.assertIn(REV, script)
        self.assertNotIn("__CONTROLLER__", script)
        self.assertNotIn("systemctl', 'stop", script)
        self.assertIn("INSTALL_DEPS='0'", script)
        self.assertIn("launcher.resolve().parent / '.revision'", script)
        self.assertIn("Endpoint is the local machine", script)

    @patch("thirtyna.onboarding.sys.stdin.isatty", return_value=True)
    @patch("thirtyna.onboarding.subprocess.run")
    @patch("thirtyna.onboarding.controller_revision", return_value=REV)
    def test_interactive_native_ssh_credentials(self, revision, run, tty):
        run.return_value = subprocess.CompletedProcess([], 0, "ENROLLMENT_OK\n", None)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            onboarding.enroll("ssh.example.test", interactive=True)
        argv = run.call_args.args[0]
        self.assertIn("BatchMode=no", argv)
        self.assertIn("PreferredAuthentications=publickey,password,keyboard-interactive", argv)
        self.assertIn("StrictHostKeyChecking=ask", argv)
        self.assertIsNone(run.call_args.kwargs["stderr"])
        self.assertNotIn("sshpass", argv)

    @patch("thirtyna.onboarding.sys.stdin.isatty", return_value=False)
    @patch("thirtyna.onboarding.subprocess.run")
    def test_interactive_requires_terminal(self, run, tty):
        with self.assertRaisesRegex(RuntimeError, "interactive terminal"):
            onboarding.enroll("ssh.example.test", interactive=True)
        run.assert_not_called()

    @patch("thirtyna.onboarding.subprocess.run")
    @patch("thirtyna.onboarding.controller_revision", return_value=REV)
    def test_failed_ssh_or_missing_completion(self, revision, run):
        for code, output in ((255, ""), (0, "INSTALLED\n"), (0, "FAKE_ENROLLMENT_OK\n"), (1, "ENROLLMENT_OK\n")):
            run.return_value = subprocess.CompletedProcess([], code, output, "private diagnostic")
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
                onboarding.enroll("ssh.example.test")

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
        enroll.assert_called_with("ssh.example.test", interactive=True)
        request.assert_called_with(control.return_value, "register", "ssh.example.test")

    @patch("thirtyna.agents.host.control")
    def test_invalid_options_do_not_connect(self, control):
        for args in (["-list", "-onboard"], ["-add", "-ip", "192.0.2.1", "-onboard", "-ssh"],
                     ["-add", "-ip", "192.0.2.1", "-password"]):
            with self.assertRaises(UsageError):
                host.run(args)
        control.assert_not_called()
