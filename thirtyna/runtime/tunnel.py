"""Private Tunnel worker; only Host IPC authorizes SSH destinations."""
import ctypes
import ipaddress
import os
import secrets
import shutil
import signal
import stat
import subprocess
import tempfile
import time

from thirtyna.core import UsageError

_TUNNELS = {}
STARTUP_TIMEOUT = 12.0
INITIAL_WAIT = 0.7
MAX_ACTIVE = 32
MAX_FAILED = 64


def _parent_guard(parent):
    """Arm parent-death termination, including the fork/prctl race."""
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0 or os.getppid() != parent:
        os._exit(127)


def _spawn(argv, log):
    parent = os.getpid()
    return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=log, close_fds=True,
                            preexec_fn=lambda: _parent_guard(parent))


def _children(item):
    return [p for p in (item.get("forward"), item.get("master")) if p is not None]


def _terminate(items):
    # Signal only our unreaped direct children. One deadline for all children.
    children = [p for item in items for p in _children(item)]
    for proc in children:
        if proc.poll() is None:
            proc.terminate()
    deadline = time.monotonic() + 0.4
    for proc in children:
        if proc.poll() is None:
            try:
                proc.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                proc.kill()
        proc.wait()


def _release(items):
    _terminate(items)
    for item in items:
        for key in ("master_log", "forward_log"):
            if item.get(key) is not None:
                item[key].close()
                item[key] = None
        if item.get("directory"):
            shutil.rmtree(item["directory"], ignore_errors=True)
            item["directory"] = None
        item["master"] = item["forward"] = None


def cleanup():
    _release(list(_TUNNELS.values()))
    _TUNNELS.clear()


def _remove(token):
    _release([_TUNNELS.pop(token)])


def _diagnose(log, default):
    # Report bounded, fixed labels; never return raw SSH diagnostics or credentials.
    size = os.fstat(log.fileno()).st_size
    message = os.pread(log.fileno(), 4096, max(0, size - 4096)).lower()
    if b"permission denied" in message or b"authentication failed" in message:
        return "authentication_failed"
    if b"host key verification failed" in message or b"remote host identification has changed" in message:
        return "host_key_failed"
    if b"address already in use" in message or b"cannot listen to port" in message:
        return "port_collision"
    if b"forwarding request failed" in message or b"port forwarding failed" in message or b"forwarding failed" in message:
        return "forwarding_rejected"
    if b"connection refused" in message or b"connection timed out" in message:
        return "connection_failed"
    return default


def _fail(item, reason):
    item["info"].update(state="failed", reason=reason)
    _release([item])


def _forward(item):
    info = item["info"]
    dest = f'[{info["target"]}]' if ":" in info["target"] else info["target"]
    spec = f'127.0.0.1:{info["listen"]}:{dest}:{info["target_port"]}'
    flag = "-L" if info["mode"] == "forward" else "-R"
    # Control client must not inherit additional forwards or connect independently.
    argv = ["ssh", "-F", "/dev/null", "-S", item["socket"], "-O", "forward",
            "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
            flag, spec, "--", info["host"]]
    item["forward_log"] = tempfile.TemporaryFile(mode="w+b")
    item["forward"] = _spawn(argv, item["forward_log"])


def tick():
    for item in list(_TUNNELS.values()):
        state = item["info"]["state"]
        if state == "failed":
            continue
        master = item["master"]
        if master.poll() is not None:
            _fail(item, _diagnose(item["master_log"], "ssh_exited"))
        elif state == "starting":
            if time.monotonic() >= item["deadline"]:
                _fail(item, "startup_timeout")
            elif item["forward"] is not None:
                code = item["forward"].poll()
                if code == 0:
                    item["forward_log"].close()
                    item["forward_log"] = None
                    item["forward"] = None
                    item["info"]["state"] = "ready"
                elif code is not None:
                    reason = _diagnose(item["forward_log"], "forwarding_rejected")
                    # Master diagnostics may contain the actual bind error.
                    reason = _diagnose(item["master_log"], reason)
                    _fail(item, reason)
            else:
                try:
                    is_socket = stat.S_ISSOCK(os.stat(item["socket"]).st_mode)
                except FileNotFoundError:
                    is_socket = False
                if is_socket:
                    try:
                        _forward(item)
                    except OSError:
                        _fail(item, "forwarding_command_failed")
    failed = [key for key, item in _TUNNELS.items() if item["info"]["state"] == "failed"]
    for key in failed[:-MAX_FAILED]:
        _remove(key)


def needs_tick():
    return any(item["info"]["state"] != "failed" for item in _TUNNELS.values())


def handle(folder, op, argument):
    tick()
    if op == "list":
        return [item["info"].copy() for item in _TUNNELS.values()]
    if op == "stop":
        token = argument.get("id") if isinstance(argument, dict) else None
        if not isinstance(token, str) or token not in _TUNNELS:
            raise UsageError("Tunnel not found")
        _remove(token)
        return {"id": token}
    if op != "start" or not isinstance(argument, dict):
        raise UsageError("Unknown tunnel operation")
    try:
        mode = argument["mode"]
        host = str(ipaddress.ip_address(argument["host"]))
        target = str(ipaddress.ip_address(argument["target"]))
        listen = int(argument["listen"])
        target_port = int(argument["target_port"])
        if mode not in ("forward", "reverse") or not 1 <= listen <= 65535 or not 1 <= target_port <= 65535:
            raise ValueError("Invalid tunnel parameters")
    except (KeyError, TypeError, ValueError) as exc:
        raise UsageError("Invalid tunnel parameters") from exc

    from thirtyna.runtime.service import control, request
    request(control("ensure", "host", bootstrap=True), "exists", host)
    if sum(item["info"]["state"] != "failed" for item in _TUNNELS.values()) >= MAX_ACTIVE:
        raise UsageError("Too many active tunnels")

    token = secrets.token_hex(12)
    # Short absolute path for AF_UNIX; mkdtemp is private (0700).
    directory = tempfile.mkdtemp(prefix="30na-t-", dir="/tmp")
    item = dict(directory=directory, socket=os.path.join(directory, "s"),
                master=None, forward=None, master_log=None, forward_log=None,
                deadline=time.monotonic() + STARTUP_TIMEOUT)
    try:
        item["master_log"] = tempfile.TemporaryFile(mode="w+b")
        argv = ["ssh", "-M", "-S", item["socket"], "-N", "-T",
                "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
                "-o", "ConnectTimeout=5", "-o", "ControlPersist=no",
                "-o", "ForkAfterAuthentication=no", "-o", "ClearAllForwardings=yes",
                "-o", "GatewayPorts=no", "-o", "PermitLocalCommand=no",
                "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3",
                "-o", "LogLevel=ERROR", "--", host]
        item["master"] = _spawn(argv, item["master_log"])
        item["info"] = dict(id=token, mode=mode, host=host, listen=listen,
                            target=target, target_port=target_port,
                            pid=item["master"].pid, state="starting")
        _TUNNELS[token] = item
        # Preserve prompt CLI response and immediate failures, but never infer readiness.
        deadline = time.monotonic() + INITIAL_WAIT
        while item["info"]["state"] == "starting" and time.monotonic() < deadline:
            tick()
            if item["info"]["state"] == "starting":
                time.sleep(0.025)
        if item["info"]["state"] == "failed":
            reason = item["info"]["reason"]
            _remove(token)
            if reason == "port_collision":
                raise UsageError("Tunnel port collision")
            if reason == "forwarding_rejected":
                raise UsageError("Tunnel forwarding rejected (port collision or server policy)")
            raise RuntimeError("SSH tunnel failed: " + reason)
        return item["info"].copy()
    except BaseException as exc:
        if token in _TUNNELS:
            _remove(token)
        else:
            _release([item])
        if isinstance(exc, OSError):
            raise RuntimeError("Could not launch OpenSSH tunnel") from exc
        raise
