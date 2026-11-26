"""Keyboard-driven renderer shared by registered menu pages."""
import sys

from .file_screen import manage
from .model import Directory


def palette(c):
    styles = [c.A_BOLD, c.A_REVERSE | c.A_BOLD, c.A_DIM, c.A_BOLD]
    if c.has_colors() and c.COLOR_PAIRS >= 5:
        try:
            c.use_default_colors()
            for number, (fg, bg) in enumerate([
                (c.COLOR_CYAN, -1), (c.COLOR_BLACK, c.COLOR_CYAN),
                (c.COLOR_WHITE, -1), (c.COLOR_YELLOW, -1)
            ], 1):
                c.init_pair(number, fg, bg)
            styles = [c.color_pair(1) | c.A_BOLD, c.color_pair(2) | c.A_BOLD,
                      c.color_pair(3), c.color_pair(4) | c.A_BOLD]
        except c.error:
            pass
    return styles


def browse(screen, session, c):
    screen.keypad(True)
    try:
        c.curs_set(0)
    except c.error:
        pass
    accent, active, normal, warning = palette(c)
    index = top = 0
    query = ""
    searching = False
    while not session.done:
        if isinstance(session.page, Directory):
            if manage(screen, session.page.path, c, (accent, active, normal, warning)) == "quit":
                return
            session.back()
            continue
        height, width = screen.getmaxyx()
        compact = height < 12
        first = 2 if compact else 4
        rows = max(1, height - first - 2)
        items = [item for item in session.items if query.casefold() in item.title.casefold()]
        index = min(index, max(0, len(items) - 1))
        top = max(0, min(top, index))
        top = max(top, index - rows + 1)
        screen.erase()

        def draw(y, x, value, style=0):
            if 0 <= y < height and x < width - 1:
                try:
                    screen.addnstr(y, x, value, width - x - 1, style)
                except c.error:
                    pass  # Resize and double-width characters can reach the edge.

        draw(0, 0, " 30nA  /  Navigator ", accent)
        path_width = max(2, width - 4)
        title = session.title
        draw(1, 2, title if len(title) <= path_width else "…" + title[1-path_width:], normal)
        if not compact:
            draw(3, 2, "NAME", accent)
        for pos in range(top, min(len(items), top + rows)):
            selected = pos == index
            text = ("  › " if selected else "    ") + items[pos].title
            draw(first + pos - top, 0, text.ljust(width), active if selected else normal)
        if not items:
            draw(first, 2, "No matches" if query else "Empty directory", normal)
        count = f"{index + 1 if items else 0}/{len(items)}"
        status = f"Filter: {query}▏" if searching else (f"Filter: {query}   " if query else "") + count
        draw(height - 2, 1, session.error or status, warning if session.error else accent)
        keys = "Enter apply   Esc clear" if searching else "↑↓ Move  Enter Open  / Find  ← Parent  Esc Back  q Quit"
        draw(height - 1, 1, keys, normal)
        screen.refresh()
        key = screen.get_wch()
        if key == c.KEY_RESIZE:
            continue
        if searching:
            if key == "\x1b":
                query, searching = "", False
            elif key in ("\n", "\r", c.KEY_ENTER):
                searching = False
            elif key in ("\b", "\x7f", c.KEY_BACKSPACE):
                query = query[:-1]
            elif isinstance(key, str) and key.isprintable():
                query += key
            index = top = 0
            continue
        if key == "q":
            return
        if key == "/":
            searching = True
            session.error = ""
        elif key == "\x1b":
            if query:
                query = ""
            else:
                session.back()
            index = top = 0
        elif key in (c.KEY_LEFT, c.KEY_BACKSPACE, "\x7f", "\b"):
            parent = next((item for item in session.items if item.title == ".."), None)
            if parent:
                session.select(parent)
            query, index, top = "", 0, 0
        elif key in (c.KEY_UP, c.KEY_DOWN, c.KEY_PPAGE, c.KEY_NPAGE, c.KEY_HOME, c.KEY_END):
            moves = {c.KEY_UP: index - 1, c.KEY_DOWN: index + 1,
                     c.KEY_PPAGE: index - rows, c.KEY_NPAGE: index + rows,
                     c.KEY_HOME: 0, c.KEY_END: len(items) - 1}
            index = max(0, min(len(items) - 1, moves[key]))
        elif key in ("\n", "\r", c.KEY_ENTER, c.KEY_RIGHT) and items:
            session.select(items[index])
            if not session.error:
                query, index, top = "", 0, 0


def show(session):
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise RuntimeError("The terminal menu requires an interactive terminal.")
    try:
        import curses
    except ImportError as exc:
        raise RuntimeError("Install Python with curses support for -tui.") from exc
    try:
        curses.wrapper(browse, session, curses)
    except curses.error as exc:
        raise RuntimeError("Cannot initialize this terminal for curses.") from exc
