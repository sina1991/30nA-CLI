from thirtyna.address import host_address, is_domain
import subprocess
import sys
from thirtyna.runtime.service import control, request

from thirtyna.core import UsageError, input_value, parser

SWITCH = "-host"
NAME = "Host Agent"


def run(argv):
    cli = parser(SWITCH, NAME + " manages saved IP addresses and DNS names and opens SSH.",
                 "Example: echo 192.0.2.1 | 30na -host -add -ip. Supply the IP "
                 "as an argument, on stdin or at the prompt. Add -ssh to connect after saving.")
    group = cli.add_mutually_exclusive_group()
    for flag in ("add", "remove", "list"):
        group.add_argument("-" + flag, action="store_true")
    endpoint = cli.add_mutually_exclusive_group()
    endpoint.add_argument("-ip", nargs="?", const="", metavar="ADDRESS", help="IPv4, IPv6 or DNS name")
    endpoint.add_argument("-domain", dest="ip", nargs="?", const="", metavar="NAME", help="Alias for -ip")
    cli.add_argument("-ssh", action="store_true")
    args = cli.parse_args(argv)
    agent = control("ensure", bootstrap=True)
    address = None
    if args.list:
        if args.ip is not None or args.ssh:
            raise UsageError("-list takes no other options")
    elif args.ip is None or not (args.add or args.remove or args.ssh) or (args.remove and args.ssh):
        raise UsageError("Use -list, -add -ip, -remove -ip or -ssh -ip")
    else:
        address = host_address(args.ip or input_value("IP address:"))
        if is_domain(address) and not agent.get("domain_support"):
            raise RuntimeError("Restart Service Agent before using domain names")
    op = "list" if args.list else "add" if args.add else "remove" if args.remove else "exists"
    reply = request(agent, op, address)
    if args.list:
        for ip in reply["value"]:
            print(ip)
    if args.ssh:
        options = [] if sys.stdin.isatty() else ["-o", "BatchMode=yes"]
        status = subprocess.run(["ssh", *options, "--", address]).returncode
        if status:
            raise RuntimeError(f"SSH exited with status {status}")
