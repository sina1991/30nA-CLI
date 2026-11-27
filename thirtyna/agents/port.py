"""Inspect sockets; emergency release requires an explicitly identified owner."""
from dataclasses import dataclass
import os
from pathlib import Path
import re
import signal
import subprocess
import time

from thirtyna.core import UsageError, parser

SWITCH = "-port"
NAME = "Port Management Agent"


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


def owner_pids(row):
    return {int(pid) for pid in re.findall(r"\bpid=(\d+)", row.owner)}


def matching(port, protocol):
    return [row for row in sockets() if row.port == port and row.protocol == protocol]


def describe(rows, phase):
    print(phase, flush=True)
    for row in rows:
        print(row.line(), flush=True)
    if not rows:
        print("No observed listener/bound socket", flush=True)


def ancestors():
    result = {1}
    pid = os.getpid()
    while pid > 1 and pid not in result:
        result.add(pid)
        try:
            status = Path(f"/proc/{pid}/status").read_text()
            pid = int(next(line.split()[1] for line in status.splitlines()
                           if line.startswith("PPid:")))
        except (OSError, ValueError, StopIteration, IndexError) as exc:
            raise RuntimeError("Cannot verify process ancestry; refusing release") from exc
    return result


def guard_pid(pid):
    if pid in ancestors():
        raise UsageError("Refusing PID 1, current process or its ancestors")
    try:
        name = Path(f"/proc/{pid}/comm").read_text().strip()
        command = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError as exc:
        raise RuntimeError("Owner identity unavailable; refusing release") from exc
    if (name in {"sshd", "ssh", "systemd", "systemd-logind", "dbus-daemon", "dbus-broker"}
            or b"thirtyna.runtime" in command or b"/30na\x00" in command
            or b"30na\x00" in command):
        raise UsageError("Protected SSH/system/30nA process; use its own management interface")


def unit_group(unit):
    result = subprocess.run(["systemctl", "--no-pager", "--no-ask-password",
                             "show", "--property=ControlGroup", "--value", "--", unit],
                            capture_output=True, text=True, check=True, timeout=4)
    group = result.stdout.strip()
    if not group.startswith("/system.slice/") or group.rsplit("/", 1)[-1] != unit:
        raise UsageError("Cannot verify exact system-scope service cgroup")
    return group


def in_group(pid, group):
    try:
        rows = Path(f"/proc/{pid}/cgroup").read_text().splitlines()
    except OSError:
        return False
    return any(path == group or path.startswith(group + "/")
               for path in (line.split(":", 2)[-1] for line in rows))


def verify_owner(rows, pid=None, group=None):
    pids = set()
    for row in rows:
        owners = owner_pids(row)
        if not owners:
            raise UsageError("Unknown socket owner; refusing release")
        pids.update(owners)
    for owner in pids:
        guard_pid(owner)
    if pid is not None:
        if pids != {pid}:
            raise UsageError("Port is shared or PID does not match; refusing release")
        if service_unit(pid):
            raise UsageError("Service-managed PID; use the exact -unit instead")
    elif not all(in_group(owner, group) for owner in pids):
        raise UsageError("Socket owner does not belong to the selected unit")
    return pids


def release(port, protocol, unit=None, pid=None):
    rows = matching(port, protocol)
    describe(rows, "BEFORE")
    if not rows:
        print("ALREADY_CLEAR (observed only)")
        return 0
    if unit is not None:
        from thirtyna.agents.systemctl import run as service_run, unit_name
        unit = unit_name(unit)
        if unit.startswith(("ssh.", "sshd.", "ssh@", "sshd@", "systemd-", "dbus.", "dbus-", "user@")):
            raise UsageError("Protected system/SSH unit; refusing release")
        try:
            group = unit_group(unit)
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError("Cannot verify service ownership") from exc
        verify_owner(rows, group=group)
        current = matching(port, protocol)
        if current != rows or not current:
            raise RuntimeError("Socket ownership changed; inspect again")
        verify_owner(current, group=group)
        print("ACTION stop unit=" + unit + " (may affect other ports)", flush=True)
        code = service_run(["-stop", "-unit", unit])
        if code:
            describe(matching(port, protocol), "AFTER")
            raise RuntimeError("Service stop failed; check unit status")
    else:
        if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
            raise RuntimeError("PID-safe release requires Linux pidfd support")
        # Open a stable process reference before the final ownership observation.
        verify_owner(rows, pid=pid)
        with_pid = os.pidfd_open(pid)
        try:
            current = matching(port, protocol)
            if current != rows or not current:
                raise RuntimeError("Socket ownership changed; inspect again")
            verify_owner(current, pid=pid)
            print(f"ACTION SIGTERM pid={pid}", flush=True)
            signal.pidfd_send_signal(with_pid, signal.SIGTERM)
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                current = matching(port, protocol)
                if not current:
                    break
                if set().union(*(owner_pids(row) for row in current)) != {pid}:
                    break
                time.sleep(0.1)
            else:
                current = matching(port, protocol)
                if current:
                    verify_owner(current, pid=pid)
                    print(f"ACTION SIGKILL pid={pid}", flush=True)
                    signal.pidfd_send_signal(with_pid, signal.SIGKILL)
        finally:
            os.close(with_pid)
    deadline = time.monotonic() + 1.0
    while True:
        rows = matching(port, protocol)
        if not rows or time.monotonic() >= deadline:
            break
        time.sleep(0.1)
    describe(rows, "AFTER")
    if rows:
        print("STILL_IN_USE; no further automatic action")
        return 1
    print("RELEASED (no observed listener/bound socket; not a bind guarantee)")
    return 0


def run(argv):
    cli = parser(SWITCH, "Inspect local TCP/UDP ports and observed owners.",
                 "Examples: 30na -port -list | 30na -port -check 5555")
    mode = cli.add_mutually_exclusive_group(required=True)
    for op in ("list", "all", "summary"):
        mode.add_argument("-" + op, dest="operation", action="store_const", const=op)
    mode.add_argument("-check", type=int, metavar="PORT")
    mode.add_argument("-force", type=int, metavar="PORT")
    owners = cli.add_mutually_exclusive_group()
    owners.add_argument("-pid", type=int, metavar="PID")
    owners.add_argument("-unit", metavar="NAME.service")
    proto = cli.add_mutually_exclusive_group()
    proto.add_argument("-tcp", dest="protocol", action="store_const", const="tcp")
    proto.add_argument("-udp", dest="protocol", action="store_const", const="udp")
    args = cli.parse_args(argv)
    if args.force is not None:
        if not 1 <= args.force <= 65535 or not args.protocol:
            raise UsageError("Force requires a port 1-65535 and -tcp or -udp")
        if args.pid is None and args.unit is None:
            raise UsageError("Force requires the exact -pid or -unit shown by -check")
        if args.pid is not None and args.pid <= 1:
            raise UsageError("Invalid or protected PID")
        return release(args.force, args.protocol, args.unit, args.pid)
    if args.pid is not None or args.unit is not None:
        raise UsageError("-pid and -unit require -force")
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
