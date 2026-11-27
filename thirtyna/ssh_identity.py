"""Local-only management identity; never import credentials from chat or network."""
import fcntl
import os
from pathlib import Path
import stat
import subprocess
import tempfile


def private_dir(path):
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError("SSH management directory must be owned by this user and mode 0700")


def read_key(path, private):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeError("SSH key must be an owned regular file")
        if private and info.st_mode & 0o077:
            raise RuntimeError("Private SSH key must have mode 0600 or stricter")
        data = stream.read(65537)
        if not data or len(data) > 65536:
            raise RuntimeError("Invalid SSH key size")
        return data


def validate_pair(key):
    read_key(key, True)
    public = read_key(key.with_suffix(".pub"), False).split()
    try:
        result = subprocess.run(["ssh-keygen", "-y", "-P", "", "-f", str(key)],
                                stdin=subprocess.DEVNULL, capture_output=True, timeout=5)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("SSH key validation timed out") from exc
    if result.returncode or len(public) < 2 or result.stdout.split()[:2] != public[:2]:
        raise RuntimeError("SSH key pair mismatch, invalid or encrypted; use a verified noninteractive management pair")


def existing_identity(home=None):
    home = Path.home() if home is None else Path(home)
    directory = home / ".ssh" / "30na-management"
    key = directory / "identity"
    if not directory.exists() and not directory.is_symlink():
        return None
    private_dir(home / ".ssh")
    private_dir(directory)
    validate_pair(key)
    return key


def import_identity(home=None):
    home = Path.home() if home is None else Path(home)
    ssh = home / ".ssh"
    private_dir(ssh)
    lock = os.open(ssh / ".30na-management.lock",
                   os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(lock, "r+b") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise RuntimeError("Unsafe SSH management lock")
        fcntl.flock(stream, fcntl.LOCK_EX)
        current = existing_identity(home)
        if current is not None:
            return current
        source = home / "30na_windows"
        secret = read_key(source, True)
        public = read_key(source.with_suffix(".pub"), False)
        with tempfile.TemporaryDirectory(prefix=".30na-import-", dir=ssh) as temp:
            staging = Path(temp) / "pair"
            staging.mkdir(mode=0o700)
            key = staging / "identity"
            for path, data in ((key, secret), (key.with_suffix(".pub"), public)):
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "wb") as output:
                    output.write(data)
            validate_pair(key)
            destination = ssh / "30na-management"
            staging.rename(destination)
        return destination / "identity"


def identity_options(key):
    return ["-i", str(key), "-o", "IdentitiesOnly=yes", "-o", "ForwardAgent=no"]
