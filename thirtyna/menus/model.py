from dataclasses import dataclass
from pathlib import Path


def label(value):
    """Escape control characters and undecodable bytes before display."""
    return "".join(c if c.isprintable() else ascii(c)[1:-1] for c in str(value))


@dataclass(frozen=True)
class Item:
    title: str
    target: object


class Directory:
    def __init__(self, path):
        self.open(path)

    def open(self, path):
        path = Path(path).expanduser().resolve(strict=True)
        items = []
        for child in path.iterdir():
            if child.is_dir():
                items.append(Item(label(child.name) + "/", child))
        items.sort(key=lambda item: (item.title.casefold(), item.title))
        if path != path.parent:
            items.insert(0, Item("..", path.parent))
        self.title, self.items = label(path), items


MENUS = {"dir": ("Directory browser", Directory)}


class MenuSession:
    def __init__(self, start, target=None):
        self.start = start
        self.direct = target is not None
        self.page = None
        self.done = False
        self.error = ""
        if target:
            key, path = target
            self.page = MENUS[key][1](path)

    @property
    def title(self):
        return self.page.title if self.page else "30nA menus"

    @property
    def items(self):
        if self.page:
            return self.page.items
        return [Item(title, key) for key, (title, _) in MENUS.items()]

    def select(self, item):
        try:
            if self.page:
                self.page.open(item.target)
            else:
                self.page = MENUS[item.target][1](self.start)
            self.error = ""
        except (OSError, RuntimeError) as exc:
            self.error = label(exc)

    def back(self):
        self.error = ""
        if self.direct or self.page is None:
            self.done = True
        else:
            self.page = None
