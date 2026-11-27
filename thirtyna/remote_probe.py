"""Read-only inventory of known SSH tunnel units; standalone stdlib probe."""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess

UNIT = re.compile(r"(?:ssh-tunnel-[0-9]+|stm-r-[a-z0-9]+|nt-[a-z0-9]+|gr02-iran-reverse|30na-tunnel-[0-9a-f]{24})\.service\Z")
HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9.:%_-]{0,252}\Z")
MAX_UNITS = 64


def run(args):
    result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, timeout=4, env=dict(os.environ, LC_ALL="C", SYSTEMD_COLORS="0"))
    if result.returncode:
        raise RuntimeError("Probe command failed")
    return result.stdout


def parse_exec(value):
    """Only recognize the reference manager's explicit, ordinary IPv4 TCP forwards."""
    match = re.search(r"argv\[\]=(.*?)\s*;", value)
    if not match:
        return None
    try:
        args = shlex.split(match.group(1))
    except ValueError:
        return None
    if not args or args[0] not in ("/usr/bin/ssh", "/bin/ssh"):
        return None
    forwards = [(i, arg) for i, arg in enumerate(args) if arg in ("-L", "-R")]
    if len(forwards) != 1 or any(arg.startswith(("-L", "-R")) and arg not in ("-L", "-R") for arg in args):
        return None
    i, flag = forwards[0]
    if i + 2 >= len(args):
        return None
    fields = args[i+1].split(":")
    if len(fields) != 4 or fields[0] not in ("0.0.0.0", "127.0.0.1") or fields[2] != "127.0.0.1":
        return None
    try:
        lp, rp = int(fields[1]), int(fields[3])
        if not (1 <= lp <= 65535 and 1 <= rp <= 65535):
            return None
        peer = args[-1].rsplit("@", 1)[-1].lower().rstrip(".")
        if not HOST.fullmatch(peer):
            return None
        ssh_port = int(args[args.index("-p") + 1]) if "-p" in args else 22
        if not 1 <= ssh_port <= 65535:
            return None
    except (ValueError, IndexError):
        return None
    return dict(mode="forward" if flag == "-L" else "reverse", bind=fields[0],
                local_port=lp, remote_port=rp, ssh_peer=peer, ssh_port=ssh_port)


def addresses():
    result = []
    for value in run(["hostname", "-I"]).split():
        try:
            ip = ipaddress.ip_address(value)
            if not ip.is_loopback and not ip.is_unspecified:
                result.append(str(ip))
        except ValueError:
            pass
    return sorted(set(result))


def resolve(peer):
    try:
        return sorted({str(ipaddress.ip_address(row[4][0]))
                       for row in socket.getaddrinfo(peer, None, type=socket.SOCK_STREAM)})
    except (OSError, ValueError):
        return []


def listening():
    rows = []
    for line in run(["ss", "-H", "-ltnp"]).splitlines():
        parts = line.split(None, 5)
        if len(parts) < 5:
            continue
        addr, _, port = parts[3].rpartition(":")
        if not port.isdecimal() or not 1 <= int(port) <= 65535:
            continue
        owners = []
        if len(parts) == 6:
            for name, pid in re.findall(r'"(ssh|sshd|sshd-session)",pid=(\d+)', parts[5]):
                owners.append([name, int(pid)])
        rows.append(dict(port=int(port), addr=addr, owners=owners))
    return rows[:4096]


def probe():
    machine = Path("/etc/machine-id").read_bytes().strip()
    if not re.fullmatch(rb"[0-9a-f]{32}", machine):
        raise RuntimeError("Machine identity unavailable")
    result = dict(machine=hashlib.sha256(machine).hexdigest(), ips=addresses(), units=[], complete=True, listeners=None)
    try:
        result["listeners"] = listening()
    except (OSError, RuntimeError, subprocess.SubprocessError):
        result["complete"] = False
    listing = run(["systemctl", "--no-pager", "--no-legend", "--plain",
                   "list-units", "--all", "--type=service"])
    units = sorted({line.split()[0] for line in listing.splitlines()
                    if line.split() and UNIT.fullmatch(line.split()[0])})
    if len(units) > MAX_UNITS:
        result["complete"] = False
    for unit in units[:MAX_UNITS]:
        try:
            raw = run(["systemctl", "--no-pager", "show", "--property=ActiveState,MainPID,ExecStart", "--", unit])
            props = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
            spec = parse_exec(props.get("ExecStart", ""))
            if spec is None:
                result["units"].append(dict(unit=unit, recognized=False))
                continue
            state = props.get("ActiveState", "unknown")
            if state not in ("active", "inactive", "failed", "activating", "deactivating"):
                state = "unknown"
            result["units"].append(dict(unit=unit, recognized=True, state=state,
                                        peer_ips=resolve(spec["ssh_peer"]),
                                        pid=int(props.get("MainPID", "0")) if props.get("MainPID", "").isdecimal() else 0, **spec))
        except (OSError, RuntimeError, subprocess.SubprocessError):
            result["units"].append(dict(unit=unit, recognized=False))
            result["complete"] = False
    # No raw ExecStart, environment, credentials or arbitrary command output.
    return result


if __name__ == "__main__":
    try:
        print(json.dumps(probe(), separators=(",", ":")))
    except (OSError, RuntimeError, subprocess.SubprocessError):
        raise SystemExit("Inventory unavailable")
