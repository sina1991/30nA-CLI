"""Public two-endpoint contract; local identity comes from this Linux system."""
import ipaddress
from thirtyna.core import UsageError
from thirtyna.agents.sysinfo import local_addresses


def local_ip(value=None):
    if value is None:
        return "127.0.0.1"
    try:
        ip = ipaddress.ip_address(value)
    except (TypeError, ValueError) as exc:
        raise UsageError("Local IP must be numeric and assigned to this server") from exc
    if not ip.is_loopback and str(ip) not in local_addresses():
        raise UsageError("Local IP is not assigned to this server")
    # Scope identifiers are not supported in the new forwarding contract.
    if getattr(ip, "scope_id", None):
        raise UsageError("Scoped local addresses are not supported")
    return str(ip)


def host_ids(agent):
    from thirtyna.runtime.service import request
    import platform
    if not agent.get("endpoint_protocol"):
        raise RuntimeError("Restart Service Agent to use numbered hosts")
    ips = local_addresses()
    print("1 LOCAL " + platform.node() + " " + (" ".join(ips) or "loopback-only"))
    for row in request(agent, "ids")["value"]:
        print(f'{row["id"]} REMOTE {row["ip"]}')
