"""Transfer the encrypted SSH backup and restore it through an interactive SSH TTY."""
import hashlib
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys


RECEIVER = r"""
import hashlib, os, pathlib, sys, tempfile
home = pathlib.Path.home()
target = home / "30na-SSH-Backup.zip"
if target.is_symlink():
    raise SystemExit("Refusing symlink archive")
expected = sys.argv[1]
size = int(sys.argv[2])
fd, name = tempfile.mkstemp(prefix=".30na-archive-", dir=home)
try:
    digest = hashlib.sha256()
    received = 0
    with os.fdopen(fd, "wb") as output:
        while block := sys.stdin.buffer.read(65536):
            received += len(block)
            if received > size:
                raise SystemExit("Archive transfer exceeds expected size")
            digest.update(block)
            output.write(block)
        output.flush()
        os.fsync(output.fileno())
    if received != size or digest.hexdigest() != expected:
        raise SystemExit("Archive transfer verification failed")
    os.replace(name, target)
finally:
    pathlib.Path(name).unlink(missing_ok=True)
"""


def restore_backup(address, key, archive=None):
    archive = Path.home() / "30na-SSH-Backup.zip" if archive is None else Path(archive)
    if not os.path.lexists(archive):
        return
    if not sys.stdin.isatty():
        raise RuntimeError("SSH backup restoration requires an interactive terminal for the ZIP password")
    from thirtyna.onboarding import ssh_options

    fd = os.open(archive, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or not 0 < info.st_size <= 16 * 1024 * 1024):
            raise RuntimeError("Expected an owned SSH backup archive of at most 16 MiB")
        digest = hashlib.sha256(source.read()).hexdigest()
        source.seek(0)
        receive = "python3 -c " + shlex.quote(RECEIVER) + " " + digest + " " + str(info.st_size)
        result = subprocess.run(
            ["ssh", "-T", *ssh_options(key), "--", "root@" + address, receive],
            stdin=source, timeout=120
        )
    if result.returncode:
        raise RuntimeError("Encrypted SSH backup transfer failed")
    peer = Path(__file__).with_name("backup_peer.py").read_text()
    script = (
        "set -euo pipefail\numask 077\n"
        "if ! command -v 7z >/dev/null; then\n"
        "apt-get update </dev/null\n"
        "DEBIAN_FRONTEND=noninteractive apt-get install -y p7zip-full </dev/null\nfi\n"
        'stage=$(mktemp -d "$HOME/.30na-extract.XXXXXXXX")\n'
        'trap \'rm -rf -- "$stage"\' EXIT\n'
        'echo "Enter SSH backup ZIP password:"\n'
        '7z e -r -y "-o$stage" -- "$HOME/30na-SSH-Backup.zip" 30na_windows 30na_windows.pub </dev/tty\n'
        "python3 -c " + shlex.quote(peer) + ' "$stage"\n'
    )
    result = subprocess.run(
        ["ssh", "-tt", *ssh_options(key), "--", "root@" + address,
         "bash -c " + shlex.quote(script)],
        timeout=900
    )
    if result.returncode:
        raise RuntimeError("SSH backup extraction or key restoration failed; host was not registered")
