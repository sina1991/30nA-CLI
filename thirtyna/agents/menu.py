import importlib
import os
import sys
from pathlib import Path

from thirtyna.core import parser
from thirtyna.menus.model import MENUS, MenuSession

SWITCH = "-menu"
NAME = "Menu Agent"


def run(argv):
    cli = parser(SWITCH, "Browse registered menus and directories.",
                 "Examples: 30na -menu | 30na -menu -dir /var -tui | 30na -menu -gui")
    targets = cli.add_mutually_exclusive_group()
    for key, (title, _) in MENUS.items():
        targets.add_argument("-" + key, dest="target", nargs="?", const=".",
                             metavar="PATH", type=lambda value, k=key: (k, value),
                             help=title)
    modes = cli.add_mutually_exclusive_group()
    for flag, module in (("text", "numbered"), ("tui", "terminal"), ("gui", "window")):
        modes.add_argument("-" + flag, action="store_const", dest="view", const=module)
    args = cli.parse_args(argv)
    session = MenuSession(Path.cwd(), args.target)
    mode = args.view or "numbered"
    if mode == "window" and not os.environ.get("DISPLAY") and sys.stdin.isatty() and sys.stdout.isatty():
        print("No graphical display. Opening the numbered directory menu.", file=sys.stderr)
        mode = "numbered"
    view = importlib.import_module("thirtyna.menus." + mode)
    try:
        view.show(session)
    except KeyboardInterrupt:
        return 130
