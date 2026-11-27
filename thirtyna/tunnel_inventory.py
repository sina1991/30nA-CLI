"""Observe reference-style systemd tunnels without adopting or stopping them."""
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import sys

from thirtyna.address import host_address
from thirtyna.core import UsageError
from thirtyna.onboarding import ssh_options, verify_identity_config
from thirtyna.remote_probe import UNIT, HOST, MAX_UNITS
from thirtyna.ssh_identity import existing_identity

MAX_HOSTS = 16


def checked_ips(values):
    if not isinstance(values, list) or len(values) > 256:
        raise ValueError("Invalid addresses")
    return {str(ipaddress.ip_address(x)) for x in values}


def validate(value):
    if not isinstance(value, dict) or not re.fullmatch(r"[0-9a-f]{64}", value.get("machine", "")):
        raise ValueError("Invalid probe identity")
    value["ips"] = checked_ips(value["ips"])
    if type(value["complete"]) is not bool or not isinstance(value["units"], list) or len(value["units"]) > MAX_UNITS:
        raise ValueError("Invalid probe inventory")
    listeners = value["listeners"]
    if listeners is not None:
        if not isinstance(listeners, list) or len(listeners) > 4096:
            raise ValueError("Invalid listener inventory")
        for listener in listeners:
            if type(listener["port"]) is not int or not 1 <= listener["port"] <= 65535 or not isinstance(listener["addr"], str) or not isinstance(listener["owners"], list):
                raise ValueError("Invalid listener")
            for name, pid in listener["owners"]:
                if name not in ("ssh", "sshd", "sshd-session") or type(pid) is not int or pid <= 0:
                    raise ValueError("Invalid listener owner")
    for row in value["units"]:
        if not isinstance(row, dict) or not UNIT.fullmatch(row["unit"]) or type(row["recognized"]) is not bool:
            raise ValueError("Invalid unit")
        if not row["recognized"]:
            continue
        if row["mode"] not in ("forward", "reverse") or row["bind"] not in ("0.0.0.0", "127.0.0.1"):
            raise ValueError("Invalid mode")
        if row["state"] not in ("active", "inactive", "failed", "activating", "deactivating", "unknown"):
            raise ValueError("Invalid state")
        if not HOST.fullmatch(row["ssh_peer"]):
            raise ValueError("Invalid SSH peer")
        for name in ("local_port", "remote_port", "ssh_port"):
            if type(row[name]) is not int or not 1 <= row[name] <= 65535:
                raise ValueError("Invalid port")
        if type(row["pid"]) is not int or row["pid"] < 0:
            raise ValueError("Invalid service PID")
        row["peer_ips"] = checked_ips(row["peer_ips"])
    return value


def collect(address=None, key=None):
    source = Path(__file__).with_name("remote_probe.py")
    try:
        if address is None:
            argv = [sys.executable, str(source)]
            data = None
        else:
            if key is None:
                return None
            verify_identity_config(address, key)
            argv = ["ssh", "-T", *ssh_options(key), "--", address, "python3", "-"]
            data = source.read_text()
        result = subprocess.run(argv, input=data, text=True, capture_output=True, timeout=25)
        if result.returncode or len(result.stdout) > 262144:
            return None
        return validate(json.loads(result.stdout))
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError):
        return None


def identify_peer(row, nodes, client):
    # Match the SSH destination to exactly one observed machine. DNS/IP
    # overlap is a candidate, not proof of the effective SSH configuration.
    matches = []
    for number, (address, probe) in nodes.items():
        if number == client or probe is None:
            continue
        if row["ssh_peer"] == address or row["peer_ips"] & probe["ips"]:
            matches.append(number)
    return matches[0] if len(matches) == 1 else None


def listener_status(row, local_probe):
    if local_probe is None or local_probe["listeners"] is None:
        return "UNKNOWN"
    listeners = [listener for listener in local_probe["listeners"]
                 if listener["port"] == row["local_port"]]
    if not listeners:
        return "ABSENT"
    for listener in listeners:
        # Public wildcard and loopback are not interchangeable.
        if listener["addr"] not in (("0.0.0.0", "*") if row["bind"] == "0.0.0.0" else ("127.0.0.1",)):
            continue
        if row["mode"] == "forward" and row["pid"] > 0:
            if ["ssh", row["pid"]] in listener["owners"]:
                return "MATCHED_PID"
        elif row["mode"] == "reverse" and any(name in ("sshd", "sshd-session") for name, _ in listener["owners"]):
            return "SSHD_OBSERVED"
    return "UNVERIFIED_OWNER_OR_BIND"


def render(nodes):
    # Local ID 1 is authoritative for aliases of this machine. Multiple
    # remote IDs with the same machine ID remain ambiguous, not distinct hosts.
    groups = {}
    for number, (_, probe) in nodes.items():
        if probe:
            groups.setdefault(probe["machine"], []).append(number)
    aliases = {}
    excluded = set()
    for ids in groups.values():
        if len(ids) > 1:
            if 1 in ids:
                aliases.update({number: 1 for number in ids if number != 1})
            else:
                excluded.update(ids)
    unique = {number: data for number, data in nodes.items()
              if number not in aliases and number not in excluded}
    incomplete = False
    for number, (address, probe) in nodes.items():
        if probe is None:
            print(f"HOST {number} {address} inventory=UNKNOWN")
            incomplete = True
            continue
        if number in aliases:
            print(f"HOST {number} {address} inventory=LOCAL_ALIAS canonical_id=1")
            continue
        if number in excluded:
            print(f"HOST {number} {address} inventory=AMBIGUOUS duplicate_machine")
            incomplete = True
            continue
        print(f"HOST {number} {address} inventory={'COMPLETE' if probe['complete'] else 'PARTIAL'}")
        incomplete |= not probe["complete"]
        for row in probe["units"]:
            if not row["recognized"]:
                print(f"  unit={row['unit']} topology=UNKNOWN ownership=external")
                incomplete = True
                continue
            peer = identify_peer(row, unique, number)
            # An exact registered alias of the observed local machine is
            # sufficient for an inventory candidate, but not authorization.
            if peer is None and number != 1 and any(nodes[alias][0] == row["ssh_peer"] for alias in aliases):
                peer = 1
            if peer is None:
                incomplete = True
            peer_id = peer if peer is not None else "?"
            local, remote = (number, peer_id) if row["mode"] == "forward" else (peer_id, number)
            listener = listener_status(row, unique.get(local, (None, None))[1])
            print(f"  {row['mode']} local_id={local} local_port={row['local_port']} "
                  f"remote_id={remote} remote_port={row['remote_port']} ssh_client_id={number} "
                  f"ssh_peer={row['ssh_peer']} ssh_port={row['ssh_port']} bind={row['bind']} "
                  f"unit={row['unit']} service_state={row['state']} listener={listener} ownership=external")
    print("Observed configuration and socket evidence only; no end-to-end TCP health claim. No changes made.")
    return 1 if incomplete else 0


def discover(remote_id=None):
    from thirtyna.runtime.service import control, request
    agent = control("ensure", "host", bootstrap=True)
    if agent.get("endpoint_protocol") != 1:
        raise RuntimeError("Numbered hosts require a compatible Host Agent")
    rows = request(agent, "ids")["value"]
    remotes = [(row["id"], host_address(row["ip"])) for row in rows
               if remote_id is None or row["id"] == remote_id]
    if remote_id is not None and not remotes:
        raise UsageError("Remote host ID not found")
    if len(remotes) > MAX_HOSTS:
        raise UsageError("Too many hosts for one discovery; select -remote-id")
    try:
        key = existing_identity() if remotes else None
    except (OSError, RuntimeError):
        key = None
    nodes = {1: ("LOCAL", collect())}
    with ThreadPoolExecutor(max_workers=4) as pool:
        probes = list(pool.map(lambda row: collect(row[1], key), remotes))
    nodes.update({number: (address, probe) for (number, address), probe in zip(remotes, probes)})
    return render(nodes)
