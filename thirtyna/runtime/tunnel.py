"""Private Tunnel Agent worker. No Host database access is permitted here."""
import ctypes
import ipaddress
import os
import secrets
import signal
import subprocess
import tempfile
import time

from thirtyna.core import UsageError

_TUNNELS = {}


def _parent_guard():
    """Make the SSH child terminate when the worker dies unexpectedly (Linux)."""
    parent = os.getppid()
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
        os._exit(127)
    if os.getppid() != parent:
        os._exit(127)


def _reap(token):
    item = _TUNNELS.pop(token)
    process, log = item["process"], item["log"]
    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        else:
            process.wait()
    finally:
        log.close()


def cleanup():
    for token in list(_TUNNELS):
        _reap(token)


def _prune():
    for token, item in list(_TUNNELS.items()):
        if item["process"].poll() is not None:
            _reap(token)


def handle(folder, op, argument):
    # The worker is already authenticated by the private Service Agent.
    _prune()
    if op == "list":
        return [item["info"].copy() for item in _TUNNELS.values()]
    if op == "stop":
        token = argument.get("id") if isinstance(argument, dict) else None
        if not isinstance(token, str) or token not in _TUNNELS:
            raise UsageError("Tunnel not found")
        _reap(token)
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

    # Only the Host Agent owns host storage. This request uses its authenticated IPC.
    from thirtyna.runtime.service import control, request
    request(control("ensure", "host", bootstrap=True), "exists", host)

    # All listening endpoints are constrained to loopback on their respective side.
    dest = f"[{target}]" if ":" in target else target
    spec = f"127.0.0.1:{listen}:{dest}:{target_port}"
    flag = "-L" if mode == "forward" else "-R"
    argv = ["ssh", "-N", "-T", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
            "-o", "ConnectTimeout=5", flag, spec, "--", host]
    log = tempfile.TemporaryFile(mode="w+b")
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=log, close_fds=True, preexec_fn=_parent_guard)
        # OpenSSH reports immediate bind, authentication and forwarding errors via exit code.
        time.sleep(1.0)
        if proc.poll() is not None:
            log.seek(0)
            error = log.read(1024).decode(errors="replace").strip()
            proc.wait()
            log.close()
            if any(s in error.lower() for s in ("address already in use", "remote port forwarding failed", "cannot listen to port")):
                raise UsageError("Tunnel port collision: " + error[:200])
            raise RuntimeError("SSH tunnel exited during startup: " + (error[:200] or "no diagnostics"))
        token = secrets.token_hex(12)
        info = dict(id=token, mode=mode, host=host, listen=listen,
                    target=target, target_port=target_port, pid=proc.pid, state="starting")
        _TUNNELS[token] = {"process": proc, "log": log, "info": info}
        return info.copy()
    except BaseException:
        if not log.closed:
            log.close()
        raise
