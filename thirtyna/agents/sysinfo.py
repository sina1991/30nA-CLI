import platform
import shutil
from pathlib import Path

from thirtyna.core import UsageError, parser

SWITCH = "-sys"
NAME = "System Agent"


def report(field):
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
    for field in ("hostname", "os", "kernel", "uptime", "cpu", "ram", "disk"):
        cli.add_argument("-" + field, action="store_true")
    args = vars(cli.parse_args(argv))
    if not any(args.values()):
        raise UsageError("Select a system field")
    for field, selected in args.items():
        if selected:
            print(report(field))
