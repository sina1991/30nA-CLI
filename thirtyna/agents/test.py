"""Public proxy profile benchmark entry point."""
import os
from pathlib import Path
import shutil
import sqlite3

from thirtyna.core import UsageError, parser
from thirtyna import vless_test, test_history

SWITCH = "-test"
NAME = "Proxy Profile Test Agent"


def run(argv):
    try:
        return benchmark(argv)
    except sqlite3.Error as exc:
        raise RuntimeError("Test history database failure; check its path and free disk space") from exc


def benchmark(argv):
    home = Path.home()
    cli = parser(SWITCH, "Test VLESS, VMess, Trojan and Shadowsocks profiles separately through isolated Xray clients.",
                 "30na -test | 30na -test -vless -ids 1,3 -count 5")
    cli.add_argument("-lists", action="store_true", help="Show three rolling history lists")
    cli.add_argument("-list", choices=("1", "2", "3"), help="Test profiles in a history list")
    cli.add_argument("-window", type=float, default=24, help="Classification window in hours")
    cli.add_argument("-min-runs", type=int, default=3, help="Minimum batches before normal classification")
    cli.add_argument("-history", type=Path, default=Path(os.environ.get("XDG_STATE_HOME") or home / ".local/state") / "30na/tests/history.sqlite")
    cli.add_argument("-policy", type=Path, help="JSON classification policy")
    cli.add_argument("-vless", action="store_true", help="Select VLESS profiles")
    cli.add_argument("-protocol", choices=("all", "vless", "vmess", "trojan", "ss"), default="all")
    select = cli.add_mutually_exclusive_group()
    select.add_argument("-all", action="store_true", help="Test every profile (default)")
    select.add_argument("-ids", "-id", metavar="IDS", help="Profile numbers, such as 1,3,7")
    cli.add_argument("-profiles", type=Path, default=home / "vless-bench/profiles.txt")
    cli.add_argument("-xray", type=Path, default=Path(shutil.which("xray") or home / "vless-bench/bin/xray"))
    cli.add_argument("-routes", type=Path, help="JSON map of endpoint host:port to route label")
    cli.add_argument("-count", type=int, default=3)
    cli.add_argument("-bytes", type=int, default=10_000_000, help="Download bytes per attempt")
    cli.add_argument("-timeout", type=float, default=60)
    cli.add_argument("-connect-timeout", type=float, default=10)
    cli.add_argument("-interval", type=float, default=1)
    cli.add_argument("-output", type=Path, default=home / "vless-bench/reports")
    args = cli.parse_args(argv)
    if not 1 <= args.count <= 100 or not 1 <= args.bytes <= 1_000_000_000:
        raise UsageError("Count must be 1..100 and bytes 1..1000000000")
    if not 0 < args.connect_timeout <= args.timeout <= 600 or not 0 <= args.interval <= 60:
        raise UsageError("Require 0 < connect-timeout <= timeout <= 600 and interval 0..60")
    if not 0 < args.window <= 87600 or not 1 <= args.min_runs <= 10000:
        raise UsageError("Window must be >0..87600 hours and min-runs 1..10000")
    args.classification_policy = None
    policy_path = args.policy or args.history.parent / "policy.json"
    if args.policy or policy_path.exists():
        import json
        try:
            args.classification_policy = json.loads(policy_path.read_text())
        except ValueError as exc:
            raise UsageError("Invalid classification policy JSON") from exc
        if not isinstance(args.classification_policy, dict):
            raise UsageError("Classification policy must be an object")
    current = None
    if args.lists or args.list or args.classification_policy is not None:
        current = test_history.catalog(args.history, args.bytes, args.window,
                                       args.min_runs, args.classification_policy)
    if args.policy:
        test_history.save_json(args.classification_policy, args.history.parent / "policy.json")
    if args.lists:
        test_history.display(current, args.history.parent / "catalog.json")
        return 0
    if not args.xray.is_file() or not os.access(args.xray, os.X_OK):
        raise UsageError("Xray executable is missing; use -xray /path/to/xray")
    if shutil.which("curl") is None:
        raise UsageError("curl is required")
    profiles = vless_test.load_profiles(args.profiles)
    if args.ids:
        try:
            ids = list(dict.fromkeys(int(value) for value in args.ids.split(",")))
        except ValueError as exc:
            raise UsageError("Profile IDs must be comma-separated numbers") from exc
        if not ids or min(ids) < 1 or max(ids) > len(profiles):
            raise UsageError("Profile ID outside the input file")
        profiles = [profiles[number - 1] for number in ids]
    if args.vless and args.protocol not in ("all", "vless"):
        raise UsageError("-vless conflicts with -protocol")
    protocol = "vless" if args.vless else args.protocol
    if protocol != "all":
        profiles = [profile for profile in profiles if profile["link"].startswith(protocol + "://")]
    if args.list:
        keys = {entry["key"] for entry in current["lists"][args.list]}
        profiles = [profile for profile in profiles if test_history.profile_key(profile["link"]) in keys]
    if not profiles:
        raise UsageError("No profiles match the selected filters")
    return vless_test.execute(args, profiles)
