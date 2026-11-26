"""Bounded preview and terminal editing without a GUI toolkit."""
import codecs
import os
import stat
import subprocess

from .model import label

LIMIT = 16384


def sample(path):
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("Only regular text files can be opened")
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("Not a regular file")
        data = stream.read(LIMIT + 1)
    if b"\0" in data:
        raise ValueError("Binary file")
    try:
        decoder = codecs.getincrementaldecoder("utf-8-sig")()
        return decoder.decode(data[:LIMIT], final=len(data) <= LIMIT)
    except UnicodeError as exc:
        raise ValueError("Preview requires UTF-8 text") from exc


def preview(path):
    if path is None:
        return ["No selection"]
    try:
        if path.is_dir():
            return ["Directory", "Press → to enter"]
        return [label(line.expandtabs(4)) for line in sample(path).splitlines()] or ["Empty file"]
    except (OSError, ValueError) as exc:
        return [label(exc)]


def edit(screen, curses, path):
    sample(path)
    curses.def_prog_mode()
    curses.endwin()
    try:
        result = subprocess.run(["nano", "--", str(path)])
        if result.returncode:
            raise RuntimeError(f"nano exited with status {result.returncode}")
    finally:
        curses.reset_prog_mode()
        screen.clearok(True)
        screen.refresh()
