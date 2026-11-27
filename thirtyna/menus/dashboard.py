"""Curses command center. All actions delegate to the public CLI of this release."""
from dataclasses import dataclass
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import textwrap
import time

from .model import label

LAUNCHER = Path(__file__).resolve().parents[2] / "30na"
LIMIT = 65536


@dataclass(frozen=True)
class Field:
    name: str
    default: str = ""
    picker: str = ""


@dataclass(frozen=True)
class Action:
    title: str
    args: tuple
    fields: tuple = ()
    interactive: bool = False
    confirm: bool = False
    hint: str = ""

    def command(self, values):
        if len(values) != len(self.fields):
            raise ValueError("Incomplete form")
        args = []
        for part in self.args:
            if isinstance(part, int):
                value = values[part]
                if not value.strip():
                    raise ValueError(self.fields[part].name + " is required")
                args.append(value)
            elif part == "@restore":
                value = values[-1].lower()
                if value not in ("yes", "no"):
                    raise ValueError("Restore must be yes or no")
                if value == "yes":
                    args.append("-restore")
            else:
                args.append(part)
        return args


def tunnel(mode):
    return Action(mode.capitalize() + " tunnel",
                  ("-tunnel", "-" + mode, "-domain", 0, "-listen", 1,
                   "-target", 2, "-target-port", 3, "@restore"),
                  (Field("Registered IP or domain", picker="host"), Field("Listen port", "5555"),
                   Field("Target IP", "127.0.0.1"), Field("Target port", "443"),
                   Field("Restore (yes/no)", "no")),
                  hint="Loopback listener; register the SSH host first.")


SYSTEM = ("hostname", "os", "kernel", "uptime", "cpu", "ram", "disk")
CATALOG = (
    ("Calculator", tuple(Action(title, ("-calc", "-" + op, 0, 1),
                                (Field("First number"), Field("Second number")))
                         for title, op in (("Add", "add"), ("Subtract", "sub"),
                                           ("Multiply", "mul"), ("Divide", "div")))
     + (Action("All four operations",
               ("-calc", "-add", 0, 1, "-sub", 0, 1, "-mul", 0, 1, "-div", 0, 1),
               (Field("First number"), Field("Second number")),
               hint="Prints add, subtract, multiply, divide in that order."),)),
    ("System", (Action("All system fields", ("-sys", *("-" + f for f in SYSTEM))),)
     + tuple(Action(f.capitalize(), ("-sys", "-" + f)) for f in SYSTEM)),
    ("Host", (
        Action("List hosts", ("-host", "-list")),
        Action("Register IP or domain", ("-host", "-add", "-domain", 0),
               (Field("IP or domain"),)),
        Action("Connect SSH", ("-host", "-ssh", "-domain", 0),
               (Field("Registered IP or domain", picker="host"),), interactive=True,
               hint="Uses your SSH configuration. Exit SSH to return."),
        Action("Register and connect", ("-host", "-add", "-domain", 0, "-ssh"),
               (Field("IP or domain"),), interactive=True),
        Action("Remove host", ("-host", "-remove", "-domain", 0),
               (Field("IP or domain", picker="host"),), confirm=True),
    )),
    ("Tunnel", (
        Action("List tunnels", ("-tunnel", "-list")),
        tunnel("forward"), tunnel("reverse"),
        Action("Stop tunnel / clear failed entry", ("-tunnel", "-stop", "-id", 0),
               (Field("Tunnel ID", picker="tunnel"),), confirm=True),
    )),
    ("Files", (
        Action("Open current directory", ("@files",)),
        Action("Open directory by path", ("@files", 0), (Field("Directory", "."),)),
    )),
    ("Help", tuple(Action(name, args) for name, args in (
        ("All agents", ("-help",)), ("Calculator help", ("-calc", "-help")),
        ("System help", ("-sys", "-help")), ("Host help", ("-host", "-help")),
        ("Tunnel help", ("-tunnel", "-help")), ("Menu help", ("-menu", "-help"))))),
)


@dataclass
class Result:
    code: int
    stdout: str = ""
    stderr: str = ""
    truncated: bool = False


def invoke(args, interactive=False, timeout=15):
    """No shell. Pin Python and launcher to the current installed release."""
    argv = [sys.executable, str(LAUNCHER), *args]
    try:
        if interactive:
            return Result(subprocess.run(argv).returncode,
                          "Interactive SSH session ended.")
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            code = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=out,
                                  stderr=err, timeout=timeout).returncode
            out.seek(0)
            err.seek(0)
            a, b = out.read(LIMIT + 1), err.read(LIMIT + 1)
            return Result(code, a[:LIMIT].decode(errors="replace"),
                          b[:LIMIT].decode(errors="replace"),
                          len(a) > LIMIT or len(b) > LIMIT)
    except subprocess.TimeoutExpired:
        return Result(124, stderr="CLI timed out; check actual state before retrying.")
    except OSError as exc:
        return Result(1, stderr=str(exc))


class Snapshot:
    def __init__(self):
        self.hosts = None
        self.tunnels = None
        self.host_time = None
        self.tunnel_time = None

    def invalidate(self, args):
        if args and args[0] == "-host" and "-list" not in args:
            self.hosts = self.host_time = None
        if args and args[0] == "-tunnel" and "-list" not in args:
            self.tunnels = self.tunnel_time = None

    def observe(self, args, result):
        if args == ["-host", "-list"]:
            self.hosts = self.host_time = None
            if result.code == 0 and not result.truncated:
                self.hosts = len(result.stdout.splitlines())
                self.host_time = time.strftime("%H:%M:%S")
        elif args == ["-tunnel", "-list"]:
            self.tunnels = self.tunnel_time = None
            if result.code == 0 and not result.truncated:
                counts = dict(ready=0, starting=0, failed=0)
                for line in result.stdout.splitlines():
                    states = [word[6:] for word in line.split() if word.startswith("state=")]
                    if len(states) != 1 or states[0] not in counts:
                        return
                    counts[states[0]] += 1
                self.tunnels = counts
                self.tunnel_time = time.strftime("%H:%M:%S")

    def summary(self, compact=False):
        hosts = "?" if self.hosts is None else str(self.hosts)
        t = self.tunnels
        tunnels = "?/?/?" if t is None else f'{t["ready"]}/{t["starting"]}/{t["failed"]}'
        if compact:
            return f"H {hosts} | R/S/F {tunnels}"
        ht, tt = self.host_time or "--", self.tunnel_time or "--"
        return f"Hosts {hosts} | Tunnels R/S/F {tunnels} | H {ht} T {tt}"


class Dashboard:
    def __init__(self, screen, c, styles, start, runner=invoke):
        self.screen, self.c = screen, c
        self.accent, self.active, self.normal, self.warning = styles
        self.start, self.runner = start, runner
        self.snapshot = Snapshot()
        self.category = 0
        self.index = 0
        self.page = "home"
        self.action = None
        self.values = []
        self.editing = False
        self.buffer = ""
        self.confirming = False
        self.choices = []
        self.choice_index = 0
        self.status = "READY"
        self.detail = "Choose an agent. r refreshes counts."
        self.output = []
        self.scroll = 0

    def draw(self, y, x, value, style=0, fill=False):
        h, w = self.screen.getmaxyx()
        width = w - x - 1
        if not 0 <= y < h or width <= 0:
            return
        value = label(value)
        if fill:
            value = value.ljust(width)
        try:
            self.screen.addnstr(y, x, value, width, style)
        except self.c.error:
            pass

    def keys(self):
        if self.editing:
            return "Enter save | Esc cancel | Backspace | Ctrl+U erase"
        if self.confirming:
            return "y confirm | n / Esc cancel"
        if self.page == "picker":
            return "Up/Down or j/k | Enter select | Esc cancel"
        if self.page == "result":
            return "j/k or arrows scroll | PgUp/PgDn | Esc back | q quit"
        if self.page == "form":
            return "j/k or Tab | Enter edit/run | f/F2 pick | Esc back"
        return "j/k or arrows | Enter open | r refresh | Esc back | q quit"

    def render(self):
        s = self.screen
        h, w = s.getmaxyx()
        s.erase()
        self.draw(0, 0, " 30nA / AGENT CONTROL CENTER ", self.active, True)
        if h < 8 or w < 24:
            self.draw(2, 0, "Resize terminal (24x8 minimum)", self.warning)
            self.draw(h-1, 0, "q Quit / resize", self.active, True)
            s.refresh()
            return
        category, actions = CATALOG[self.category]
        title = {"home": "AGENTS", "actions": category.upper(),
                 "form": category + " / " + (self.action.title if self.action else ""),
                 "result": "COMMAND OUTPUT", "picker": "SELECT SAVED ENTRY"}[self.page]
        self.draw(1, 1, title, self.accent)
        body = h - 6
        if self.page == "result":
            lines = []
            for line in self.output:
                lines.extend(textwrap.wrap(label(line), max(1, w-3),
                                           replace_whitespace=False,
                                           drop_whitespace=False) or [""])
            max_scroll = max(0, len(lines)-body)
            self.scroll = min(self.scroll, max_scroll)
            for i, line in enumerate(lines[self.scroll:self.scroll+body]):
                self.draw(2+i, 1, line)
        elif self.page == "picker":
            first = max(0, self.choice_index-body+1)
            for i, (_, desc) in enumerate(self.choices[first:first+body], first):
                selected = i == self.choice_index
                self.draw(2+i-first, 1, ("> " if selected else "  ") + desc,
                          self.active if selected else self.normal, fill=selected)
        else:
            if self.page == "home":
                rows = [f"{i+1}. {name}" for i, (name, _) in enumerate(CATALOG)]
            elif self.page == "actions":
                rows = [a.title for a in actions]
            else:
                rows = []
                for i, (f, v) in enumerate(zip(self.action.fields, self.values)):
                    if self.editing and i == self.index:
                        rows.append("Edit: " + self.buffer[-max(1, w-12):] + "_")
                    else:
                        rows.append(f"{f.name}: {v}")
                rows.append("[ RUN COMMAND ]")
                if self.index < len(self.action.fields) and self.action.fields[self.index].picker:
                    rows.append("f / F2: choose a saved entry")
                if self.action.hint:
                    rows.append(self.action.hint)
                try:
                    cmd = "30na " + shlex.join(self.action.command(self.values))
                    if self.action.args[0] != "@files":
                        rows.extend(textwrap.wrap(cmd, max(1, w-4)))
                except ValueError:
                    pass
            first = max(0, self.index-body+1)
            for i, line in enumerate(rows[first:first+body], first):
                self.draw(2+i-first, 1, ("> " if i == self.index else "  ") + line,
                          self.active if i == self.index else self.normal,
                          fill=i == self.index)
        if self.confirming:
            self.draw(h-4, 0, " CONFIRM: " + self.action.title + "? ", self.warning, True)
        else:
            self.draw(h-4, 0, self.snapshot.summary(compact=w < 74),
                      self.warning if self.snapshot.tunnels and self.snapshot.tunnels["failed"]
                      else self.accent, True)
        self.draw(h-3, 0, " STATUS | " + self.status + " | " + self.detail,
                  self.warning if self.status.startswith("ERROR") else self.active, True)
        keys = self.keys()
        legend = " Snapshot: R ready / S starting / F failed; ? unknown"
        if w < 55:
            if self.editing:
                keys = "Enter save | Esc cancel"
            elif self.confirming:
                keys = "y confirm | n cancel"
            elif self.page == "result":
                keys = "j/k scroll | Esc back"
            elif self.page == "picker":
                keys = "j/k | Enter select | Esc"
            elif self.page == "form":
                keys = "j/k Enter f:pick Esc"
            else:
                keys = "j/k Enter r:refresh q"
            legend = "R/S/F snapshot (? unknown)"
        self.draw(h-2, 0, keys, self.accent, True)
        self.draw(h-1, 0, legend, self.normal, True)
        s.refresh()

    def set_result(self, args, result):
        self.snapshot.observe(args, result)
        self.status = ("OK" if result.code == 0 else "ERROR") + f" exit={result.code}"
        self.detail = ("Review output (stderr)" if result.stderr else "Command completed") if result.code == 0 else "Review output"
        self.output = ["$ 30na " + shlex.join(args), ""]
        self.output.extend(result.stdout.splitlines())
        if result.stderr:
            self.output.extend(["", "STDERR:", *result.stderr.splitlines()])
        if result.truncated:
            self.output.append("[Output truncated]")
        if not result.stdout and not result.stderr:
            self.output.append("(No output)")
        if args == ["-tunnel", "-list"]:
            self.output.append("Exit 0 means list succeeded, not all tunnels are ready.")
        self.page, self.scroll = "result", 0

    def refresh_counts(self):
        self.status, self.detail = "RUNNING", "Refreshing hosts and tunnels"
        self.render()
        results = []
        for args in (["-host", "-list"], ["-tunnel", "-list"]):
            result = self.runner(args)
            self.snapshot.observe(args, result)
            results.append(result)
        failed = next((r for r in results if r.code or r.truncated), None)
        if failed or self.snapshot.hosts is None or self.snapshot.tunnels is None:
            self.status = "ERROR refresh"
            self.detail = "Counts incomplete; open agent list for details"
        else:
            self.status, self.detail = "OK", "Counts refreshed"

    def open_picker(self):
        field = self.action.fields[self.index]
        args = ["-" + field.picker, "-list"]
        self.status, self.detail = "RUNNING", "Loading saved entries"
        self.render()
        result = self.runner(args)
        self.snapshot.observe(args, result)
        if result.code or result.truncated:
            self.status, self.detail = "ERROR picker", "List failed; open agent list for details"
            return
        self.choices = [(line.split()[0], line) for line in result.stdout.splitlines()
                        if line.strip()]
        if not self.choices:
            self.status, self.detail = "READY", "No saved entries"
            return
        self.choice_index = 0
        self.page = "picker"
        self.status, self.detail = "OK", "Select a saved entry"

    def execute(self):
        try:
            args = self.action.command(self.values)
        except ValueError as exc:
            self.status, self.detail = "ERROR input", str(exc)
            return
        self.snapshot.invalidate(args)
        self.status, self.detail = "RUNNING", self.action.title
        self.render()
        if args[0] == "@files":
            from .file_screen import manage
            try:
                path = (Path.cwd() / Path(args[1]).expanduser()) if len(args) == 2 else self.start
                manage(self.screen, path.resolve(strict=True), self.c,
                       (self.accent, self.active, self.normal, self.warning))
                self.status, self.detail = "READY", "Returned from file manager"
            except (OSError, ValueError, RuntimeError) as exc:
                self.status, self.detail = "ERROR files", str(exc)
            return
        if self.action.interactive:
            self.c.def_prog_mode()
            self.c.endwin()
            try:
                result = self.runner(args, interactive=True)
            except KeyboardInterrupt:
                result = Result(130, stderr="Interactive session interrupted")
            finally:
                self.c.reset_prog_mode()
                self.screen.clearok(True)
                self.screen.keypad(True)
        else:
            result = self.runner(args)
        self.set_result(args, result)

    def back(self):
        if self.page == "picker":
            self.page = "form"
        elif self.page == "result":
            self.page = "form"
            self.index = len(self.action.fields)
        elif self.page == "form":
            self.page = "actions"
            self.index = CATALOG[self.category][1].index(self.action)
        elif self.page == "actions":
            self.page = "home"
            self.index = self.category
        else:
            return False
        return True

    def handle(self, key):
        c = self.c
        enter = key in ("\n", "\r", c.KEY_ENTER)
        if key == c.KEY_RESIZE:
            return True
        if self.editing:
            if enter:
                self.values[self.index] = self.buffer
                self.editing = False
            elif key == "\x1b":
                self.editing = False
            elif key in ("\b", "\x7f", c.KEY_BACKSPACE):
                self.buffer = self.buffer[:-1]
            elif key == "\x15":
                self.buffer = ""
            elif isinstance(key, str) and key.isprintable() and len(self.buffer) < 512:
                self.buffer += key
            return True
        if self.confirming:
            if key in ("y", "Y"):
                self.confirming = False
                self.execute()
            elif key in ("n", "N", "\x1b"):
                self.confirming = False
                self.status, self.detail = "READY", "Cancelled; no command executed"
            return True
        if key == "q":
            return False
        if key == "\x1b":
            return self.back()
        h, w = self.screen.getmaxyx()
        if h < 8 or w < 24:
            return True
        if key in ("r", c.KEY_F5) and self.page in ("home", "actions"):
            self.refresh_counts()
            return True
        if self.page == "picker":
            if key in (c.KEY_UP, "k"):
                self.choice_index = (self.choice_index-1) % len(self.choices)
            elif key in (c.KEY_DOWN, "j"):
                self.choice_index = (self.choice_index+1) % len(self.choices)
            elif enter:
                self.values[self.index] = self.choices[self.choice_index][0]
                self.page = "form"
            return True
        if self.page == "form" and key in ("f", c.KEY_F2) and self.index < len(self.action.fields):
            if self.action.fields[self.index].picker:
                self.open_picker()
            return True
        if self.page == "result":
            if key in (c.KEY_UP, "k"):
                self.scroll = max(0, self.scroll-1)
            elif key in (c.KEY_DOWN, "j"):
                self.scroll += 1
            elif key == c.KEY_PPAGE:
                self.scroll = max(0, self.scroll-max(1, h-6))
            elif key == c.KEY_NPAGE:
                self.scroll += max(1, h-6)
            return True
        count = (len(CATALOG) if self.page == "home" else
                 len(CATALOG[self.category][1]) if self.page == "actions" else
                 len(self.action.fields)+1)
        if key in (c.KEY_UP, "k"):
            self.index = (self.index-1) % count
        elif key in (c.KEY_DOWN, "j", "\t"):
            self.index = (self.index+1) % count
        elif self.page == "home" and isinstance(key, str) and key in "123456":
            self.category, self.page, self.index = int(key)-1, "actions", 0
        elif enter:
            if self.page == "home":
                self.category, self.page, self.index = self.index, "actions", 0
            elif self.page == "actions":
                self.action = CATALOG[self.category][1][self.index]
                self.values = [f.default for f in self.action.fields]
                self.page, self.index = "form", 0
            elif self.index < len(self.action.fields):
                self.buffer, self.editing = self.values[self.index], True
            else:
                if self.action.confirm:
                    self.confirming = True
                else:
                    self.execute()
        return True

    def run(self):
        self.screen.keypad(True)
        try:
            self.c.curs_set(0)
        except self.c.error:
            pass
        while True:
            self.render()
            if not self.handle(self.screen.get_wch()):
                return
