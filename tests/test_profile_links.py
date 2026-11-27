import base64
import json
import tempfile
from pathlib import Path
import unittest

from thirtyna.vless_test import config_for, load_profiles


class ProtocolTests(unittest.TestCase):
    def test_vmess_websocket(self):
        data = dict(add="vm.example", port="443", id="00000000-0000-4000-8000-000000000001",
                    aid="0", net="ws", tls="tls", host="front.example",
                    path="/ws", sni="tls.example", ps="VMess WS")
        link = "vmess://" + base64.b64encode(json.dumps(data).encode()).decode()
        config, endpoint, label = config_for(link, 12000)
        outbound = config["outbounds"][0]
        self.assertEqual(outbound["protocol"], "vmess")
        self.assertEqual(outbound["settings"]["vnext"][0]["users"][0]["alterId"], 0)
        self.assertEqual(outbound["streamSettings"]["wsSettings"]["path"], "/ws")
        self.assertEqual(outbound["streamSettings"]["tlsSettings"]["serverName"], "tls.example")
        self.assertEqual(label, "VMess WS")

    def test_trojan_grpc_password(self):
        config, _, _ = config_for("trojan://secret%3Avalue@tr.example:443?type=grpc&serviceName=rpc&sni=tls.example", 12000)
        outbound = config["outbounds"][0]
        self.assertEqual(outbound["settings"]["servers"][0]["password"], "secret:value")
        self.assertEqual(outbound["streamSettings"]["security"], "tls")
        self.assertEqual(outbound["streamSettings"]["grpcSettings"]["serviceName"], "rpc")

    def test_shadowsocks_modern_and_legacy(self):
        credentials = "aes-256-gcm:secret:value#end"
        modern = "ss://" + base64.urlsafe_b64encode(credentials.encode()).decode().rstrip("=") + "@ss.example:8388"
        legacy = "ss://" + base64.b64encode((credentials + "@ss.example:8388").encode()).decode()
        for link in (modern, legacy):
            config, endpoint, _ = config_for(link, 12000)
            outbound = config["outbounds"][0]
            self.assertEqual(endpoint, "ss.example:8388")
            self.assertEqual(outbound["protocol"], "shadowsocks")
            self.assertEqual(outbound["settings"]["servers"][0]["password"], "secret:value#end")

    def test_mixed_file_and_unsupported_protocol(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "profiles.txt"
            path.write_text("trojan://p@a.example:443\nss://bad@b.example:8388\nhy2://p@c.example:443\n")
            self.assertEqual(len(load_profiles(path)), 3)
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED_PROTOCOL"):
            config_for("hy2://p@c.example:443", 12000)
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED_SS_PLUGIN"):
            config_for("ss://YWVzLTI1Ni1nY206cA@ss.example:8388?plugin=unknown", 12000)
