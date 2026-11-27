"""Explicit systemd service operations; separate from 30nA runtime workers."""
import os
import re
import sqlite3
import subprocess
from contextlib import closing

from thirtyna.core import UsageError, parser

SWITCH = "-service"
NAME = "Systemd Service Agent"
UNIT = re.compile(r"[A-Za-z0-9_.:@-]+\.service\Z")
READ = ("list", "active", "installed", "workers", "managed")
OPERATIONS = ("status", "start", "stop", "restart", "reload", "enable", "disable", "logs")


def unit_name(value):
    if not value or len(value) > 255 or value.startswith("-") or not UNIT.fullmatch(value):
        raise UsageError("Use one exact .service unit name (no patterns or options)")
    return value


def managed_units(op=None, unit=None):
    """Remember units successfully started/restarted through this public agent."""
    from thirtyna.runtime.service import folder
    path = folder() / "managed-services.db"
    if op is None and not path.exists():
        return []
    if op is not None:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS managed (unit TEXT PRIMARY KEY)")
            if op in ("start", "restart"):
                db.execute("INSERT OR IGNORE INTO managed VALUES (?)", (unit,))
            elif op == "stop":
                db.execute("DELETE FROM managed WHERE unit=?", (unit,))
            return [row[0] for row in db.execute("SELECT unit FROM managed ORDER BY unit")]
    except sqlite3.Error as exc:
        raise RuntimeError("Managed service history unavailable: " + str(exc)) from exc


def worker_status():
    from thirtyna.runtime.service import control
    for name in ("host", "tunnel"):
        try:
            info = control("status", name, bootstrap=False)
        except (OSError, ValueError, RuntimeError):
            print(name + " unknown")
            if name == "host":
                print("supervisor unknown")
                print("port unknown")
            continue
        state = info.get("state")
        print(name + " " + (state if state in ("ready", "down") else "unknown"))
        if name == "host":
            running = isinstance(info.get("service_pid"), int)
            print("supervisor " + ("running" if running else "down" if state == "down" else "unknown"))
            # This PID is reported by the supervisor, not a separate liveness probe.
            print("port " + ("reported" if isinstance(info.get("port_pid"), int)
                             else "down" if state == "down" and not running else "unknown"))


def run(argv):
    cli = parser(SWITCH, "Manage systemd .service units (system scope).",
                 "Example: 30na -service -status -unit ssh.service")
    group = cli.add_mutually_exclusive_group(required=True)
    for op in (*READ, *OPERATIONS, "daemon-reload"):
        group.add_argument("-" + op, dest="operation", action="store_const", const=op)
    cli.add_argument("-unit", metavar="NAME.service")
    args = cli.parse_args(argv)
    op = args.operation
    if op in OPERATIONS:
        unit = unit_name(args.unit)
    elif args.unit is not None:
        raise UsageError("This operation takes no unit")
    if op == "workers":
        worker_status()
        return 0
    if op == "managed":
        for name in managed_units():
            print(name)
        return 0

    env = dict(os.environ, LC_ALL="C", SYSTEMD_COLORS="0", SYSTEMD_PAGER="cat")
    cmd = ["systemctl", "--no-pager", "--no-ask-password", "--full"]
    if op in ("list", "active"):
        cmd += ["list-units", "--type=service", "--no-legend", "--plain",
                "--all" if op == "list" else "--state=active"]
    elif op == "installed":
        cmd += ["list-unit-files", "--type=service", "--no-legend"]
    elif op == "daemon-reload":
        cmd += ["daemon-reload"]
    elif op == "logs":
        cmd = ["journalctl", "--no-pager", "--lines=50", "--unit=" + unit]
    else:
        cmd += [op, "--", unit]
    try:
        result = subprocess.run(cmd, env=env, stdin=subprocess.DEVNULL, timeout=10)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Systemd command timed out; check actual unit state before retry") from exc
    if result.returncode == 0 and op in ("start", "restart", "stop"):
        try:
            managed_units(op, unit)
        except (OSError, RuntimeError) as exc:
            # The systemd action already happened. Do not claim it failed.
            import sys
            print("30na: operation succeeded; " + str(exc), file=sys.stderr)
    return result.returncode
