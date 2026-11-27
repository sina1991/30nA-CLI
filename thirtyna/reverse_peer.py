"""Fixed remote executor for a single owned two-VPS reverse tunnel."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

BASE = Path("/var/lib/30na-reverse")
SYSTEMD = Path("/etc/systemd/system")


def run(args, timeout=12, check=True):
    result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(args[0] + " failed: " + result.stderr.strip()[:500])
    return result.stdout.strip()


def machine():
    value = Path("/etc/machine-id").read_bytes().strip()
    if not re.fullmatch(rb"[0-9a-f]{32}", value):
        raise RuntimeError("Machine identity unavailable")
    return hashlib.sha256(value).hexdigest()


def execute(op, data):
    if os.geteuid() != 0:
        raise RuntimeError("Remote management SSH user must be root")
    identity = machine()
    if op == "identity":
        return {"machine": identity, "ips": run(["hostname", "-I"]).split()}
    if identity != data["machine"]:
        raise RuntimeError("Remote machine identity changed")
    token = data["id"]
    if not re.fullmatch(r"[0-9a-f]{24}", token):
        raise RuntimeError("Invalid tunnel identity")
    directory = BASE / token
    unit = "30na-tunnel-" + token + ".service"
    unitfile = SYSTEMD / unit
    marker = directory / "owner"
    key = directory / "key"
    if op == "prepare":
        BASE.mkdir(mode=0o700, exist_ok=True)
        if BASE.is_symlink() or BASE.stat().st_uid != 0 or BASE.stat().st_mode & 0o077:
            raise RuntimeError("Unsafe reverse key directory")
        if unitfile.exists() or unitfile.is_symlink():
            raise RuntimeError("Remote unit already exists")
        directory.mkdir(mode=0o700)
        marker.write_text(token)
        run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)])
        return {"public": key.with_suffix(".pub").read_text().strip()}
    if BASE.is_symlink() or (BASE.exists() and (BASE.stat().st_uid != 0 or BASE.stat().st_mode & 0o077)):
        raise RuntimeError("Unsafe reverse key directory")
    if not directory.exists() and not directory.is_symlink():
        if op == "stop" and not unitfile.exists() and not unitfile.is_symlink():
            return {"stopped": True}
        raise RuntimeError("Remote tunnel directory absent")
    if directory.is_symlink() or marker.is_symlink() or marker.read_text() != token:
        raise RuntimeError("Remote tunnel ownership unverified")
    if op == "start":
        # Unit definition is produced by the authenticated controller.
        if unitfile.exists() or unitfile.is_symlink():
            raise RuntimeError("Remote unit already exists")
        known = directory / "known_hosts"
        with known.open("x") as f:
            f.write(data["known_hosts"])
        known.chmod(0o600)
        definition = data["definition"]
        if not definition.startswith("[Unit]\nDescription=30nA managed reverse " + token + "\n"):
            raise RuntimeError("Invalid unit ownership marker")
        with unitfile.open("x") as f:
            f.write(definition)
        unitfile.chmod(0o644)
        run(["systemctl", "daemon-reload"])
        run(["systemctl", "enable", "--now", unit])
        return {"active": run(["systemctl", "is-active", unit], check=False)}
    if op == "stop":
        if unitfile.is_symlink():
            raise RuntimeError("Refusing symlink unit")
        if unitfile.exists():
            if not unitfile.read_text().startswith("[Unit]\nDescription=30nA managed reverse " + token + "\n"):
                raise RuntimeError("Remote unit ownership changed")
            run(["systemctl", "disable", "--now", unit])
            state = run(["systemctl", "is-active", unit], check=False)
            if state not in ("inactive", "failed", "unknown"):
                raise RuntimeError("Remote unit not stopped")
            unitfile.unlink()
            run(["systemctl", "daemon-reload"])
        shutil.rmtree(directory)
        return {"stopped": True}
    raise RuntimeError("Unknown reverse operation")


if __name__ == "__main__":
    try:
        operation, payload = json.loads(base64.b64decode(PAYLOAD))
        print(json.dumps(execute(operation, payload)))
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc)[:1000]}))
        sys.exit(1)
