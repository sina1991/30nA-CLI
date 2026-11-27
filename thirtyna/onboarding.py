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


def enroll(address, interactive=False):
    """Verify key-only access before the caller saves the host."""
    if interactive and not sys.stdin.isatty():
        raise RuntimeError("Password authentication requires an interactive terminal")
    machine = Path("/etc/machine-id").read_bytes().strip()
    if not re.fullmatch(rb"[0-9a-f]{32}", machine):
        raise RuntimeError("Local machine identity unavailable")
    controller = hashlib.sha256(machine).hexdigest()
    key = import_identity()
    try:
        authenticate(address, key, controller, interactive)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("SSH enrollment timed out") from exc
