"""Reusable terminal regions, contextual help and local picker suggestions."""
from dataclasses import dataclass
import ipaddress


HELP = {
    "Calculator": "Decimal arithmetic. Choose an operation and enter two numbers.",
    "System": "Read Linux hostname, OS, kernel, uptime, CPU, RAM, disk and assigned interface IPs.",
    "Host": "Register IP/DNS, list, remove or open interactive SSH. f selects a saved host.",
    "Tunnel": "Local ID 1 / numbered remote. Forward listens locally; reverse listens remotely. f selects endpoints and ports.",
    "Files": "Browse, copy, move and edit files in the two-pane manager.",
    "Help": "Open exact CLI help for any public agent.",
    "Ports": "Inspect local TCP/UDP ports, sockets, process owners and observed systemd units. Emergency release requires exact owner and confirmation.",
    "Services": "Systemd: list units, status, logs, start/stop/restart, enable/disable. Changes require confirmation.",
}

FIELD_HELP = {
    "host": "f: numbered SSH hosts; Enter: type a value.",
    "local": "f: Local ID 1 or assigned interface IP. Explicit IP may expose a forward listener.",
    "remote": "f: saved remote ID or enter an IP/domain. Direct address is registered.",
    "local-port": "Local endpoint port; listener in Forward, service in Reverse.",
    "remote-port": "Remote endpoint port; service in Forward, listener in Reverse.",
    "listen": "f: common listen ports (not checked for availability).",
    "target": "f: loopback, actual local interface IPs or custom IP. Forward target is remote; reverse target is local.",
    "target-port": "f: common destination ports; Enter: type any valid port.",
    "restore": "f: yes/no. Restores only ready opted-in sessions after worker crash.",
    "tunnel": "f: choose an existing tunnel ID.",
    "protocol": "f: select TCP or UDP.",
    "unit": "f: choose an installed or loaded .service unit.",
}


@dataclass(frozen=True)
class Layout:
    top: int
    left: int
    width: int
    right: int
    body: int
    expanded: bool


def layout(height, width):
    # Reserve the four footer lines at every size.
    if height >= 19 and width >= 100:
        left, right = 21, width - 27
        return Layout(9, left, right-left-1, right, height-13, True)
    if height >= 12:
        return Layout(4, 1, width-2, 0, height-8, False)
    return Layout(2, 1, width-2, 0, height-6, False)


def suggestions(kind, current="", local_ips=()):
    if kind == "protocol":
        return [("tcp", "TCP"), ("udp", "UDP")]
    if kind == "restore":
        pairs = [("no", "No - default"), ("yes", "Yes - worker crash recovery")]
    elif kind in ("listen", "target-port", "local-port", "remote-port"):
        ports = ("5555", "8080", "8443", "443", "80", "22", "3306", "5432")
        pairs = [(p, p + " (suggestion)") for p in ports]
    elif kind == "target":
        pairs = [("127.0.0.1", "127.0.0.1 (IPv4 loopback)"),
                 ("::1", "::1 (IPv6 loopback)")]
        for host in local_ips:
            try:
                ip = str(ipaddress.ip_address(host))
            except ValueError:
                continue
            if ip not in {value for value, _ in pairs}:
                pairs.append((ip, ip + " (local interface)"))
    else:
        pairs = []
    if current and current not in {value for value, _ in pairs}:
        pairs.insert(0, (current, current + " (current)"))
    if kind != "restore":
        pairs.append((None, "[Enter custom value]"))
    return pairs
