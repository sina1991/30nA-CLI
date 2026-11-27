"""Public Tunnel Agent CLI; operations execute in a private worker."""
import ipaddress

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
                 "Example: 30na -tunnel -forward -ip 192.0.2.1 -listen 8080 "
                 "-target 127.0.0.1 -target-port 80")
    mode = cli.add_mutually_exclusive_group(required=True)
    mode.add_argument("-forward", action="store_true")
    mode.add_argument("-reverse", action="store_true")
    mode.add_argument("-list", action="store_true")
    mode.add_argument("-stop", action="store_true")
    cli.add_argument("-ip", metavar="REGISTERED_HOST")
    cli.add_argument("-listen", metavar="PORT")
    cli.add_argument("-target", metavar="ADDRESS")
    cli.add_argument("-target-port", metavar="PORT")
    cli.add_argument("-id", metavar="TUNNEL_ID")
    args = cli.parse_args(argv)
    if args.forward or args.reverse:
        if args.id or not all((args.ip, args.listen, args.target, args.target_port)):
            raise UsageError("Tunnel requires -ip, -listen, -target and -target-port")
        parameters = dict(mode="forward" if args.forward else "reverse",
                          host=address(args.ip), listen=port(args.listen),
                          target=address(args.target), target_port=port(args.target_port))
        operation = "start"
    elif args.stop:
        if not args.id or any((args.ip, args.listen, args.target, args.target_port)):
            raise UsageError("Use -stop -id TUNNEL_ID")
        parameters = {"id": args.id}
        operation = "stop"
    else:
        if any((args.ip, args.listen, args.target, args.target_port, args.id)):
            raise UsageError("-list takes no additional options")
        parameters = None
        operation = "list"
    agent = control("ensure", "tunnel", bootstrap=True)
    result = request(agent, operation, parameters)["value"]
    if operation == "list":
        for row in result:
            line = "{id} {mode} {host} {listen} {target}:{target_port} pid={pid} state={state}".format(**row)
            if row.get("reason"):
                line += " reason=" + row["reason"]
            print(line)
    elif operation == "start":
        print("id={id} pid={pid} state={state}".format(**result))
    else:
        print("stopped " + result["id"])
