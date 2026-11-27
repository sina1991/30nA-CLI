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
from .panels import HELP, FIELD_HELP, layout, suggestions

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
            elif part == "@local":
                value = values[0]
                if not value.strip():
                    raise ValueError("Select Local ID 1 or a local IP")
                args.extend(("-localhost", "-id", "1") if value == "1" else ("-ip", value))
            elif part == "@remote":
                value = values[2]
                if not value.strip():
                    raise ValueError("Select a remote host")
                args.extend(("-remote-id", value) if value.isascii() and value.isdecimal()
                            else ("-remote-ip", value))
            elif part == "@protocol":
                value = values[1].lower()
                if value not in ("tcp", "udp"):
                    raise ValueError("Protocol must be tcp or udp")
                args.append("-" + value)
            else:
                args.append(part)
        return args


def tunnel(mode, persistent=False):
    title = "Persistent Forward" if persistent else mode.capitalize() + " tunnel"
    extra = ("-persistent",) if persistent else ()
    return Action(title,
                  ("-tunnel", "-" + mode, "@local", "-local-port", 1,
                   "@remote", "-remote-port", 3, *extra),
                  (Field("Local host (ID 1)", "1", "local"),
                   Field("Local port", "8080", "local-port"),
                   Field("Registered remote ID" if persistent else "Remote host ID/IP/domain", "", "remote"),
                   Field("Remote port", "443", "remote-port")),
                  confirm=True,
                  hint=("Local listener -> remote loopback service." if mode == "forward"
                        else "Remote initiates SSH; Local listener -> remote loopback service."))


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
     + tuple(Action(f.capitalize(), ("-sys", "-" + f)) for f in SYSTEM) + (Action("Local interface IPs", ("-sys", "-ip")),)),
    ("Host", (
        Action("List numbered hosts", ("-host", "-list", "-ids")),
        Action("Add / update host (SSH onboarding)", ("-host", "-add", "-domain", 0, "-onboard"),
               (Field("IP or domain"),), confirm=True,
               hint="Use local management key; verify the host fingerprint and key-only SSH login."),
        Action("Add / update host (password / key + password)", ("-host", "-add", "-domain", 0, "-onboard", "-password"),
               (Field("IP or domain"),), interactive=True, confirm=True,
               hint="Native password prompt and ssh-copy-id; verify host fingerprint."),
        Action("Connect SSH", ("-host", "-ssh", "-domain", 0),
               (Field("Registered IP or domain", picker="host"),), interactive=True,
               hint="Uses your SSH configuration. Exit SSH to return."),
        Action("Register address only (offline)", ("-host", "-add", "-domain", 0),
               (Field("IP or domain"),)),
        Action("Remove host", ("-host", "-remove", "-domain", 0),
               (Field("IP or domain", picker="host"),), confirm=True),
    )),
    ("Tunnel", (
        Action("List tunnels", ("-tunnel", "-list")),
        tunnel("forward"), tunnel("reverse"),
        Action("Discover external SSH tunnel services", ("-tunnel", "-discover"),
               hint="Read-only inventory across registered hosts; no adoption or stop."),
        *(Action(title, ("-tunnel", flag, "-id", 0),
                 (Field("Tunnel ID", picker="tunnel"),), confirm=True)
          for title, flag in (("Stop tunnel", "-stop"), ("Start managed tunnel", "-start"),
                              ("Restart managed tunnel", "-restart"), ("Delete managed tunnel", "-delete"))),
        tunnel("forward", persistent=True),
    )),
    ("Files", (
        Action("Open current directory", ("@files",)),
        Action("Open directory by path", ("@files", 0), (Field("Directory", "."),)),
    )),
    ("Help", tuple(Action(name, args) for name, args in (
        ("All agents", ("-help",)), ("Calculator help", ("-calc", "-help")),
        ("System help", ("-sys", "-help")), ("Host help", ("-host", "-help")),
        ("Tunnel help", ("-tunnel", "-help")), ("Menu help", ("-menu", "-help")),
        ("Service help", ("-service", "-help")), ("Port help", ("-port", "-help"))))),
    ("Services", tuple(Action(title, ("-service", "-" + op)) for title, op in (
        ("Active services", "active"), ("All loaded services", "list"),
        ("Installed unit files", "installed"), ("30nA worker status", "workers"), ("Managed unit history", "managed")))
     + tuple(Action(op.capitalize() + " service", ("-service", "-" + op, "-unit", 0),
                    (Field("Service unit", picker="unit"),), confirm=op not in ("status", "logs"),
                    hint="Uses system scope; requires existing permissions.")
             for op in ("status", "start", "stop", "restart", "reload", "enable", "disable", "logs"))
     + (Action("Reload systemd manager", ("-service", "-daemon-reload"), confirm=True),)),
    ("Ports", (
        Action("Listening TCP / bound UDP", ("-port", "-list")),
        Action("All TCP/UDP sockets", ("-port", "-all")),
        Action("TCP listeners", ("-port", "-list", "-tcp")),
        Action("UDP bound sockets", ("-port", "-list", "-udp")),
        Action("Port counts", ("-port", "-summary")),
        Action("Inspect port number", ("-port", "-check", 0),
               (Field("Port number", "5555", "listen"),)),
        Action("Emergency release by unit", ("-port", "-force", 0, "@protocol", "-unit", 2),
               (Field("Port number", "5555", "listen"), Field("Protocol", "tcp", "protocol"), Field("Exact owning unit", picker="unit")),
               confirm=True, hint="Inspect port first. Stops entire selected service."),
        Action("Emergency release by PID", ("-port", "-force", 0, "@protocol", "-pid", 2),
               (Field("Port number", "5555", "listen"), Field("Protocol", "tcp", "protocol"), Field("Exact standalone PID")),
               confirm=True, hint="Inspect port first. Terminates the selected process."),
    )),
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
    if args[:2] == ["-port", "-force"]:
        timeout = max(timeout, 60)
    if args[:2] == ["-tunnel", "-discover"]:
        timeout = max(timeout, 180)
    if args[:2] in (["-tunnel", "-reverse"], ["-tunnel", "-stop"]):
        timeout = max(timeout, 360)
    enrollment = args[:2] == ["-host", "-add"] and "-onboard" in args
    if enrollment:
        timeout = max(timeout, 450 if interactive else 180)
    try:
        if interactive and not enrollment:
            return Result(subprocess.run(argv).returncode,
                          "Interactive SSH session ended.")
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            code = subprocess.run(argv, stdin=None if interactive else subprocess.DEVNULL, stdout=out,
                                  stderr=None if interactive else err, timeout=timeout).returncode
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
        self.host_rows = []
        self.numbered_hosts = None
        self.tunnel_rows = []
        self.system = []
        self.local_ips = None
        self.services = None
        self.managed = None
        self.ports = None
        self.port_rows = None
        self.workers = None
        self.overview_time = None

    def invalidate(self, args):
        if args and args[0] == "-port" and "-force" in args:
            self.ports = self.port_rows = self.services = self.managed = self.workers = None
            self.tunnels = self.tunnel_time = None
            self.tunnel_rows = []
        if args and (args[0] == "-tunnel" and "-list" not in args or
                     args[0] == "-service" and args[1] not in ("-list", "-active", "-installed", "-workers", "-managed", "-status", "-logs", "-help")):
            self.ports = self.port_rows = None
        if args and args[0] == "-host" and "-list" not in args:
            self.hosts = self.host_time = None
            self.host_rows = []
            self.numbered_hosts = None
        if args and args[0] == "-tunnel" and "-list" not in args:
            self.hosts = self.host_time = None
            self.host_rows = []
            self.numbered_hosts = None
            self.tunnels = self.tunnel_time = None
            self.tunnel_rows = []
        if args and args[0] == "-service" and args[1] not in ("-list", "-active", "-installed", "-workers", "-managed", "-status", "-logs", "-help"):
            self.services = self.managed = None

    def observe(self, args, result):
        if args == ["-host", "-list", "-ids"]:
            self.hosts = self.host_time = None
            self.numbered_hosts = None
            self.host_rows = []
            if result.code == 0 and not result.truncated:
                rows = [line.split(None, 2) for line in result.stdout.splitlines()]
                if rows and len(rows[0]) == 3 and rows[0][:2] == ["1", "LOCAL"] and all(len(r) == 3 and r[0].isascii() and r[0].isdigit() and int(r[0]) >= 2 and r[1] == "REMOTE" for r in rows[1:]):
                    self.numbered_hosts = [(r[0], r[2]) for r in rows[1:]]
                    self.host_rows = [r[2] for r in rows[1:]]
                    self.hosts = len(self.host_rows)
                    self.host_time = time.strftime("%H:%M:%S")
        elif args == ["-host", "-list"]:
            self.hosts = self.host_time = None
            self.host_rows = []
            self.numbered_hosts = None
            if result.code == 0 and not result.truncated:
                self.host_rows = result.stdout.splitlines()
                self.hosts = len(self.host_rows)
                self.host_time = time.strftime("%H:%M:%S")
        elif args == ["-tunnel", "-list"]:
            self.tunnels = self.tunnel_time = None
            self.tunnel_rows = []
            if result.code == 0 and not result.truncated:
                counts = dict(ready=0, starting=0, failed=0)
                for line in result.stdout.splitlines():
                    states = [word[6:] for word in line.split() if word.startswith("state=")]
                    if len(states) != 1 or states[0] not in counts:
                        return
                    counts[states[0]] += 1
                self.tunnels = counts
                self.tunnel_rows = result.stdout.splitlines()
                self.tunnel_time = time.strftime("%H:%M:%S")
        elif args == ["-port", "-list"]:
            self.ports = self.port_rows = None
            if result.code == 0 and not result.truncated:
                rows = result.stdout.splitlines()
                counts = {"tcp": set(), "udp": set()}
                for line in rows:
                    words = line.split()
                    if len(words) < 6 or words[0] not in counts or not words[3].startswith("port="):
                        return
                    try:
                        number = int(words[3][5:])
                    except ValueError:
                        return
                    if not 1 <= number <= 65535:
                        return
                    counts[words[0]].add(number)
                self.port_rows = rows
                self.ports = {proto: len(numbers) for proto, numbers in counts.items()}
        elif args == ["-service", "-active"]:
            self.services = None
            if result.code == 0 and not result.truncated:
                self.services = [line.split()[0] for line in result.stdout.splitlines()
                                 if line.split() and line.split()[0].endswith(".service")]
        elif args == ["-service", "-managed"]:
            self.managed = None if result.code or result.truncated else set(result.stdout.splitlines())
        elif args == ["-service", "-workers"]:
            self.workers = None
            if result.code == 0 and not result.truncated:
                rows = dict(line.split() for line in result.stdout.splitlines() if len(line.split()) == 2)
                if set(rows) == {"host", "tunnel", "supervisor", "port"}:
                    self.workers = rows
        elif args == ["-sys", "-ip"]:
            self.local_ips = None
            if result.code == 0 and not result.truncated:
                self.local_ips = [] if result.stdout.strip() == "none" else result.stdout.split()
        elif args == ["-sys", *("-" + f for f in SYSTEM)]:
            self.system = list(zip(SYSTEM, result.stdout.splitlines())) if result.code == 0 and not result.truncated else []

    def summary(self, compact=False):
        hosts = "?" if self.hosts is None else str(self.hosts)
        t = self.tunnels
        tunnels = "?/?/?" if t is None else f'{t["ready"]}/{t["starting"]}/{t["failed"]}'
        p = self.ports
        ports = "?/?" if p is None else f'{p["tcp"]}/{p["udp"]}'
        if compact:
            return f"H {hosts} | R/S/F {tunnels} | P {ports}"
        ht, tt = self.host_time or "--", self.tunnel_time or "--"
        return f"Hosts {hosts} | Tunnels R/S/F {tunnels} | Ports T/U {ports} | H {ht} T {tt}"


class Dashboard:
    def __init__(self, screen, c, styles, start, runner=invoke):
        self.screen, self.c = screen, c
        self.accent, self.active, self.normal, self.warning = styles
        self.status_styles = {"READY": self.active, "RUNNING": self.warning,
                              "OK": self.active, "ERROR": self.warning}
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
        self.side_scroll = 0
        self.show_system_services = False
        self.row_styles = {"local": self.accent, "remote": self.accent, "ready": self.active,
                           "starting": self.warning, "failed": self.warning}

    def draw(self, y, x, value, style=0, fill=False, limit=None):
        h, w = self.screen.getmaxyx()
        width = w - x - 1
        if limit is not None:
            width = min(width, limit)
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
            return "Up/Down | Right/Enter select | Left cancel"
        if self.page in ("result", "overview"):
            return "Up/Down scroll | Left back | PgUp/PgDn | q quit"
        if self.page == "form":
            return "Up/Down | Right/Enter edit/run | f pick | Left back"
        return "Up/Down | Right open | Left back | h services | r refresh | v view"

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
        region = layout(h, w)
        category, actions = CATALOG[self.category]
        focused = CATALOG[self.index][0] if self.page == "home" else category
        context = HELP[focused]
        if self.page == "actions":
            item = actions[self.index]
            context = item.hint or (item.title + ": " + " ".join(str(a) for a in item.args if isinstance(a, str) and not a.startswith("@")))
        elif self.page in ("form", "picker") and self.index < len(self.action.fields):
            field = self.action.fields[self.index]
            context = FIELD_HELP.get(field.picker, self.action.hint or field.name + ": Enter to edit.")
        elif self.page == "result":
            context = "Scroll output with j/k. Esc returns to the form."
        sysinfo = dict(self.snapshot.system)
        if region.expanded:
            half = w//2
            self.draw(1, 1, "SYSTEM / " + sysinfo.get("hostname", "?"), self.accent, limit=half-2)
            self.draw(1, half+1, "CONTEXT HELP / " + focused, self.accent, limit=w-half-2)
            info = ["IP " + self.local_ip_text(), "OS " + sysinfo.get("os", "?"),
                    "Kernel " + sysinfo.get("kernel", "?") + " | Up " + sysinfo.get("uptime", "?"),
                    "CPU " + sysinfo.get("cpu", "?"),
                    "RAM " + sysinfo.get("ram", "?"),
                    "Disk " + sysinfo.get("disk", "?")]
            for i, line in enumerate(info, 2):
                self.draw(i, 1, line, limit=half-2)
            for i, line in enumerate(textwrap.wrap(context, max(1, w-half-3))[:5], 2):
                self.draw(i, half+1, line, limit=w-half-2)
            for y in range(1, region.top-1):
                self.draw(y, half, "|", self.accent, limit=1)
            self.draw(region.top-1, 1, "AGENTS", self.accent, limit=region.left-2)
            self.draw(region.top-1, region.right, "OBSERVED STATUS", self.accent, limit=w-region.right-1)
            focus_index = self.index if self.page == "home" else self.category
            first_agent = max(0, focus_index-region.body+1)
            for i, (name, _) in enumerate(CATALOG[first_agent:first_agent+region.body], first_agent):
                self.draw(region.top+i-first_agent, 1, f"{i+1}. {name}",
                          self.active if name == focused else self.normal,
                          fill=name == focused, limit=region.left-2)
            side = self.side_lines()
            self.side_scroll = min(self.side_scroll, max(0, len(side)-region.body))
            for i, line in enumerate(side[self.side_scroll:self.side_scroll+region.body]):
                self.draw(region.top+i, region.right, line, self.line_style(line), limit=w-region.right-1)
            for y in range(region.top, h-4):
                self.draw(y, region.left-1, "|", self.accent, limit=1)
                self.draw(y, region.right-1, "|", self.accent, limit=1)
        elif region.top >= 4:
            self.draw(1, 1, sysinfo.get("hostname", "?") + " | IP " + self.local_ip_text(), self.accent)
            self.draw(2, 1, "HELP: " + context, self.normal)
        title = {"home": "AGENTS" if not region.expanded else focused.upper() + " / OPTIONS",
                 "actions": category.upper(), "form": category + " / " + (self.action.title if self.action else ""),
                 "result": "COMMAND OUTPUT", "picker": "SELECT ENTRY", "overview": "SYSTEM / SERVICES / WORKERS"}[self.page]
        self.draw(region.top-1, region.left, title, self.accent, limit=region.width)
        body = region.body
        if self.page in ("result", "overview"):
            lines = []
            for line in (self.output if self.page == "result" else self.overview_lines()):
                lines.extend((part, self.line_style(line)) for part in (textwrap.wrap(label(line), max(1, region.width-1),
                                           replace_whitespace=False, drop_whitespace=False) or [""]))
            self.scroll = min(self.scroll, max(0, len(lines)-body))
            for i, (line, style) in enumerate(lines[self.scroll:self.scroll+body]):
                self.draw(region.top+i, region.left, line, style, limit=region.width)
        elif self.page == "picker":
            first = max(0, self.choice_index-body+1)
            for i, (_, desc) in enumerate(self.choices[first:first+body], first):
                selected = i == self.choice_index
                self.draw(region.top+i-first, region.left, ("> " if selected else "  ") + desc,
                          self.active if selected else self.line_style(desc), fill=selected, limit=region.width)
        else:
            if self.page == "home":
                rows = ([a.title for a in CATALOG[self.index][1]] if region.expanded else
                        [f"{i+1}. {name}" for i, (name, _) in enumerate(CATALOG)])
            elif self.page == "actions":
                rows = [a.title for a in actions]
            else:
                rows = []
                for i, (f, v) in enumerate(zip(self.action.fields, self.values)):
                    if self.editing and i == self.index:
                        rows.append("Edit: " + self.buffer[-max(1, region.width-10):] + "_")
                    else:
                        rows.append(f"{f.name}: {v}" + (" [f]" if f.picker else ""))
                rows.append("[ RUN COMMAND ]")
                if self.action.hint:
                    rows.append(self.action.hint)
                try:
                    cmd = "30na " + shlex.join(self.action.command(self.values))
                    if self.action.args[0] != "@files":
                        rows.extend(textwrap.wrap(cmd, max(1, region.width-3)))
                except ValueError:
                    pass
            preview = self.page == "home" and region.expanded
            first = 0 if preview else max(0, self.index-body+1)
            for i, line in enumerate(rows[first:first+body], first):
                selected = not preview and i == self.index
                self.draw(region.top+i-first, region.left, ("> " if selected else "  ") + line,
                          self.active if selected else self.normal, fill=selected, limit=region.width)
        if self.confirming:
            prompt = self.action.title
            if self.action.args[:2] in (("-tunnel", "-forward"), ("-tunnel", "-reverse")) and self.values[0] != "1":
                prompt = "Bind listener on " + self.values[0] + " (review exposure)"
            self.draw(h-4, 0, " CONFIRM: " + prompt + "? ", self.warning, True)
        else:
            self.draw(h-4, 0, self.snapshot.summary(compact=w < 74),
                      self.warning if self.snapshot.tunnels and self.snapshot.tunnels["failed"]
                      else self.accent, True)
        self.draw(h-3, 0, " STATUS | " + self.status + " | " + self.detail,
                  self.status_styles.get(self.status.split()[0], self.active), True)
        keys = self.keys()
        legend = " R/S/F: ready/starting/failed | T/U: TCP/UDP port numbers | ? unknown"
        if w < 55:
            if self.editing:
                keys = "Enter save | Esc cancel"
            elif self.confirming:
                keys = "y confirm | n cancel"
            elif self.page in ("result", "overview"):
                keys = "j/k scroll | Esc back"
            elif self.page == "picker":
                keys = "j/k | Enter select | Esc"
            elif self.page == "form":
                keys = "j/k Enter f:pick Esc"
            else:
                keys = "j/k Enter r v:view q"
            legend = "H:hosts P:TCP/UDP ports"
        self.draw(h-2, 0, keys, self.accent, True)
        self.draw(h-1, 0, (" h: SYSTEM UNITS " + ("SHOWN" if self.show_system_services else "HIDDEN") + " | " + legend + " | [ ] panel"), self.normal, True)
        s.refresh()

    def set_result(self, args, result):
        self.snapshot.observe(args, result)
        if args and args[0] in ("-host", "-tunnel"):
            self.snapshot.workers = None
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
        if args and args[0] == "-tunnel" and "host_key_failed" in result.stderr + result.stdout:
            self.output.extend(["", "HOST KEY: verify the SSH server fingerprint using a trusted source.",
                                "Open Host > Connect SSH for the registered endpoint (same user/config).",
                                "Do not disable host-key verification or blindly remove known_hosts entries.",
                                "Retry the tunnel after verified noninteractive SSH works."])
        self.page, self.scroll = "result", 0

    def line_style(self, line):
        words = line.split()
        if len(words) > 1 and words[0].isdigit():
            if words[1] == "LOCAL":
                return self.row_styles["local"]
            if words[1] == "REMOTE":
                return self.row_styles["remote"]
        if line.startswith("LOCAL #"):
            return self.row_styles["local"]
        if line.startswith("REMOTE #"):
            return self.row_styles["remote"]
        for state in ("ready", "starting", "failed"):
            if line.startswith(("F " + state.upper(), "R " + state.upper())) or "state=" + state in words:
                return self.row_styles[state]
        return self.normal

    def side_lines(self):
        snap = self.snapshot
        rows = ["LOCAL #1 " + self.local_ip_text(), "REMOTE HOSTS: " + ("?" if snap.hosts is None else str(snap.hosts))]
        rows += [f"REMOTE #{i} {ip}" for i, ip in (snap.numbered_hosts or [])]
        if snap.hosts == 0:
            rows.append("None")
        rows += ["TUNNELS R/S/F"]
        if snap.tunnels is None:
            rows += ["Unknown"]
        else:
            rows += [f'{snap.tunnels["ready"]}/{snap.tunnels["starting"]}/{snap.tunnels["failed"]}']
            for line in snap.tunnel_rows:
                words = line.split()
                if len(words) >= 5:
                    state = next((v[6:] for v in words if v.startswith("state=")), "?")
                    remote = next((v[10:] for v in words if v.startswith("remote_id=")), "?")
                    local_ep = next((v[6:] for v in words if v.startswith("local=")), "")
                    remote_ep = next((v[7:] for v in words if v.startswith("remote=")), "")
                    direction = "F" if words[1] == "forward" else "R"
                    if local_ep and remote_ep:
                        ports = local_ep.rsplit(":", 1)[-1] + ("<" if "legacy_topology=yes" in words else ">") + remote_ep.rsplit(":", 1)[-1]
                    else:
                        ports = ":" + words[3]
                    rows.append(f"{direction} {state.upper()} #{remote} {ports}")
        rows += ["30nA WORKERS"]
        rows += ([f"{name}: {snap.workers[name]}" for name in ("supervisor", "port", "host", "tunnel")]
                 if snap.workers else ["Unknown"])
        rows += ["MANAGED ACTIVE UNITS"]
        if snap.services is None or snap.managed is None:
            rows += ["Unknown"]
        else:
            rows += [unit for unit in snap.services if unit in snap.managed] or ["None"]
        rows += ["PORTS TCP/UDP"]
        if snap.ports is None:
            rows += ["Unknown"]
        else:
            rows += [f'{snap.ports["tcp"]}/{snap.ports["udp"]} distinct ports']
            for line in snap.port_rows:
                words = line.split()
                rows.append(f"{words[0]} {words[3][5:]} {words[4][5:]}")
        if self.show_system_services:
            rows += ["ALL ACTIVE SYSTEM UNITS"]
            rows += snap.services if snap.services else (["None"] if snap.services == [] else ["Unknown"])
        else:
            rows += ["SYSTEM UNITS HIDDEN (h)"]
        return rows

    def local_ip_text(self):
        ips = self.snapshot.local_ips
        return "?" if ips is None else " ".join(ips) if ips else "none"

    def overview_lines(self):
        return ["SYSTEM", "Local IPs: " + self.local_ip_text(), *[f"{k}: {v}" for k, v in self.snapshot.system],
                "", *self.side_lines(), "", "Last overview: " + (self.snapshot.overview_time or "unknown"),
                "Worker states are last observed; port reported is not a liveness probe.",
                "Registered host does not mean connected. Use agent lists for full details."]

    def refresh_overview(self):
        for args in (["-sys", *("-" + f for f in SYSTEM)], ["-sys", "-ip"], ["-service", "-active"], ["-service", "-managed"], ["-service", "-workers"], ["-port", "-list"]):
            self.snapshot.observe(args, self.runner(args))
        self.snapshot.overview_time = time.strftime("%H:%M:%S")
        self.side_scroll = 0

    def refresh_counts(self):
        self.status, self.detail = "RUNNING", "Refreshing dashboard"
        self.render()
        results = []
        for args in (["-host", "-list", "-ids"], ["-tunnel", "-list"]):
            result = self.runner(args)
            self.snapshot.observe(args, result)
            results.append(result)
        self.refresh_overview()
        failed = next((r for r in results if r.code or r.truncated), None)
        if failed or self.snapshot.hosts is None or self.snapshot.tunnels is None:
            self.status = "ERROR refresh"
            self.detail = "Counts incomplete; open agent list for details"
        else:
            self.status, self.detail = "OK", ("Counts refreshed; overview incomplete" if self.snapshot.services is None or self.snapshot.managed is None or self.snapshot.workers is None or self.snapshot.ports is None else "Counts refreshed")

    def open_picker(self):
        field = self.action.fields[self.index]
        kind = field.picker
        self.status, self.detail = "RUNNING", "Loading choices"
        self.render()
        if kind in ("host", "remote"):
            args = ["-host", "-list", "-ids"]
            result = self.runner(args)
            self.snapshot.observe(args, result)
            self.choices = [(i if kind == "remote" else ip, f"{i} REMOTE {ip}")
                            for i, ip in (self.snapshot.numbered_hosts or [])]
            self.choices.append((None, "[Enter IP or domain]"))
        elif kind == "local":
            args = ["-sys", "-ip"]
            self.snapshot.observe(args, self.runner(args))
            self.choices = [("1", "1 LOCAL (loopback default)")]
            self.choices += [(ip, "1 LOCAL " + ip) for ip in self.snapshot.local_ips or []]
        elif kind in ("tunnel", "unit"):
            commands = ([["-service", "-installed"], ["-service", "-list"]] if kind == "unit"
                        else [["-" + kind, "-list"]])
            rows = {}
            for args in commands:
                result = self.runner(args)
                self.snapshot.observe(args, result)
                if result.code or result.truncated:
                    continue
                for line in result.stdout.splitlines():
                    if not line.strip():
                        continue
                    key = line.split()[0]
                    if kind == "unit" and not key.endswith(".service"):
                        continue
                    rows[key] = line
            self.choices = list(rows.items())
            if kind != "tunnel":
                self.choices.append((None, "[Enter custom value]"))
            elif not self.choices:
                self.choices.append((None, "[Enter tunnel ID manually]"))
        else:
            self.choices = suggestions(kind, self.values[self.index])
        self.choice_index = next((i for i, (value, _) in enumerate(self.choices) if value == self.values[self.index]), 0)
        self.page = "picker"
        self.status, self.detail = "OK", "Select a value or enter custom"

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
        if result.code == 0:
            self.refresh_after_action(args)

    def refresh_after_action(self, args):
        """Refresh affected snapshots after successful explicit mutations."""
        commands = []
        if args[:2] in (["-tunnel", "-forward"], ["-tunnel", "-reverse"], ["-tunnel", "-stop"]):
            commands = [["-host", "-list", "-ids"], ["-tunnel", "-list"],
                        ["-service", "-workers"], ["-port", "-list"]]
        elif args[:2] in (["-host", "-add"], ["-host", "-remove"]):
            commands = [["-host", "-list", "-ids"], ["-service", "-workers"]]
        elif args[0] == "-service" and args[1] not in ("-list", "-active", "-installed", "-workers", "-managed", "-status", "-logs", "-help"):
            commands = [["-service", "-active"], ["-service", "-managed"], ["-port", "-list"]]
        elif args[:2] == ["-port", "-force"]:
            commands = [["-port", "-list"], ["-service", "-active"], ["-service", "-managed"], ["-service", "-workers"]]
        if commands:
            self.render()
            for command in commands:
                self.snapshot.observe(command, self.runner(command))

    def back(self):
        if self.page == "overview":
            self.page, self.index = "home", self.category
        elif self.page == "picker":
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
        enter = key in ("\n", "\r", c.KEY_ENTER) or (not self.editing and key == c.KEY_RIGHT)
        if key == c.KEY_RESIZE:
            return True
        if self.editing:
            if enter:
                self.values[self.index] = self.buffer
                self.editing = False
            elif key in ("\x1b", c.KEY_LEFT):
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
            elif key in ("n", "N", "\x1b", c.KEY_LEFT):
                self.confirming = False
                self.status, self.detail = "READY", "Cancelled; no command executed"
            return True
        if key == "q":
            return False
        if key in ("\x1b", c.KEY_LEFT):
            return True if self.page == "home" and key == c.KEY_LEFT else self.back()
        if key == "h":
            self.show_system_services = not self.show_system_services
            self.side_scroll = 0
            return True
        h, w = self.screen.getmaxyx()
        if h < 8 or w < 24:
            return True
        if key in ("[", "]"):
            self.side_scroll = max(0, self.side_scroll + (1 if key == "]" else -1))
            return True
        if key == "v" and self.page in ("home", "actions"):
            self.page, self.scroll = "overview", 0
            return True
        if key in ("r", c.KEY_F5) and self.page in ("home", "actions", "overview"):
            self.refresh_counts()
            return True
        if self.page == "picker":
            if key in (c.KEY_UP, "k"):
                self.choice_index = (self.choice_index-1) % len(self.choices)
            elif key in (c.KEY_DOWN, "j"):
                self.choice_index = (self.choice_index+1) % len(self.choices)
            elif enter:
                chosen = self.choices[self.choice_index][0]
                self.page = "form"
                if chosen is None:
                    self.buffer, self.editing = self.values[self.index], True
                else:
                    self.values[self.index] = chosen
            return True
        if self.page == "form" and key in ("f", c.KEY_F2) and self.index < len(self.action.fields):
            if self.action.fields[self.index].picker:
                self.open_picker()
            return True
        if self.page in ("result", "overview"):
            if key in (c.KEY_UP, "k"):
                self.scroll = max(0, self.scroll-1)
            elif key in (c.KEY_DOWN, "j"):
                self.scroll += 1
            elif key == c.KEY_PPAGE:
                self.scroll = max(0, self.scroll-layout(h, w).body)
            elif key == c.KEY_NPAGE:
                self.scroll += layout(h, w).body
            return True
        count = (len(CATALOG) if self.page == "home" else
                 len(CATALOG[self.category][1]) if self.page == "actions" else
                 len(self.action.fields)+1)
        if key in (c.KEY_UP, "k"):
            self.index = (self.index-1) % count
        elif key in (c.KEY_DOWN, "j", "\t"):
            self.index = (self.index+1) % count
        elif self.page == "home" and isinstance(key, str) and key in "12345678":
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

    def init_status_colors(self):
        c = self.c
        if not c.has_colors() or c.COLOR_PAIRS < 8:
            return
        for number, state, fg, bg in (
                (5, "RUNNING", c.COLOR_BLACK, c.COLOR_YELLOW),
                (6, "OK", c.COLOR_BLACK, c.COLOR_GREEN),
                (7, "ERROR", c.COLOR_WHITE, c.COLOR_RED)):
            try:
                c.init_pair(number, fg, bg)
                self.status_styles[state] = c.color_pair(number) | c.A_BOLD
            except c.error:
                pass

    def init_row_colors(self):
        c = self.c
        if not c.has_colors() or c.COLOR_PAIRS < 13:
            return
        for number, key, fg in ((8, "local", c.COLOR_CYAN), (9, "remote", c.COLOR_MAGENTA),
                                (10, "ready", c.COLOR_GREEN), (11, "starting", c.COLOR_YELLOW),
                                (12, "failed", c.COLOR_RED)):
            try:
                c.init_pair(number, fg, -1)
                self.row_styles[key] = c.color_pair(number) | c.A_BOLD
            except c.error:
                pass

    def run(self):
        self.screen.keypad(True)
        self.init_status_colors()
        self.init_row_colors()
        try:
            self.c.curs_set(0)
        except self.c.error:
            pass
        self.render()
        self.refresh_overview()
        # Do not bootstrap stopped runtime workers merely to draw the dashboard.
        for name in ("host", "tunnel"):
            if self.snapshot.workers and self.snapshot.workers.get(name) == "ready":
                args = ["-host", "-list", "-ids"] if name == "host" else ["-tunnel", "-list"]
                self.snapshot.observe(args, self.runner(args))
        while True:
            self.render()
            if not self.handle(self.screen.get_wch()):
                return
