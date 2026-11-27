"""Observe local TCP/UDP sockets. Never terminate or reserve foreign sockets."""
from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess

from thirtyna.core import UsageError, parser

SWITCH = "-port"
NAME = "Port Inspection Agent"


@dataclass(frozen=True)
class Endpoint:
    protocol: str
    state: str
    address: str
    port: int
    owner: str
    unit: str

    def line(self):
        return f"{self.protocol} {self.state} {self.address} port={self.port} unit={self.unit} owner={self.owner}"


def service_unit(pid):
    try:
        groups = Path(f"/proc/{pid}/cgroup").read_text().splitlines()
    except OSError:
        return None
    for line in groups:
        for part in reversed(line.split(":", 2)[-1].split("/")):
            if part.endswith(".service") and not any(c.isspace() for c in part):
                return part
    return None


def parse_sockets(output):
    rows = []
    for line in output.splitlines():
        words = line.split(None, 6)
        if len(words) < 6 or words[0] not in ("tcp", "udp"):
            raise RuntimeError("Unrecognized ss socket output")
        address, sep, port = words[4].rpartition(":")
        if not sep or not port.isascii() or not port.isdecimal():
            # Unbound sockets with wildcard port are not assigned ports.
            if sep and port == "*":
                continue
            raise RuntimeError("Unrecognized local socket address")
        number = int(port)
        if not 1 <= number <= 65535:
            continue
        owner = words[6] if len(words) == 7 else "?"
        pids = re.findall(r"\bpid=(\d+)", owner)
        units = sorted({unit for pid in pids if (unit := service_unit(pid))})
        rows.append(Endpoint(words[0], words[1], address, number, owner,
                             ",".join(units) or "?"))
    return sorted(rows, key=lambda r: (r.protocol, r.port, r.address, r.state, r.owner))


def sockets(all_states=False):
    cmd = ["ss", "-H", "-n", "-a" if all_states else "-l", "-t", "-u", "-p"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True,
                                timeout=5, env=dict(os.environ, LC_ALL="C"))
    except FileNotFoundError as exc:
        raise RuntimeError("ss unavailable; install iproute2") from exc
    except subprocess.SubprocessError as exc:
        raise RuntimeError("Could not inspect local TCP/UDP sockets") from exc
    return parse_sockets(result.stdout)


def run(argv):
    cli = parser(SWITCH, "Inspect local TCP/UDP ports and observed owners.",
                 "Examples: 30na -port -list | 30na -port -check 5555")
    mode = cli.add_mutually_exclusive_group(required=True)
    for op in ("list", "all", "summary"):
        mode.add_argument("-" + op, dest="operation", action="store_const", const=op)
    mode.add_argument("-check", type=int, metavar="PORT")
    proto = cli.add_mutually_exclusive_group()
    proto.add_argument("-tcp", dest="protocol", action="store_const", const="tcp")
    proto.add_argument("-udp", dest="protocol", action="store_const", const="udp")
    args = cli.parse_args(argv)
    if args.check is not None and not 1 <= args.check <= 65535:
        raise UsageError("Port must be between 1 and 65535")
    if args.operation == "summary" and args.protocol:
        raise UsageError("Summary reports both protocols")
    rows = sockets(all_states=args.operation == "all" or args.check is not None)
    if args.protocol:
        rows = [row for row in rows if row.protocol == args.protocol]
    if args.check is not None:
        rows = [row for row in rows if row.port == args.check]
        if not rows:
            print("No observed local socket on port", args.check)
            print("Not a bind-availability guarantee.")
            return 0
    if args.operation == "summary":
        for proto in ("tcp", "udp"):
            print(f"{proto} {len({row.port for row in rows if row.protocol == proto})}")
    else:
        for row in rows:
            print(row.line())
    return 0
