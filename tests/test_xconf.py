import ipaddress
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from thirtyna.vless_test import config_for
from thirtyna.xconf import suite


class XconfTests(unittest.TestCase):
    def test_export_existing_does_not_write_panel_and_round_trips(self):
        def inbound_for(port, network, flow, mode):
            name = f"xconf-reality-{port}"
            stream = suite.stream_for(dict(serverNames=["test.example"], shortIds=[""]), name, network, mode)
            return dict(suite.build_payload(name, port, flow, stream), id=port)

        rows = [inbound_for(port, *plan) for port, plan in enumerate(suite.PLANS, 25001)]
        with tempfile.TemporaryDirectory() as directory, patch.object(suite, "Panel") as panel, patch.object(
            suite, "public_key", return_value="fixture-key"
        ):
            output = Path(directory) / "profiles.txt"
            panel.return_value.inbounds.return_value = rows
            panel.return_value.inbound.side_effect = lambda row: row
            suite.export_suite(SimpleNamespace(
                panel="https://test.example", entry=ipaddress.IPv4Address("203.0.113.10"),
                output=output, make=None,
            ))
            panel.return_value.call.assert_not_called()
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            configs = [config_for(link, 1080)[0] for link in output.read_text().splitlines()]
            self.assertEqual(len(configs), 6)
            self.assertEqual(
                [config["outbounds"][0]["streamSettings"]["xhttpSettings"]["mode"]
                 for config in configs[3:]], ["packet-up", "stream-up", "stream-one"]
            )
