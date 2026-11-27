import subprocess
import unittest
from unittest.mock import patch

from thirtyna.agents import systemctl
from thirtyna.core import UsageError


class SystemctlTests(unittest.TestCase):
    @patch("thirtyna.agents.systemctl.subprocess.run")
    def test_unit_commands_no_shell_or_escalation(self, run):
        run.return_value = subprocess.CompletedProcess([], 0)
        for op in systemctl.OPERATIONS:
            self.assertEqual(systemctl.run(["-" + op, "-unit", "ssh.service"]), 0)
            cmd = run.call_args.args[0]
            if op == "logs":
                self.assertEqual(cmd, ["journalctl", "--no-pager", "--lines=50", "--unit=ssh.service"])
            else:
                self.assertEqual(cmd, ["systemctl", "--no-pager", "--no-ask-password", "--full", op, "--", "ssh.service"])
            self.assertNotIn("shell", run.call_args.kwargs)
            self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)

    @patch("thirtyna.agents.systemctl.subprocess.run")
    def test_invalid_input_never_runs_systemctl(self, run):
        for bad in ("ssh", "*.service", "a.service;id", "-bad.service", "a b.service", "ssh.socket"):
            with self.subTest(bad=bad), self.assertRaises(UsageError):
                systemctl.run(["-stop", "-unit", bad])
        for args in (["-start"], ["-list", "-unit", "ssh.service"], ["-start", "-stop"]):
            with self.assertRaises(UsageError):
                systemctl.run(args)
        run.assert_not_called()

    @patch("thirtyna.agents.systemctl.subprocess.run")
    def test_list_active_installed_and_error(self, run):
        run.return_value = subprocess.CompletedProcess([], 1)
        self.assertEqual(systemctl.run(["-active"]), 1)
        self.assertIn("--state=active", run.call_args.args[0])
        systemctl.run(["-installed"])
        self.assertIn("list-unit-files", run.call_args.args[0])
        systemctl.run(["-list"])
        self.assertIn("--all", run.call_args.args[0])
        run.side_effect = subprocess.TimeoutExpired("systemctl", 10)
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            systemctl.run(["-status", "-unit", "ssh.service"])

    @patch("thirtyna.runtime.service.control")
    @patch("builtins.print")
    def test_worker_status_does_not_bootstrap(self, print_mock, control):
        control.side_effect = [{"state": "ready", "service_pid": 12, "port_pid": 13}, {"state": "down"}]
        self.assertEqual(systemctl.run(["-workers"]), 0)
        self.assertEqual([call.args[0] for call in print_mock.call_args_list],
                         ["host ready", "supervisor running", "port reported", "tunnel down"])
        self.assertTrue(all(call.kwargs == {"bootstrap": False} for call in control.call_args_list))
