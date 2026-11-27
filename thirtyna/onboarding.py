"""Register and verify the local management public key over SSH."""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys

from thirtyna.ssh_identity import import_identity, identity_options


def authentication_options(key, interactive=False):
    return [*identity_options(key), "-o", "IdentityAgent=none", "-o", "CertificateFile=none", "-o", "BatchMode=" + ("no" if interactive else "yes"),
            "-o", "PreferredAuthentications=" + ("publickey,password,keyboard-interactive" if interactive else "publickey"),
            "-o", "StrictHostKeyChecking=" + ("ask" if interactive else "yes"),
            "-o", "NumberOfPasswordPrompts=3"]


def ssh_options(key, interactive=False):
    return [*authentication_options(key, interactive), "-o", "ConnectTimeout=8",
            "-o", "ClearAllForwardings=yes", "-o", "ControlMaster=no",
            "-o", "ControlPath=none", "-o", "PermitLocalCommand=no"]


def verify_identity_config(address, key):
    result = subprocess.run(["ssh", "-G", *ssh_options(key), "--", address],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=8)
    if result.returncode:
        raise RuntimeError("Cannot verify SSH configuration")
    identities = [line.partition(" ")[2] for line in result.stdout.splitlines()
                  if line.startswith("identityfile ")]
    if not identities or any(Path(os.path.expanduser(name)) != key for name in identities):
        raise RuntimeError("SSH config includes another IdentityFile; use a host entry with only the 30nA management identity")
    certificates = [line.partition(" ")[2] for line in result.stdout.splitlines()
                    if line.startswith("certificatefile ")]
    if any(name != "none" for name in certificates):
        raise RuntimeError("SSH config includes another certificate identity")


def distinct_probe(address, key, controller, interactive=False, isolated=False):
    config = ["-F", "/dev/null"] if isolated else []
    result = subprocess.run(["ssh", "-T", *config, *ssh_options(key, interactive),
                             "--", address, "cat /etc/machine-id"],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=None if interactive else subprocess.PIPE, timeout=90 if interactive else 15)
    if result.returncode:
        return False
    machine = result.stdout.strip()
    if not re.fullmatch(rb"[0-9a-f]{32}", machine):
        raise RuntimeError("Remote machine identity unavailable")
    if hashlib.sha256(machine).hexdigest() == controller:
        raise RuntimeError("Endpoint is the local machine, reserved ID 1")
    return True


def authenticate(address, key, controller, interactive):
    verify_identity_config(address, key)
    if distinct_probe(address, key, controller):
        return
    if not interactive:
        raise RuntimeError("SSH key login failed; verify host key or use interactive -password enrollment")
    print("Verify any new SSH host fingerprint independently before accepting.", file=sys.stderr, flush=True)
    if not distinct_probe(address, key, controller, interactive=True):
        raise RuntimeError("Interactive SSH authentication failed")
    # Probe already verified host identity. Copy only the selected public key.
    print("Registering the management public key with ssh-copy-id.", file=sys.stderr, flush=True)
    options = ssh_options(key, True)
    options[options.index("StrictHostKeyChecking=ask")] = "StrictHostKeyChecking=yes"
    # ssh-copy-id accepts -i and -o, not ssh's standalone -T.
    # The public file supplied to -i also selects its matching local private key.
    options = options[2:]
    # Force the exact public key to be tested by ssh-copy-id even if an
    # unrelated SSH agent is available. Native password prompts stay on TTY.
    result = subprocess.run(["ssh-copy-id", "-i", str(key.with_suffix(".pub")),
                             *options, address], timeout=120)
    if result.returncode:
        raise RuntimeError("ssh-copy-id failed; check remote authorized_keys")
    if not distinct_probe(address, key, controller):
        raise RuntimeError("Public key was offered but noninteractive login is not verified; check server policy")


def enroll(address, interactive=False, install=False):
    """Verify key-only access before the caller saves the host."""
    if interactive and not sys.stdin.isatty():
        raise RuntimeError("Password authentication requires an interactive terminal")
    machine = Path("/etc/machine-id").read_bytes().strip()
    if not re.fullmatch(rb"[0-9a-f]{32}", machine):
        raise RuntimeError("Local machine identity unavailable")
    controller = hashlib.sha256(machine).hexdigest()
    key = import_identity(create=True)
    try:
        authenticate(address, key, controller, interactive)
        configure_login(address, key)
        if install:
            install_remote(address, key)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("SSH enrollment timed out") from exc


def configure_login(address, key):
    """Select the verified management key for ordinary SSH from this account."""
    import fcntl
    import tempfile

    ssh = key.parent.parent
    config = ssh / "config"
    lock = ssh / ".30na-config.lock"
    with lock.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        if config.is_symlink():
            raise RuntimeError("Refusing symlink SSH config")
        if config.exists():
            import stat
            info = config.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
                raise RuntimeError("Unsafe SSH config ownership or permissions")
        original = config.read_text() if config.exists() else ""
        begin = "# BEGIN 30na " + address
        end = "# END 30na " + address
        block = (begin + "\nHost " + address + "\n    User root\n"
                 '    IdentityFile "' + str(key).replace("\\", "\\\\").replace('"', '\\"') +
                 '"\n    IdentitiesOnly yes\n    StrictHostKeyChecking yes\n' + end + "\n")
        if begin in original:
            start = original.index(begin)
            finish = original.find(end, start)
            if finish < 0:
                raise RuntimeError("Incomplete managed SSH configuration")
            original = original[:start] + original[finish + len(end):].lstrip("\n")
        updated = block + ("Host *\n" if not original.startswith("Host *\n") else "") + original
        fd, temporary = tempfile.mkstemp(dir=ssh, prefix=".30na-config-")
        try:
            with os.fdopen(fd, "w") as output:
                output.write(updated)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, config)
        finally:
            Path(temporary).unlink(missing_ok=True)
    result = subprocess.run(
        ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
         "-o", "ClearAllForwardings=yes", "root@" + address, "true"],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=15
    )
    if result.returncode:
        raise RuntimeError("Ordinary SSH login verification failed")


REMOTE_INSTALL = r"""
set -euo pipefail
test "$(id -u)" = 0 || { echo "Remote installation requires root"; exit 1; }
. /etc/os-release
test "$ID" = ubuntu || { echo "Remote bootstrap requires Ubuntu"; exit 1; }
if ! command -v git >/dev/null || ! command -v update-ca-certificates >/dev/null; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y git ca-certificates
fi
work=$(mktemp -d /tmp/30na-host-install.XXXXXX)
trap 'rm -rf -- "$work"' EXIT
git clone --quiet https://github.com/sina1991/30nA-CLI.git "$work"
git -C "$work" checkout --quiet --detach origin/main
requested=$(git -C "$work" rev-parse HEAD)
launcher=/usr/local/bin/30na
if test -e "$launcher"; then
    installed=$(readlink -f "$launcher")
    marker="$(dirname "$installed")/.revision"
    test -f "$marker" || { echo "Installed revision unknown; cannot verify upgrade"; exit 1; }
    previous=$(cat "$marker")
    [[ "$previous" =~ ^[0-9a-f]{40}$ ]] || { echo "Invalid installed revision"; exit 1; }
    git -C "$work" cat-file -e "$previous^{commit}" ||
        git -C "$work" fetch origin "$previous"
    git -C "$work" merge-base --is-ancestor "$previous" "$requested" ||
        { echo "Refusing downgrade or divergent release"; exit 1; }
fi
echo "INSTALLING_REVISION $requested"
bash "$work/install.sh" </dev/null
installed=$(readlink -f "$launcher")
test "$(cat "$(dirname "$installed")/.revision")" = "$requested"
"$launcher" -help >/dev/null
echo "30NA_INSTALL_OK $requested"
"""


def install_remote(address, key):
    result = subprocess.run(
        ["ssh", "-T", *ssh_options(key), "--", "root@" + address, "bash", "-s"],
        input=REMOTE_INSTALL, text=True, timeout=900
    )
    if result.returncode:
        raise RuntimeError("Remote 30na installation failed; host was not registered")
