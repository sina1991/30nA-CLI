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
    for row in value["units"]:
        if not UNIT.fullmatch(row["unit"]) or type(row["recognized"]) is not bool:
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
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
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


def render(nodes):
    # Refuse to resolve aliases as distinct nodes when their machine IDs match.
    counts = {}
    for _, probe in nodes.values():
        if probe:
            counts[probe["machine"]] = counts.get(probe["machine"], 0) + 1
    incomplete = False
    for number, (address, probe) in nodes.items():
        if probe is None:
            print(f"HOST {number} {address} inventory=UNKNOWN")
            incomplete = True
            continue
        if counts[probe["machine"]] > 1:
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
            peer = identify_peer(row, nodes, number)
            if peer is not None and counts[nodes[peer][1]["machine"]] != 1:
                peer = None
            if peer is None:
                incomplete = True
            peer_id = peer if peer is not None else "?"
            local, remote = (number, peer_id) if row["mode"] == "forward" else (peer_id, number)
            print(f"  {row['mode']} local_id={local} local_port={row['local_port']} "
                  f"remote_id={remote} remote_port={row['remote_port']} ssh_client_id={number} "
                  f"ssh_peer={row['ssh_peer']} ssh_port={row['ssh_port']} bind={row['bind']} "
                  f"unit={row['unit']} service_state={row['state']} ownership=external")
    print("Observed unit configuration only; no end-to-end TCP health claim. No changes made.")
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
    key = existing_identity() if remotes else None
    nodes = {1: ("LOCAL", collect())}
    with ThreadPoolExecutor(max_workers=4) as pool:
        probes = list(pool.map(lambda row: collect(row[1], key), remotes))
    nodes.update({number: (address, probe) for (number, address), probe in zip(remotes, probes)})
    return render(nodes)
