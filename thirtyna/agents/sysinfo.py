import ipaddress
import platform
import shutil
import subprocess
from pathlib import Path

from thirtyna.core import UsageError, parser

SWITCH = "-sys"
NAME = "System Agent"


def local_addresses():
    """Read assigned non-loopback interface addresses, not DNS or saved hosts."""
    try:
        result = subprocess.run(["hostname", "-I"], capture_output=True, text=True,
                                check=True, timeout=3)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("Local interface addresses unavailable") from exc
    addresses = []
    for value in result.stdout.split():
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if not address.is_loopback and not address.is_unspecified and str(address) not in addresses:
            addresses.append(str(address))
    return addresses


def report(field):
    if field == "ip":
        return " ".join(local_addresses()) or "none"
    if field == "hostname":
        return platform.node()
    if field == "os":
        return platform.freedesktop_os_release()["PRETTY_NAME"]
    if field == "kernel":
        return platform.release()
    if field == "uptime":
        return Path("/proc/uptime").read_text().split()[0] + " seconds"
    if field == "cpu":
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.partition(":")[2].strip()
        return platform.machine()
    if field == "ram":
        return Path("/proc/meminfo").read_text().splitlines()[0]
    disk = shutil.disk_usage("/")
    return f"/ total={disk.total} used={disk.used} free={disk.free} bytes"


def run(argv):
    cli = parser(SWITCH, NAME + " reads Linux system information.",
                 "Example: 30na -sys -hostname -kernel. Flags only, no input required.")
    for field in ("hostname", "os", "kernel", "uptime", "cpu", "ram", "disk", "ip"):
        cli.add_argument("-" + field, action="store_true")
    args = vars(cli.parse_args(argv))
    if not any(args.values()):
        raise UsageError("Select a system field")
    for field, selected in args.items():
        if selected:
            print(report(field))
