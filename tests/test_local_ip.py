import subprocess
import unittest
from unittest.mock import patch

from thirtyna.agents.sysinfo import local_addresses, report


class LocalIPTests(unittest.TestCase):
    @patch("thirtyna.agents.sysinfo.subprocess.run")
    def test_interface_addresses_without_dns_or_host_database(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "192.0.2.55 2001:db8::1 192.0.2.55 127.0.0.1 bad\n", "")
        self.assertEqual(local_addresses(), ["192.0.2.55", "2001:db8::1"])
        self.assertEqual(report("ip"), "192.0.2.55 2001:db8::1")
        self.assertEqual(run.call_args.args[0], ["hostname", "-I"])
        run.return_value.stdout = ""
        self.assertEqual(report("ip"), "none")
        run.side_effect = subprocess.TimeoutExpired("hostname", 3)
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            report("ip")
