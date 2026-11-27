"""Public Tunnel Agent CLI; operations execute in a private worker."""
import argparse
import ipaddress
from thirtyna.address import host_address, is_domain

from thirtyna.core import UsageError, parser
from thirtyna.runtime.service import control, request

SWITCH = "-tunnel"
NAME = "Tunnel Agent"


def port(value):
    try:
        number = int(value)
    except (ValueError, TypeError) as exc:
        raise UsageError("Port must be an integer from 1 to 65535") from exc
    if not 1 <= number <= 65535:
        raise UsageError("Port must be an integer from 1 to 65535")
    return number


def address(value):
    try:
        return str(ipaddress.ip_address(value))
    except ValueError as exc:
        raise UsageError("Invalid IP address") from exc


def endpoint_label(host, number):
    return f'[{host}]:{number}' if ":" in host else f"{host}:{number}"


def describe_endpoints(row):
    return ("local_id=1 local=" + endpoint_label(row["local"], row["local_port"]) +
            " remote_id=" + str(row["remote_id"]) + " remote=" + endpoint_label(row["host"], row["remote_port"]))


def run(argv):
    cli = parser(SWITCH, NAME + " manages OpenSSH forward and reverse tunnels.",
                 "Example: 30na -tunnel -forward -localhost -id 1 -local-port 8080 -remote-id 3 -remote-port 443")
    mode = cli.add_mutually_exclusive_group(required=True)
    mode.add_argument("-forward", action="store_true")
    mode.add_argument("-reverse", action="store_true")
    mode.add_argument("-list", action="store_true")
    mode.add_argument("-discover", action="store_true", help="Read-only inventory of external SSH tunnel services")
    mode.add_argument("-stop", action="store_true", help="Stop a managed tunnel or end a temporary session")
    mode.add_argument("-start", action="store_true", help="Start a previously stopped managed tunnel")
    mode.add_argument("-restart", action="store_true", help="Restart a managed tunnel")
    mode.add_argument("-delete", action="store_true", help="Delete a managed tunnel and its owned resources")
    endpoint = cli.add_mutually_exclusive_group()
    endpoint.add_argument("-ip", metavar="LOCAL_IP", help="Explicit IP assigned to this server")
    endpoint.add_argument("-localhost", action="store_true", help="Local host ID 1 (loopback)")
    endpoint.add_argument("-domain", dest="ip", metavar="NAME", help=argparse.SUPPRESS)
    remote = cli.add_mutually_exclusive_group()
    remote.add_argument("-remote-ip", "-remote-domain", dest="remote", metavar="ADDRESS")
    remote.add_argument("-remote-ip/domain", dest="remote", metavar="ADDRESS", help=argparse.SUPPRESS)
    remote.add_argument("-remote-id", type=int, metavar="ID")
    cli.add_argument("-local-port", metavar="PORT")
    cli.add_argument("-remote-port", metavar="PORT")
    cli.add_argument("-listen", metavar="PORT", help=argparse.SUPPRESS)
    cli.add_argument("-target", metavar="ADDRESS", help=argparse.SUPPRESS)
    cli.add_argument("-target-port", metavar="PORT", help=argparse.SUPPRESS)
    cli.add_argument("-id", metavar="ID", help="Local ID 1 for start; tunnel ID for stop")
    cli.add_argument("-restore", action="store_true", help="Opt in to worker-crash restoration")
    cli.add_argument("-persistent", action="store_true", help="Run numbered Forward as a boot-enabled systemd service")
    args = cli.parse_args(argv)
    if args.persistent and (not args.forward or args.remote_id is None or args.restore):
        raise UsageError("Use -persistent with -forward -remote-id ID and omit -restore")
    if args.discover:
        if any((args.localhost, args.ip is not None, args.remote is not None,
                args.local_port is not None, args.remote_port is not None,
                args.listen is not None, args.target is not None, args.target_port is not None,
                args.id is not None, args.restore)) or (args.remote_id is not None and args.remote_id < 2):
            raise UsageError("Use -discover [-remote-id ID]")
        from thirtyna.tunnel_inventory import discover
        return discover(args.remote_id)
    modern = any((args.localhost, args.remote is not None, args.remote_id is not None,
                  args.local_port is not None, args.remote_port is not None))
    remote_host = None
    if args.forward or args.reverse:
        direction = "forward" if args.forward else "reverse"
        if modern:
            from thirtyna.endpoints import local_ip
            if args.target is not None or args.target_port is not None:
                raise UsageError("Do not mix endpoint and legacy target options")
            if args.local_port is not None and args.listen is not None:
                raise UsageError("Use -local-port, not both port aliases")
            if args.id is not None and (args.id != "1" or not args.localhost):
                raise UsageError("Local host ID is always 1")
            if args.localhost and args.id not in (None, "1"):
                raise UsageError("Local host ID is always 1")
            local = local_ip(args.ip)
            lp = port(args.local_port if args.local_port is not None else args.listen)
            rp = port(args.remote_port)
            if args.remote_id is not None and args.remote_id < 2:
                raise UsageError("Remote host ID must be at least 2")
            if args.remote is None and args.remote_id is None:
                raise UsageError("Select -remote-id or -remote-ip/-remote-domain")
            remote_host = host_address(args.remote) if args.remote is not None else None
            parameters = dict(mode=direction, local=local, local_port=lp, remote_port=rp,
                              restore=args.restore)
        else:
            if args.id or not all((args.ip, args.listen, args.target, args.target_port)):
                raise UsageError("Use -local-port, -remote-id or -remote-ip, and -remote-port")
            parameters = dict(mode=direction, host=host_address(args.ip),
                              listen=port(args.listen), target=address(args.target),
                              target_port=port(args.target_port), restore=args.restore)
        operation = "start"
    elif args.stop or args.start or args.restart or args.delete:
        if modern or not args.id or any((args.ip, args.listen, args.target, args.target_port, args.restore)):
            raise UsageError("Use -stop, -start, -restart or -delete with -id TUNNEL_ID")
        parameters = {"id": args.id}
        operation = "stop" if args.stop else "resume" if args.start else "restart" if args.restart else "delete"
    else:
        if modern or any((args.ip, args.listen, args.target, args.target_port, args.id, args.restore)):
            raise UsageError("-list takes no additional options")
        parameters = None
        operation = "list"
    from thirtyna import persistent_forward, two_vps
    if operation in ("stop", "resume", "restart", "delete"):
        token = parameters["id"]
        if persistent_forward.operate(token, operation) or two_vps.operate(token, operation):
            verb = {"stop": "stopped", "resume": "started", "restart": "restarted", "delete": "deleted"}
            print(f"{verb[operation]} {token}")
            return 0
        if operation != "stop":
            raise UsageError("Managed tunnel ID not found")
    if modern and operation == "start":
        host_agent = control("ensure", "host", bootstrap=True)
        if host_agent.get("endpoint_protocol") != 1:
            raise RuntimeError("Restart Service Agent before using numbered hosts")
        if remote_host is not None:
            request(host_agent, "exists", remote_host)
            entries = request(host_agent, "ids", None)["value"]
            remote_id = next(row["id"] for row in entries if row["ip"] == remote_host)
        else:
            remote_id = args.remote_id
            remote_host = request(host_agent, "lookup", remote_id)["value"]
        from thirtyna.onboarding import enroll
        enroll(remote_host, interactive=False)
        parameters.update(host=remote_host, remote_id=remote_id)
        if direction == "reverse":
            result = two_vps.start(parameters)
            print("id={id} pid={pid} state={state}".format(**result))
            print(describe_endpoints(result) + " ssh_client=remote unit=" + two_vps.unit(result))
            return 0
        if args.persistent:
            result = persistent_forward.start(parameters)
            print("id={id} pid={pid} state={state}".format(**result))
            print(describe_endpoints(result) + " unit=" + two_vps.unit(result))
            return 0
    agent = control("ensure", "tunnel", bootstrap=True)
    if agent.get("tunnel_protocol") != 2:
        raise RuntimeError("Restart Service Agent before using this Tunnel release")
    if modern and operation == "start" and agent.get("endpoint_protocol") != 1:
        raise RuntimeError("Restart Service Agent before using local/remote endpoints")
    if modern and operation == "start" and direction == "forward" and not agent.get("management_forward_identity"):
        from thirtyna.ssh_identity import existing_identity
        if existing_identity() is not None:
            raise RuntimeError("Old Tunnel Worker: restart local Service Agent only after stopping or scheduling interruption of its active tunnels")
    if operation == "start" and is_domain(parameters["host"]) and not agent.get("domain_support"):
        raise RuntimeError("Restart Service Agent before using domain names")
    if agent.get("recovery_warning"):
        import sys
        print("30na: " + agent["recovery_warning"], file=sys.stderr)
    result = request(agent, operation, parameters)["value"]
    if operation == "list":
        for row in [*result, *persistent_forward.list_rows(), *two_vps.list_rows()]:
            if row.get("remote_id") is not None:
                line = "{id} {mode} ".format(**row) + describe_endpoints(row) + " pid={pid} state={state}".format(**row)
            else:
                line = "{id} {mode} {host} {listen} {target}:{target_port} pid={pid} state={state}".format(**row)
            if row.get("engine") == "two-vps":
                line += " ssh_client=remote unit=" + two_vps.unit(row) + " persistent=yes"
            elif row.get("engine") == "systemd-forward":
                line += " ssh_client=local unit=" + two_vps.unit(row) + " persistent=yes"
            elif row.get("remote_id") is not None and row["mode"] == "reverse":
                line += " legacy_topology=yes"
            if row.get("reason"):
                line += " reason=" + row["reason"]
            if row.get("restore"):
                line += " restore=on"
            print(line)
    elif operation == "start":
        print("id={id} pid={pid} state={state}".format(**result) +
              (" restore=on" if result.get("restore") else ""))
        if result.get("remote_id") is not None:
            print(describe_endpoints(result))
    else:
        print("stopped " + result["id"])
