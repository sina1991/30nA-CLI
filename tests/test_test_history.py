import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from thirtyna import test_history as history
from thirtyna.core import UsageError

LINK = "vless://00000000-0000-4000-8000-000000000001@vpn.example:443?security=tls"


class HistoryTests(unittest.TestCase):
    def record(self, path, run, link, successes, at, speed=10):
        summary = dict(protocol="vless", endpoint="vpn.example:443", label="profile",
                       route="fixture route", status="OK" if successes == 3 else "FAILED",
                       requested_runs=3, successful_runs=successes)
        samples = [dict(status="OK", download_Mbps=speed, ttfb_ms=100) for _ in range(successes)]
        with patch("thirtyna.test_history.time.time", return_value=at):
            history.record(path, run, link, 10000000, summary, samples)

    def test_three_lists_idempotency_and_windows(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "history.sqlite"
            good, bad, pending = LINK, LINK.replace(":443", ":6677"), LINK.replace(":443", ":20200")
            for index in range(3):
                self.record(path, str(index), good, 3, 10000 + index)
                self.record(path, str(index), bad, 0, 10000 + index)
            self.record(path, "0", good, 3, 10000)
            self.record(path, "pending", pending, 3, 10001)
            result = history.catalog(path, 10000000, now=10100)
            self.assertEqual(len(result["lists"]["1"]), 1)
            self.assertEqual(len(result["lists"]["2"]), 1)
            self.assertEqual(len(result["lists"]["3"]), 1)
            self.assertEqual(result["lists"]["1"][0]["metrics"]["runs"], 3)
            self.assertEqual(result["lists"]["3"][0]["metrics"]["failures"], 9)
            expired = history.catalog(path, 10000000, now=10100 + 8 * 86400)
            self.assertEqual(len(expired["lists"]["2"]), 3)
            self.assertTrue(all(row["reason"] == "STALE" for row in expired["lists"]["2"]))
            self.assertNotIn(b"00000000-0000", path.read_bytes())

    def test_payload_sizes_are_separate_and_labels_do_not_reset_identity(self):
        self.assertEqual(history.profile_key(LINK + "#A"), history.profile_key(LINK + "#B"))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "history.sqlite"
            self.record(path, "one", LINK, 3, 10000)
            self.assertEqual(history.catalog(path, 25000000, now=10100)["lists"],
                             {"1": [], "2": [], "3": []})

    def test_recovered_profile_returns_to_recommended(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "history.sqlite"
            for index in range(3):
                self.record(path, "failed-" + str(index), LINK, 0, 10000 + index)
            failed = history.catalog(path, 10000000, now=10100)
            self.assertEqual(len(failed["lists"]["3"]), 1)
            later = 10000 + 25 * 3600
            for index in range(3):
                self.record(path, "recovered-" + str(index), LINK, 3, later + index)
            recovered = history.catalog(path, 10000000, now=later + 100)
            self.assertEqual(len(recovered["lists"]["1"]), 1)
            entry = recovered["lists"]["1"][0]
            self.assertEqual(entry["windows"]["24h"]["success_rate"], 1)
            self.assertEqual(entry["windows"]["7d"]["success_rate"], 0.5)

    def test_policy_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            for policy in ({"good_success": "bad"}, dict(history.DEFAULT_POLICY, failure_margin=2)):
                with self.assertRaises(UsageError):
                    history.catalog(Path(temp) / "history.sqlite", 10000000, policy=policy)

    def test_list_view_and_persistent_policy_without_xray(self):
        import contextlib
        import io
        import json
        from thirtyna.agents import test as agent
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            policy = root / "input-policy.json"
            policy.write_text(json.dumps(dict(history.DEFAULT_POLICY, good_success=0.9)))
            database = root / "state/history.sqlite"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(agent.run(["-lists", "-history", str(database),
                                            "-policy", str(policy)]), 0)
                self.assertEqual(agent.run(["-lists", "-history", str(database)]), 0)
            saved = json.loads((database.parent / "policy.json").read_text())
            self.assertEqual(saved["good_success"], 0.9)
            catalog = json.loads((database.parent / "catalog.json").read_text())
            self.assertEqual(catalog["lists"], {"1": [], "2": [], "3": []})
