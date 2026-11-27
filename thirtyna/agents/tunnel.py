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


def run(argv):
    cli = parser(SWITCH, NAME + " manages OpenSSH forward and reverse tunnels.",
                 "Example: 30na -tunnel -forward -localhost -id 1 -local-port 8080 -remote-id 3 -remote-port 443")
    mode = cli.add_mutually_exclusive_group(required=True)
    mode.add_argument("-forward", action="store_true")
    mode.add_argument("-reverse", action="store_true")
    mode.add_argument("-list", action="store_true")
    mode.add_argument("-stop", action="store_true")
    endpoint = cli.add_mutually_exclusive_group()
    endpoint.add_argument("-ip", metavar="LOCAL_IP", help="Explicit IP assigned to this server")
    endpoint.add_argument("-localhost", action="store_true", help="Local host ID 1 (loopback)")
    endpoint.add_argument("-domain", dest="ip", metavar="NAME", help=argparse.SUPPRESS)
    remote = cli.add_mutually_exclusive_group()
    remote.add_argument("-remote-ip", "-remote-domain", "-remote-ip/domain", dest="remote", metavar="ADDRESS")
    remote.add_argument("-remote-id", type=int, metavar="ID")
    cli.add_argument("-local-port", metavar="PORT")
    cli.add_argument("-remote-port", metavar="PORT")
    cli.add_argument("-listen", metavar="PORT", help=argparse.SUPPRESS)
    cli.add_argument("-target", metavar="ADDRESS", help=argparse.SUPPRESS)
    cli.add_argument("-target-port", metavar="PORT", help=argparse.SUPPRESS)
    cli.add_argument("-id", metavar="ID", help="Local ID 1 for start; tunnel ID for stop")
    cli.add_argument("-restore", action="store_true", help="Opt in to worker-crash restoration")
    args = cli.parse_args(argv)
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
    elif args.stop:
        if modern or not args.id or any((args.ip, args.listen, args.target, args.target_port, args.restore)):
            raise UsageError("Use -stop -id TUNNEL_ID")
        parameters = {"id": args.id}
        operation = "stop"
    else:
        if modern or any((args.ip, args.listen, args.target, args.target_port, args.id, args.restore)):
            raise UsageError("-list takes no additional options")
        parameters = None
        operation = "list"
    agent = control("ensure", "tunnel", bootstrap=True)
    if agent.get("tunnel_protocol") != 2:
        raise RuntimeError("Restart Service Agent before using this Tunnel release")
    if modern and operation == "start":
        if agent.get("endpoint_protocol") != 1:
            raise RuntimeError("Restart Service Agent before using local/remote endpoints")
        host_agent = control("ensure", "host", bootstrap=True)
        if host_agent.get("endpoint_protocol") != 1:
            raise RuntimeError("Restart Service Agent before using numbered hosts")
        if remote_host is not None:
            # An explicitly supplied remote address is an explicit registration.
            remote_id = request(host_agent, "register", remote_host)["value"]
        else:
            remote_id = args.remote_id
            remote_host = request(host_agent, "lookup", remote_id)["value"]
        parameters.update(host=remote_host, remote_id=remote_id)
    if operation == "start" and is_domain(parameters["host"]) and not agent.get("domain_support"):
        raise RuntimeError("Restart Service Agent before using domain names")
    if agent.get("recovery_warning"):
        import sys
        print("30na: " + agent["recovery_warning"], file=sys.stderr)
    result = request(agent, operation, parameters)["value"]
    if operation == "list":
        for row in result:
            line = "{id} {mode} {host} {listen} {target}:{target_port} pid={pid} state={state}".format(**row)
            if row.get("remote_id") is not None:
                line += " local_id=1 remote_id={remote_id} local={local}:{local_port} remote={host}:{remote_port}".format(**row)
            if row.get("reason"):
                line += " reason=" + row["reason"]
            if row.get("restore"):
                line += " restore=on"
            print(line)
    elif operation == "start":
        print("id={id} pid={pid} state={state}".format(**result) +
              (" restore=on" if result.get("restore") else ""))
        if result.get("remote_id") is not None:
            print("local_id=1 remote_id={remote_id} local={local}:{local_port} remote={host}:{remote_port}".format(**result))
    else:
        print("stopped " + result["id"])
