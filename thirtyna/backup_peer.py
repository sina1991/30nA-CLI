"""Validate and restore the operator's SSH key pair from a private staging directory."""
import fcntl
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile


def regular(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise RuntimeError("Key restoration requires owned regular files")
    return info


def private_directory(path):
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise RuntimeError("Unsafe SSH directory")
    path.chmod(0o700)


def write_file(path, content, mode):
    fd, name = tempfile.mkstemp(prefix=".30na-key-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            os.fchmod(output.fileno(), mode)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def restore(stage, home):
    key = stage / "30na_windows"
    public = key.with_suffix(".pub")
    for path in (key, public):
        if regular(path).st_size > 65536:
            raise RuntimeError("Extracted key is too large")
    key.chmod(0o600)
    secret = key.read_bytes()
    public_data = public.read_bytes()
    expected = public_data.split()
    result = subprocess.run(
        ["ssh-keygen", "-y", "-P", "", "-f", str(key)],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=10
    )
    if (result.returncode or len(expected) < 2 or expected[0] != b"ssh-ed25519"
            or result.stdout.split()[:2] != expected[:2]):
        raise RuntimeError("Extracted key pair is invalid or mismatched")
    ssh = home / ".ssh"
    private_directory(ssh)
    managed = ssh / "30na-management"
    private_directory(managed)
    lock_path = ssh / ".30na-management.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+b") as lock:
        regular(lock_path)
        fcntl.flock(lock, fcntl.LOCK_EX)
        targets = [
            (home / "30na_windows", secret, 0o600),
            (home / "30na_windows.pub", public_data, 0o644),
            (ssh / "id_ed25519", secret, 0o600),
            (ssh / "id_ed25519.pub", public_data, 0o644),
            (managed / "identity", secret, 0o600),
            (managed / "identity.pub", public_data, 0o644),
        ]
        authorized = ssh / "authorized_keys"
        for path, _, _ in targets:
            if os.path.lexists(path):
                regular(path)
        if os.path.lexists(authorized):
            regular(authorized)
        backup = None
        for path, content, mode in targets:
            if path.exists() and path.read_bytes() != content:
                if backup is None:
                    backup = Path(tempfile.mkdtemp(prefix="30na-key-backup.", dir=ssh))
                # Relative directory names preserve distinct identity copies.
                relative = path.relative_to(home)
                destination = backup / relative
                destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
                destination.chmod(0o600)
            write_file(path, content, mode)
        previous = authorized.read_bytes() if authorized.exists() else b""
        normalized = b" ".join(expected[:2])
        present = any(line.strip().startswith(normalized + b" ") or line.strip() == normalized
                      for line in previous.splitlines())
        if not present:
            previous = previous.rstrip(b"\n") + b"\n" + normalized + b"\n"
        write_file(authorized, previous, 0o600)
        if backup is not None:
            print("PREVIOUS_KEYS_BACKUP", backup)
    print("SSH_BACKUP_RESTORED")


if __name__ == "__main__":
    try:
        restore(Path(sys.argv[1]), Path.home())
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print("SSH backup restoration failed:", exc, file=sys.stderr)
        raise SystemExit(1)
