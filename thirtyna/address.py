"""Shared canonical SSH endpoint validation; no DNS lookup at registration."""
import ipaddress
import re

from thirtyna.core import UsageError

_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_SCOPE = re.compile(r"[A-Za-z0-9_.-]+")


def host_address(value):
    """Accept numeric IP or ASCII fully qualified DNS name (including A-labels)."""
    if not isinstance(value, str) or not value.isascii():
        raise UsageError("Invalid IP address or domain name")
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        if isinstance(ip, ipaddress.IPv6Address) and ip.scope_id:
            if not _SCOPE.fullmatch(ip.scope_id):
                raise UsageError("Invalid IPv6 scope")
        return str(ip)

    name = value.removesuffix(".").lower()
    labels = name.split(".")
    if (len(name) > 253 or len(labels) < 2
            or not all(_LABEL.fullmatch(label) for label in labels)
            or not any("a" <= ch <= "z" for ch in labels[-1])):
        raise UsageError("Invalid IP address or domain name")
    return name


def is_domain(canonical):
    try:
        ipaddress.ip_address(canonical)
        return False
    except ValueError:
        return True
