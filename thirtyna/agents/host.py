import ipaddress
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from contextlib import closing

from thirtyna.core import UsageError, input_value, parser

SWITCH = "-host"
NAME = "Host Agent"


def run(argv):
    cli = parser(SWITCH, NAME + " manages saved IP addresses and opens SSH.",
                 "Example: echo 192.0.2.1 | 30na -host -add -ip. Supply the IP "
                 "as an argument, on stdin or at the prompt. Add -ssh to connect after saving.")
    group = cli.add_mutually_exclusive_group()
    for flag in ("add", "remove", "list"):
        group.add_argument("-" + flag, action="store_true")
    cli.add_argument("-ip", nargs="?", const="", metavar="ADDRESS")
    cli.add_argument("-ssh", action="store_true")
    args = cli.parse_args(argv)
    if args.list:
        if args.ip is not None or args.ssh:
            raise UsageError("-list takes no other options")
    elif args.ip is None or not (args.add or args.remove or args.ssh) or (args.remove and args.ssh):
        raise UsageError("Use -list, -add -ip, -remove -ip or -ssh -ip")
    else:
        try:
            address = str(ipaddress.ip_address(args.ip or input_value("IP address:")))
        except ValueError as exc:
            raise UsageError("Invalid IP address") from exc
    folder = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "30na"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with closing(sqlite3.connect(folder / "hosts.db")) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS hosts (ip TEXT PRIMARY KEY)")
            if args.list:
                for row in db.execute("SELECT ip FROM hosts ORDER BY ip"):
                    print(row[0])
            elif args.add:
                db.execute("INSERT INTO hosts VALUES (?)", (address,))
            elif args.remove:
                if not db.execute("DELETE FROM hosts WHERE ip=?", (address,)).rowcount:
                    raise UsageError("Host not found")
            elif not db.execute("SELECT 1 FROM hosts WHERE ip=?", (address,)).fetchone():
                raise UsageError("Host not found")
    except sqlite3.IntegrityError as exc:
        raise UsageError("Duplicate host") from exc
    except sqlite3.Error as exc:
        raise RuntimeError(f"Host storage failure: {exc}") from exc
    if args.ssh:
        options = [] if sys.stdin.isatty() else ["-o", "BatchMode=yes"]
        status = subprocess.run(["ssh", *options, "--", address]).returncode
        if status:
            raise RuntimeError(f"SSH exited with status {status}")
