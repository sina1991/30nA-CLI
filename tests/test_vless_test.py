import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from thirtyna import vless_test
from thirtyna.agents import test as agent
from thirtyna.core import UsageError

LINK = "vless://00000000-0000-4000-8000-000000000001@vpn.example:443?type=tcp&security=reality&sni=example.com&pbk=fixture&sid=abcd&flow=xtls-rprx-vision#Fixture"


class VlessTests(unittest.TestCase):
    def test_config_conversion(self):
        config, endpoint, label = vless_test.config_for(LINK, 12345)
        outbound = config["outbounds"][0]
        self.assertEqual(endpoint, "vpn.example:443")
        self.assertEqual(label, "Fixture")
        self.assertEqual(outbound["streamSettings"]["realitySettings"]["password"], "fixture")
        self.assertEqual(outbound["settings"]["vnext"][0]["users"][0]["flow"], "xtls-rprx-vision")
        self.assertEqual(config["inbounds"][0]["listen"], "127.0.0.1")
        with self.assertRaises(ValueError):
            vless_test.config_for(LINK.replace("type=tcp", "type=ws"), 12345)

    def test_parser_requires_profiles_and_valid_limits(self):
        for args in (["-count", "0"], ["-timeout", "-1"], ["-bytes", "0"]):
            with self.assertRaises(UsageError):
                agent.run(args)

    def test_cli_real_owned_listener_reports_and_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            xray = root / "xray"
            xray.write_text("#!" + sys.executable + '''
import json, socket, sys, time
if "version" in sys.argv:
    print("Fixture Xray")
    raise SystemExit(0)
config = json.load(open(sys.argv[sys.argv.index("-config")+1]))
if "-test" in sys.argv:
    raise SystemExit(0)
listener = socket.socket()
listener.bind(("127.0.0.1", config["inbounds"][0]["port"]))
listener.listen()
while True:
    time.sleep(1)
''')
            xray.chmod(0o700)
            curl = root / "curl"
            curl.write_text("#!" + sys.executable + '\nprint("200 10000000 0.1 0.5 20000000")\n')
            curl.chmod(0o700)
            profiles = root / "profiles.txt"
            profiles.write_text(LINK + "\n" + LINK.replace(":443?", ":6677?") + "\n")
            (root / "routes.json").write_text(json.dumps({"vpn.example:6677": "i -> Reverse -> UK"}))
            from unittest.mock import patch
            with patch.dict(os.environ, {"PATH": str(root) + os.pathsep + os.environ["PATH"]}):
                with contextlib.redirect_stdout(io.StringIO()):
                    status = agent.run(["-profiles", str(profiles), "-xray", str(xray),
                                        "-ids", "2", "-count", "2", "-interval", "0",
                                        "-output", str(root / "reports"),
                                        "-history", str(root / "history.sqlite")])
            self.assertEqual(status, 0)
            directory = next((root / "reports").iterdir())
            records = json.loads((directory / "summary.json").read_text())
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["profile"], "profile-002")
            self.assertEqual(records[0]["successful_runs"], 2)
            self.assertEqual(records[0]["median_download_Mbps"], 160)
            self.assertEqual(records[0]["route"], "i -> Reverse -> UK")
            report = (directory / "report.md").read_text()
            self.assertIn("\n| Profile", report)
            for path in directory.glob("*"):
                if path.suffix in (".csv", ".json", ".md"):
                    self.assertNotIn("00000000-0000", path.read_text())
                    self.assertNotIn("pbk=", path.read_text())
            self.assertFalse(list(directory.glob(".client-*")))
