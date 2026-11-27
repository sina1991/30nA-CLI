"""Two-VPS reverse: remote initiates SSH; the local port remains the listener.

Only new managed reverse tunnels use this engine. Existing worker sessions and
external units are not migrated or mutated. No private key crosses machines.
"""
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shlex
import socket
import stat
import subprocess
import tempfile
import time

from thirtyna.core import UsageError
from thirtyna.address import host_address
from thirtyna.agents.sysinfo import local_addresses
from thirtyna.onboarding import ssh_options, verify_identity_config
from thirtyna.ssh_identity import existing_identity, private_dir
from thirtyna.runtime.service import folder

TOKEN = re.compile(r"[0-9a-f]{24}\Z")
PUBLIC = re.compile(r"ssh-ed25519 [A-Za-z0-9+/=]+(?: .*)?\Z")
SSHD = "/usr/sbin/sshd"
CONFIG = Path("/etc/ssh/sshd_config.d")
SSHD_CONFIG = Path("/etc/ssh/sshd_config")
MAX_TUNNELS = 32


def command(args, timeout=12):
    try:
        result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(args[0] + " timed out") from exc
    if result.returncode:
        raise RuntimeError(args[0] + " failed: " + result.stderr.strip()[:500])
    return result.stdout.strip()


def account(row):
    return "ntr-" + row["id"]


def config_path(row):
    return CONFIG / ("90-30na-" + row["id"] + ".conf")


def keys_path(row):
    return Path("/etc/ssh") / (account(row) + ".keys")


def unit(row):
    return "30na-tunnel-" + row["id"] + ".service"


def reverse_spec(row):
    return f"{row['local']}:{row['local_port']}:127.0.0.1:{row['remote_port']}"


def service_definition(row):
    root = "/var/lib/30na-reverse/" + row["id"]
    argv = ["/usr/bin/ssh", "-F", "/dev/null", "-NT", "-o", "BatchMode=yes",
            "-o", "IdentitiesOnly=yes", "-o", "IdentityAgent=none",
            "-o", "StrictHostKeyChecking=yes", "-o", "GlobalKnownHostsFile=/dev/null",
            "-o", "UserKnownHostsFile=" + root + "/known_hosts",
            "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3", "-o", "ConnectTimeout=8",
            "-i", root + "/key", "-p", "22", "-R", reverse_spec(row),
            account(row) + "@" + row["gateway"]]
    return ("[Unit]\nDescription=30nA managed reverse " + row["id"] +
            "\nWants=network-online.target\nAfter=network-online.target\n"
            "[Service]\nType=simple\nUser=root\nExecStart=" + shlex.join(argv) +
            "\nRestart=always\nRestartSec=3\nKillMode=control-group\n"
            "[Install]\nWantedBy=multi-user.target\n")


def policy(row):
    return (f"Match User {account(row)}\n"
            f"    AuthorizedKeysFile {keys_path(row)}\n"
            "    PubkeyAuthentication yes\n    AuthenticationMethods publickey\n"
            "    PasswordAuthentication no\n    KbdInteractiveAuthentication no\n"
            "    MaxSessions 0\n    AllowTcpForwarding remote\n"
            "    GatewayPorts clientspecified\n    PermitOpen none\n"
            f"    PermitListen {row['local']}:{row['local_port']}\n"
            "    PermitTTY no\n    AllowAgentForwarding no\n    X11Forwarding no\n"
            "    PermitTunnel no\nMatch all\n")


def public_key(value):
    if not isinstance(value, str) or len(value) > 1024 or not PUBLIC.fullmatch(value):
        raise RuntimeError("Expected an Ed25519 public key")
    return " ".join(value.split()[:2])


def remote(row, op, **kwargs):
    address = host_address(row["host"])
    key = existing_identity()
    if key is None:
        raise RuntimeError("Complete Host onboarding before creating Reverse")
    verify_identity_config(address, key)
    data = dict(row, **kwargs)
    payload = base64.b64encode(json.dumps([op, data]).encode()).decode("ascii")
    source = Path(__file__).with_name("reverse_peer.py").read_text()
    script = "PAYLOAD = " + repr(payload) + "\n" + source
    # The peer source uses no __future__ imports. The payload contains only
    # public keys and metadata, never management or tunnel private keys.
    try:
        result = subprocess.run(["ssh", "-T", *ssh_options(key), "--", address, "python3", "-"],
                                input=script, capture_output=True, text=True, timeout=40)
        answer = json.loads(result.stdout)
    except (ValueError, subprocess.SubprocessError) as exc:
        raise RuntimeError("Remote reverse operation unconfirmed: " + op) from exc
    if not isinstance(answer, dict) or result.returncode or "error" in answer:
        detail = answer.get("error", "SSH or peer failure") if isinstance(answer, dict) else "Invalid reply"
        raise RuntimeError("Remote " + op + ": " + str(detail)[:500])
    return answer


def local_machine():
    value = Path("/etc/machine-id").read_bytes().strip()
    if not re.fullmatch(rb"[0-9a-f]{32}", value):
        raise RuntimeError("Local machine identity unavailable")
    return hashlib.sha256(value).hexdigest()


def gateway_address(bind):
    ip = ipaddress.ip_address(bind)
    if ip.version != 4:
        raise UsageError("Two-VPS Reverse currently supports IPv4")
    if not ip.is_loopback:
        if bind not in local_addresses():
            raise UsageError("Local bind address is not assigned")
        return bind
    options = [x for x in local_addresses() if ipaddress.ip_address(x).version == 4]
    if len(options) != 1:
        raise UsageError("Select the explicit reachable local IPv4 with -ip")
    return options[0]


def check_free(row):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((row["local"], row["local_port"]))
    except OSError as exc:
        from thirtyna.agents.port import matching
        owners = "; ".join(r.line() for r in matching(row["local_port"], "tcp"))
        raise UsageError("Local port is unavailable: " + (owners or str(exc))) from exc


def write_new(path, value):
    with path.open("x") as stream:
        stream.write(value)
    path.chmod(0o644)


def effective_policy(row, peer_ip):
    return command([SSHD, "-T", "-C",
                    f"user={account(row)},host={peer_ip},addr={peer_ip},"
                    f"laddr={row['gateway']},lport=22"]).splitlines()


def main_policy_block(row):
    # A new Match User starts its own context even if the original file ends
    # in a Match block. Do not enable unrelated, previously dormant drop-ins.
    return (f"\n# BEGIN 30nA reverse {row['id']}\n" + policy(row)
            + f"# END 30nA reverse {row['id']}\n").encode()


def read_main_config():
    info = SSHD_CONFIG.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o022 or info.st_nlink != 1):
        raise RuntimeError("Unsafe sshd_config; refusing automatic edit")
    return SSHD_CONFIG.read_bytes(), info


def replace_main_config(original, updated, info):
    fd, name = tempfile.mkstemp(prefix=".30na-sshd-", dir=SSHD_CONFIG.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchown(stream.fileno(), info.st_uid, info.st_gid)
            os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode))
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        current, current_info = read_main_config()
        if (current != original or current_info.st_ino != info.st_ino
                or current_info.st_dev != info.st_dev
                or current_info.st_mode != info.st_mode
                or current_info.st_uid != info.st_uid or current_info.st_gid != info.st_gid):
            raise RuntimeError("sshd_config changed concurrently; refusing overwrite")
        os.replace(temp, SSHD_CONFIG)
        fd = os.open(SSHD_CONFIG.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temp.unlink(missing_ok=True)


def ensure_policy_loaded(row, peer_ip, persist):
    command([SSHD, "-t"])
    if f"authorizedkeysfile {keys_path(row)}" in effective_policy(row, peer_ip):
        return
    # On images with no effective Include, append exactly the same scoped
    # policy directly. Preserve every pre-existing byte and all other users.
    original, info = read_main_config()
    block = main_policy_block(row)
    if f"# BEGIN 30nA reverse {row['id']}".encode() in original:
        raise RuntimeError("Unexpected existing managed sshd policy")
    row["main_policy_attempt"] = True
    persist()
    replace_main_config(original, original + block, info)


def remove_main_policy(row):
    if not row.get("main_policy_attempt"):
        return
    original, info = read_main_config()
    block = main_policy_block(row)
    if original.count(block) == 1:
        replace_main_config(original, original.replace(block, b"", 1), info)
    elif (f"# BEGIN 30nA reverse {row['id']}".encode() in original
          or f"# END 30nA reverse {row['id']}".encode() in original
          or ("Match User " + account(row)).encode() in original):
        raise RuntimeError("Managed sshd policy changed; refusing automatic removal")


def reload_sshd():
    states = command(["systemctl", "is-active", "ssh.service", "ssh.socket"]).splitlines()
    if states != ["inactive", "active"]:
        command(["systemctl", "reload", "ssh.service"])


def validate_policy(row, peer_ip):
    command([SSHD, "-t"])
    effective = effective_policy(row, peer_ip)
    for setting in ("port 22", "pubkeyauthentication yes", "authenticationmethods publickey",
                    "maxsessions 0", "allowtcpforwarding remote", "gatewayports clientspecified",
                    "disableforwarding no", "passwordauthentication no",
                    "permitopen none", f"permitlisten {row['local']}:{row['local_port']}",
                    f"authorizedkeysfile {keys_path(row)}"):
        if setting not in effective:
            raise RuntimeError("Conflicting local sshd policy: " + setting)
    reload_sshd()


def state_dir():
    root = folder()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    private_dir(root)
    directory = root / "two-vps"
    private_dir(directory)
    return directory


@contextmanager
def locked(create=False, kind="reverse"):
    if not create and not (folder() / "two-vps").exists() and not (folder() / "two-vps").is_symlink():
        yield None, {}
        return
    directory = state_dir()
    fd = os.open(directory / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+b") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        path = directory / (kind + ".json")
        rows = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(rows, dict) or len(rows) > MAX_TUNNELS:
            raise RuntimeError("Invalid reverse state")
        for token, row in rows.items():
            if not TOKEN.fullmatch(token) or row["id"] != token:
                raise RuntimeError("Invalid reverse state identity")
        yield path, rows


def save(path, rows):
    pending = path.with_suffix(".tmp")
    fd = os.open(pending, os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(rows, stream)
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def listener(row):
    """Match the actual listening sshd process to this dedicated account."""
    try:
        uid = pwd.getpwnam(account(row)).pw_uid
    except KeyError:
        return 0
    from thirtyna.agents.port import matching, owner_pids
    for endpoint in matching(row["local_port"], "tcp"):
        if endpoint.address != row["local"]:
            continue
        for pid in owner_pids(endpoint):
            try:
                proc = Path("/proc") / str(pid)
                name = (proc / "comm").read_text().strip()
                if name not in ("sshd", "sshd-session"):
                    continue
                status = (proc / "status").read_text().splitlines()
                ids = next(line.split()[1:] for line in status if line.startswith("Uid:"))
                title = (proc / "cmdline").read_bytes().split(b"\0", 1)[0]
                prefix = ("sshd: " + account(row)).encode()
                if str(uid) in ids or title == prefix or title.startswith(prefix + b" "):
                    return pid
            except (OSError, StopIteration):
                continue
    return 0


def clean_local(row):
    remove_main_policy(row)
    # Only exact generated configuration and keys belonging to this record.
    for path, expected in ((config_path(row), policy(row)),
                           (keys_path(row), row.get("authorized", ""))):
        if path.is_symlink():
            raise RuntimeError("Local resource ownership changed")
        if path.exists():
            if not expected or path.read_text() != expected:
                raise RuntimeError("Local resource ownership changed: " + path.name)
            path.unlink()
    command([SSHD, "-t"])
    reload_sshd()
    try:
        user = pwd.getpwnam(account(row))
    except KeyError:
        return
    if user.pw_uid == 0 or user.pw_gecos != "30na-reverse-" + row["id"]:
        raise RuntimeError("Local account ownership changed")
    # The account belongs exclusively to this tunnel. Remaining session
    # processes can outlive its forwarding listener.
    processes = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdecimal():
            continue
        try:
            ids = next(line.split()[1:] for line in (proc / "status").read_text().splitlines()
                       if line.startswith("Uid:"))
            if str(user.pw_uid) in ids:
                processes.append(int(proc.name))
        except (OSError, StopIteration):
            continue
    import signal
    for pid in processes:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if not any(Path("/proc", str(pid)).exists() for pid in processes):
            break
        time.sleep(0.1)
    command(["userdel", account(row)])


def cleanup(row):
    if row.get("remote_attempt"):
        remote(row, "stop")
    if row.get("local_attempt"):
        deadline = time.monotonic() + 5
        while listener(row):
            if time.monotonic() >= deadline:
                raise RuntimeError("Owned reverse listener still present; retry stop")
            time.sleep(0.2)
        clean_local(row)


def start(parameters):
    if os.geteuid() != 0:
        raise UsageError("Two-VPS Reverse requires root on the controller and peer")
    row = dict(parameters, id=secrets.token_hex(12), state="starting", pid=0,
               gateway=gateway_address(parameters["local"]), engine="two-vps")
    if parameters.get("restore"):
        raise UsageError("Two-VPS Reverse uses a persistent systemd service; omit -restore")
    identity = remote(row, "identity")
    machine = identity.get("machine", "")
    if not re.fullmatch(r"[0-9a-f]{64}", machine) or machine == local_machine():
        raise UsageError("Remote is local or has invalid machine identity")
    row["machine"] = machine
    ips = [str(ipaddress.ip_address(x)) for x in identity["ips"]
           if ipaddress.ip_address(x).version == 4 and not ipaddress.ip_address(x).is_loopback]
    if not ips:
        raise RuntimeError("Remote IPv4 identity unavailable")
    with locked(create=True) as (path, rows):
        if len(rows) >= MAX_TUNNELS:
            raise UsageError("Too many managed reverse tunnels")
        if any(r["local_port"] == row["local_port"] for r in rows.values()):
            raise UsageError("Local port already assigned to a managed Reverse; stop it first")
        check_free(row)
        # Verify local server and existing configuration before any change.
        command([SSHD, "-t"])
        command(["systemctl", "is-active", "ssh.service", "ssh.socket"])
        for resource in (config_path(row), keys_path(row)):
            if resource.exists() or resource.is_symlink():
                raise RuntimeError("Generated resource collision")
        try:
            pwd.getpwnam(account(row))
        except KeyError:
            pass
        else:
            raise RuntimeError("Generated account collision")
        host_key = public_key(Path("/etc/ssh/ssh_host_ed25519_key.pub").read_text().strip())
        rows[row["id"]] = row
        save(path, rows)
        try:
            row["remote_attempt"] = True
            save(path, rows)
            public = public_key(remote(row, "prepare")["public"])
            row["authorized"] = f'restrict,port-forwarding,permitlisten="{row["local"]}:{row["local_port"]}" {public}\n'
            row["local_attempt"] = True
            save(path, rows)
            command(["useradd", "--system", "--no-create-home", "--home-dir", "/nonexistent",
                     "--shell", "/usr/sbin/nologin", "--password", "*",
                     "--comment", "30na-reverse-" + row["id"], account(row)])
            write_new(keys_path(row), row["authorized"])
            write_new(config_path(row), policy(row))
            ensure_policy_loaded(row, ips[0], lambda: save(path, rows))
            validate_policy(row, ips[0])
            remote(row, "start", definition=service_definition(row),
                   known_hosts=row["gateway"] + " " + host_key + "\n")
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                if (pid := listener(row)):
                    row.update(state="ready", pid=pid)
                    save(path, rows)
                    return row.copy()
                time.sleep(0.3)
            raise RuntimeError("Remote SSH service did not acquire the Local listener")
        except (OSError, RuntimeError, ValueError, KeyError, KeyboardInterrupt) as exc:
            row.update(state="failed", reason="setup_failed")
            save(path, rows)
            try:
                cleanup(row)
            except (OSError, RuntimeError, ValueError, KeyError) as error:
                row["reason"] = "cleanup_pending"
                save(path, rows)
                raise RuntimeError(f"Reverse setup failed: {exc}; cleanup pending id={row['id']}: {error}") from exc
            del rows[row["id"]]
            save(path, rows)
            raise RuntimeError("Reverse setup failed and owned resources removed: " + str(exc)) from exc


def list_rows():
    with locked() as (_, rows):
        result = []
        for row in rows.values():
            item = row.copy()
            if item["state"] not in ("failed", "stopped"):
                try:
                    pid = listener(item)
                except (OSError, RuntimeError):
                    pid = 0
                item.update(pid=pid, state="ready" if pid else "starting")
            result.append(item)
        return result


def stop(token):
    if not TOKEN.fullmatch(token):
        return False
    with locked() as (path, rows):
        if token not in rows:
            return False
        row = rows[token]
        row.update(state="failed", reason="cleanup_pending")
        save(path, rows)
        cleanup(row)
        del rows[token]
        save(path, rows)
        return True

def operate(token, operation):
    if operation == "delete":
        return stop(token)
    if not TOKEN.fullmatch(token):
        return False
    with locked() as (path, rows):
        row = rows.get(token)
        if row is None:
            return False
        if row["state"] == "failed":
            raise RuntimeError("Reverse setup is incomplete; use -delete to clean up")
        remote(row, {"stop": "pause", "resume": "resume", "restart": "restart"}[operation])
        row.update(state="stopped" if operation == "stop" else "starting", pid=0)
        save(path, rows)
        return True
