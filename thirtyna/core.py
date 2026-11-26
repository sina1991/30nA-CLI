"""Discover agent modules and dispatch a single shell invocation."""
import argparse
import importlib
import pkgutil
import sys

from thirtyna import agents


class UsageError(ValueError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)


def parser(name, description, examples):
    result = Parser(prog="30na " + name, description=description,
                    epilog=examples, allow_abbrev=False, add_help=False)
    result.add_argument("-help", "--help", action="help")
    return result


def input_value(prompt):
    if sys.stdin.isatty():
        print(prompt, end=" ", file=sys.stderr, flush=True)
        return sys.stdin.readline().strip()
    return sys.stdin.read().strip()


def discover(package=agents):
    registry = {}
    for item in pkgutil.iter_modules(package.__path__):
        if item.name.startswith("_"):
            continue
        module = importlib.import_module(package.__name__ + "." + item.name)
        if module.SWITCH in registry:
            raise RuntimeError("Duplicate agent switch: " + module.SWITCH)
        registry[module.SWITCH] = module
    return registry


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        registry = discover()
        if not argv or argv == ["-help"] or argv == ["--help"]:
            print("Usage: 30na AGENT [options]\n" + "\n".join(
                f"{key}  {module.NAME}" for key, module in registry.items()))
            return 0
        if argv[0] not in registry:
            raise UsageError("Unknown agent: " + argv[0])
        return registry[argv[0]].run(argv[1:]) or 0
    except UsageError as exc:
        print(f"30na: {exc}", file=sys.stderr)
        return 2
    except (OSError, RuntimeError) as exc:
        print(f"30na: {exc}", file=sys.stderr)
        return 1
