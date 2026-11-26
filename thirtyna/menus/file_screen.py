"""Two-pane keyboard file manager."""
import datetime
import stat
from pathlib import Path

from .text_view import edit, preview
from .files import named, relocate, remove, transfer
from .model import label


class Pane:
    def __init__(self, path):
        self.filter = ""
        self.index = 0
        self.open(path)

    def open(self, path):
        path = path.resolve(strict=True)
        entries = sorted(path.iterdir(), key=lambda p: p.name.casefold())
        self.path = path
        self.entries = entries
        self.index = 0
        self.filter = ""

    def visible(self):
        return [p for p in self.entries if self.filter.casefold() in p.name.casefold()]


def manage(screen, start, c, styles):
    accent, active, normal, warning = styles
    panes = [Pane(start), Pane(start)]
    side = 0
    show_preview = True
    message = "Tab switches destination pane   ·   ? shows all shortcuts"
    help_open = False

    def draw(y, x, value, limit, style=0):
        h, w = screen.getmaxyx()
        size = min(limit, w - x - 1)
        if size > 0 and 0 <= y < h:
            try:
                screen.addnstr(y, x, value, size, style)
            except c.error:
                pass

    def ask(prompt):
        value = ""
        while True:
            h, w = screen.getmaxyx()
            screen.move(h-1, 0)
            screen.clrtoeol()
            draw(h-1, 0, (prompt + " " + value + "▏")[-max(1,w-2):], w, active)
            screen.refresh()
            key = screen.get_wch()
            if key == "\x1b":
                return None
            if key in ("\n", "\r", c.KEY_ENTER):
                return value
            if key in ("\b", "\x7f", c.KEY_BACKSPACE):
                value = value[:-1]
            elif isinstance(key, str) and key.isprintable():
                value += key

    while True:
        h, w = screen.getmaxyx()
        rows = max(1, h-6)
        pane, other = panes[side], panes[1-side]
        screen.erase()
        draw(0, 0, " 30nA   /   FILE MANAGER ", w, accent)
        wide = w >= 80
        columns = [0, 1] if wide and not show_preview else [side]
        width = w//2 if wide else w
        for col in columns:
            panel = panes[col]
            x = col*width if wide and not show_preview else 0
            items = panel.visible()
            panel.index = max(0, min(panel.index, len(items)-1))
            title = ("ACTIVE" if col == side else "TARGET") + "  " + label(panel.path)
            draw(1, x, title, width-1, accent if col == side else normal)
            draw(2, x, f" NAME   ·   {len(items)} entries" + ("   /" + label(panel.filter) if panel.filter else ""), width-1, normal)
            top = max(0, panel.index-rows+1)
            for row, path in enumerate(items[top:top+rows]):
                tag = "@" if path.is_symlink() else "/" if path.is_dir() else ""
                selected = row+top == panel.index and col == side
                draw(row+3, x, ((" › " if selected else "   ")+label(path.name)+tag).ljust(width),
                     width-1, active if selected else normal)
            if not items:
                draw(3, x, "  No entries", width-1, normal)
        items = pane.visible()
        item = items[pane.index] if items else None
        if wide and show_preview:
            draw(1, width, "PREVIEW", width, accent)
            draw(2, width, label(item.name) if item else "", width, normal)
            for row, text in enumerate(preview(item)[:rows]):
                draw(3 + row, width, text, width, normal)
        detail = ""
        if item:
            try:
                info = item.lstat()
                stamp = datetime.datetime.fromtimestamp(info.st_mtime).strftime("%Y-%m-%d %H:%M")
                detail = f"{stat.filemode(info.st_mode)}   {info.st_size:,} bytes   {stamp}"
            except (OSError, ValueError, OverflowError):
                detail = "Metadata unavailable"
        draw(h-3, 0, detail, w, accent)
        draw(h-2, 0, label(message), w, warning)
        draw(h-1, 0, "p Preview   Enter Edit   Tab Pane   c Copy   m Move   r Rename   n File   d Folder   ? Help", w, normal)
        if help_open:
            screen.erase()
            for y, text in enumerate(["30nA / Keyboard shortcuts", "↑ ↓ / PgUp PgDn / Home End   Select",
                                      "Enter / →   Open directory     ← / Backspace   Parent",
                                      "p   Toggle preview/target      Enter on text: edit in nano",
                                      "Tab   Switch active pane      g   Go to path",
                                      "/   Filter names              Ctrl+L   Refresh",
                                      "c / m   Copy / move to other pane (prompts for name)",
                                      "r   Rename     n   New file     d   New directory",
                                      "x   Delete file, link or empty directory (confirmation)",
                                      "Esc   Clear filter / back     q   Exit manager",
                                      "Press any key to return"]):
                draw(y, 0, text, w, accent if y == 0 else normal)
            screen.refresh()
            screen.get_wch()
            help_open = False
            continue
        screen.refresh()
        key = screen.get_wch()
        try:
            if key == "q":
                return "quit"
            if key == "\x1b":
                if pane.filter:
                    pane.filter = ""
                else:
                    return "back"
            elif key == "p":
                show_preview = not show_preview
            elif key == "\t":
                show_preview = False
                side = 1-side
                message = "Destination: " + str(pane.path)
            elif key == "?":
                help_open = True
            elif key in (c.KEY_UP, c.KEY_DOWN, c.KEY_PPAGE, c.KEY_NPAGE, c.KEY_HOME, c.KEY_END):
                pane.index = {c.KEY_UP:pane.index-1, c.KEY_DOWN:pane.index+1,
                              c.KEY_PPAGE:pane.index-rows, c.KEY_NPAGE:pane.index+rows,
                              c.KEY_HOME:0, c.KEY_END:len(items)-1}[key]
            elif key in ("\n", "\r", c.KEY_ENTER, c.KEY_RIGHT) and item:
                if item.is_dir():
                    pane.open(item)
                elif key != c.KEY_RIGHT:
                    edit(screen, c, item)
                    message = "Returned from editor"
            elif key in (c.KEY_LEFT, c.KEY_BACKSPACE, "\x7f", "\b"):
                previous = pane.path
                pane.open(previous.parent)
                if previous in pane.entries:
                    pane.index = pane.entries.index(previous)
            elif key == "g":
                dest = ask("Open path (Esc cancels):")
                if dest:
                    pane.open(pane.path / Path(dest).expanduser())
            elif key == "/":
                term = ask("Filter (empty clears):")
                if term is not None:
                    pane.filter, pane.index = term, 0
            elif key == "\x0c":
                pane.open(pane.path)
            elif key in ("c", "m", "r", "n", "d", "x"):
                if key in ("c", "m", "r", "x") and not item:
                    continue
                if key in ("c", "m"):
                    action = "Copy" if key == "c" else "Move"
                    dest = ask(f"{action} {label(item.name)} to {label(other.path)} / [Enter keeps name]:")
                    if dest is None:
                        continue
                    transfer(item, named(other.path, dest or item.name), move=key == "m")
                elif key == "x":
                    if ask(f"Delete {label(item)}? Type DELETE:") != "DELETE":
                        continue
                    remove(item)
                else:
                    prompt = {"r": "Rename to:", "n": "New file:", "d": "New directory:"}
                    dest = ask(prompt[key])
                    if dest is None:
                        continue
                    target = named(pane.path, dest)
                    if key == "r":
                        relocate(item, target)
                    elif key == "d":
                        target.mkdir()
                    else:
                        target.touch(exist_ok=False)
                message = "Done"
                for panel in panes:
                    pos, term = panel.index, panel.filter
                    panel.open(panel.path)
                    panel.index, panel.filter = pos, term
        except (OSError, ValueError, RuntimeError) as exc:
            message = str(exc)
