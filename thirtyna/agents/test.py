"""Public VLESS profile benchmark entry point."""
import os
from pathlib import Path
import shutil

from thirtyna.core import UsageError, parser
from thirtyna import vless_test

SWITCH = "-test"
NAME = "VLESS Test Agent"


def run(argv):
    home = Path.home()
    cli = parser(SWITCH, "Test VLESS profiles separately through isolated Xray clients.",
                 "30na -test | 30na -test -vless -ids 1,3 -count 5")
    cli.add_argument("-vless", action="store_true", help="VLESS profile benchmark")
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
    return vless_test.execute(args, profiles)
