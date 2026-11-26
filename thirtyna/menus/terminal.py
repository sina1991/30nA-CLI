import sys


def show(session):
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise RuntimeError("The arrow-key menu requires an interactive terminal.")
    try:
        import curses
    except ImportError as exc:
        raise RuntimeError("This Python installation needs curses for -tui.") from exc

    def browse(screen):
        screen.keypad(True)
        index = 0
        while not session.done:
            height, width = screen.getmaxyx()
            items = session.items
            rows = max(1, height - 3)
            start = max(0, index - rows + 1)
            screen.erase()

            def line(row, value, style=0):
                if row < height and width > 1:
                    try:
                        screen.addnstr(row, 0, value, width - 1, style)
                    except curses.error:
                        pass  # A resize or wide character can clip the final cell.

            line(0, session.title, curses.A_BOLD)
            for offset, item in enumerate(items[start:start + rows], start):
                line(offset - start + 1, item.title,
                     curses.A_REVERSE if offset == index else 0)
            line(max(0, height - 2), session.error)
            line(height - 1, "Arrows: move  Enter: open  Esc: back  q: quit")
            key = screen.getch()
            if key == ord("q"):
                return
            if key in (27, curses.KEY_BACKSPACE):
                session.back()
                index = 0
            elif key == curses.KEY_UP:
                index = max(0, index - 1)
            elif key == curses.KEY_DOWN:
                index = max(0, min(len(items) - 1, index + 1))
            elif key in (10, 13, curses.KEY_ENTER) and items:
                session.select(items[index])
                index = 0
    try:
        curses.wrapper(browse)
    except curses.error as exc:
        raise RuntimeError("Cannot initialize this terminal for curses.") from exc
