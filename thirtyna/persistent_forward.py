"""Persistent local OpenSSH forwards owned by individual systemd units."""
import os
import secrets
import time
from pathlib import Path

from thirtyna.core import UsageError
from thirtyna.onboarding import distinct_probe, ssh_options
from thirtyna.ssh_identity import existing_identity
from thirtyna.two_vps import MAX_TUNNELS, check_free, command, local_machine, locked, save, unit, write_new

SYSTEMD = Path("/etc/systemd/system")


def definition(row):
    spec = f"{row['local']}:{row['local_port']}:127.0.0.1:{row['remote_port']}"
    options = ssh_options(Path(row["identity"]))
    # ClearAllForwardings also removes explicit -L, so override it first.
    argv = ["/usr/bin/ssh", "-F", "/dev/null", "-NT", "-o", "ClearAllForwardings=no", *options,
            "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3", "-L", spec, "--", row["host"]]
    quoted = ['"' + part.replace("\\", "\\\\").replace('"', '\\"')
              .replace("%", "%%").replace("$", "$$") + '"' for part in argv]
    return ("[Unit]\nDescription=30nA managed forward " + row["id"] +
            "\nWants=network-online.target\nAfter=network-online.target\n"
            "[Service]\nType=simple\nExecStart=" + " ".join(quoted) +
            "\nRestart=always\nRestartSec=3\nKillMode=control-group\n"
            "[Install]\nWantedBy=multi-user.target\n")


def owned_file(row):
    path = SYSTEMD / unit(row)
    if path.is_symlink() or (path.exists() and path.read_text() != definition(row)):
        raise RuntimeError("Forward unit ownership changed: " + unit(row))
    return path


def status(row):
    from thirtyna.agents.port import matching, owner_pids

    if not owned_file(row).is_file():
        return dict(row, state="failed", reason="unit_missing", pid=0)
    pid = int(command(["systemctl", "show", "-p", "MainPID", "--value", unit(row)]) or "0")
    if pid and any(endpoint.address == row["local"] and pid in owner_pids(endpoint)
                   for endpoint in matching(row["local_port"], "tcp")):
        return dict(row, state="ready", pid=pid)
    return dict(row, pid=0, state="stopped" if row.get("paused") else "starting")


def wait_for_listener(row):
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        current = status(row)
        if current["pid"]:
            return current
        time.sleep(0.3)
    raise RuntimeError("Forward did not acquire its listener. Check journalctl -u " + unit(row))


def delete(row):
    path = owned_file(row)
    if path.exists():
        command(["systemctl", "disable", "--now", unit(row)])
        path.unlink()
    command(["systemctl", "daemon-reload"])


def start(parameters):
    if os.geteuid() != 0:
        raise UsageError("Persistent Forward requires root on the local controller")
    key = existing_identity()
    if key is None:
        raise UsageError("Complete Host onboarding before creating a persistent Forward")
    if not distinct_probe(parameters["host"], key, local_machine(), isolated=True):
        raise RuntimeError("Forward requires key-only SSH as root on the registered host, port 22")
    row = dict(parameters, id=secrets.token_hex(12), identity=str(key), engine="systemd-forward")
    with locked(create=True, kind="forward") as (path, rows):
        if len(rows) >= MAX_TUNNELS:
            raise UsageError("Too many persistent forwards")
        if any((r["local"], r["local_port"]) == (row["local"], row["local_port"])
               for r in rows.values()):
            raise UsageError("Listener is already assigned to a persistent Forward")
        check_free(row)
        unitfile = owned_file(row)
        if unitfile.exists():
            raise RuntimeError("Generated Forward unit already exists")
        rows[row["id"]] = row
        save(path, rows)
        try:
            write_new(unitfile, definition(row))
            command(["systemctl", "daemon-reload"])
            command(["systemctl", "enable", "--now", unit(row)])
            return wait_for_listener(row)
        except (OSError, RuntimeError, ValueError, KeyboardInterrupt) as exc:
            try:
                delete(row)
            except (OSError, RuntimeError) as cleanup:
                raise RuntimeError(f"Forward setup failed: {exc}. Delete {row['id']} to retry cleanup: {cleanup}") from exc
            del rows[row["id"]]
            save(path, rows)
            raise


def list_rows():
    with locked(kind="forward") as (_, rows):
        result = []
        for row in rows.values():
            try:
                result.append(status(row))
            except (OSError, RuntimeError, ValueError):
                result.append(dict(row, state="unknown", pid=0))
        return result


def operate(token, operation):
    with locked(kind="forward") as (path, rows):
        row = rows.get(token)
        if row is None:
            return False
        if operation == "delete":
            delete(row)
            del rows[token]
        else:
            if not owned_file(row).is_file():
                raise RuntimeError("Forward unit is missing: " + unit(row))
            verb = "disable" if operation == "stop" else "enable"
            command(["systemctl", verb, "--now", unit(row)])
            row["paused"] = operation == "stop"
        save(path, rows)
        if operation == "restart":
            command(["systemctl", "restart", unit(row)])
        if operation in ("resume", "restart"):
            wait_for_listener(row)
        return True
