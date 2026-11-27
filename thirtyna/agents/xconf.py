"""Create, export and probe panel-managed Xray profiles."""
import ipaddress
from pathlib import Path
import shutil

from thirtyna.core import UsageError, parser
from thirtyna.vless_test import load_profiles
from thirtyna.xconf.probe import egress

SWITCH = "-xconf"
NAME = "Xray Configuration Agent"


def run(argv):
    cli = parser(SWITCH, NAME, "30na -xconf -test -profiles profiles.txt -expect PUBLIC_IP")
    actions = cli.add_mutually_exclusive_group(required=True)
    actions.add_argument("-test", action="store_true")
    actions.add_argument("-get", choices=["config"])
    actions.add_argument("-make", choices=["config"])
    cli.add_argument("-profiles", type=Path)
    cli.add_argument("-xray", type=Path)
    cli.add_argument("-expect", type=ipaddress.ip_address)
    cli.add_argument("-panel")
    cli.add_argument("-entry", type=ipaddress.IPv4Address)
    cli.add_argument("-output", type=Path, default=Path("profiles.txt"))
    args = cli.parse_args(argv)
    if not args.test:
        if args.entry is None or not args.entry.is_global or args.entry.is_multicast:
            raise UsageError("Use -entry PUBLIC_IPV4 for the client address")
        from thirtyna.xconf.suite import export_suite
        export_suite(args)
        return 0

    if args.profiles is None:
        raise UsageError("Use -profiles FILE")
    xray = args.xray or shutil.which("xray") or Path.home() / "vless-bench/bin/xray"
    if not shutil.which(str(xray)) or not shutil.which("curl"):
        raise UsageError("Xray and curl are required")
    profiles = load_profiles(args.profiles)
    passed = 0
    for profile in profiles:
        try:
            address = egress(profile["link"], xray, args.expect)
        except (OSError, RuntimeError) as exc:
            reason = str(exc) if isinstance(exc, RuntimeError) else "Local I/O failed"
            print(f'FAIL profile={profile["id"]} {reason}')
        else:
            passed += 1
            print(f'PASS profile={profile["id"]} egress={address}')
    print(f"PASSED {passed}/{len(profiles)}")
    return int(passed != len(profiles))
