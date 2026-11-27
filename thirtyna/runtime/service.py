"""Linux per-user service supervisor and authenticated loopback workers."""
import argparse
import fcntl
import hmac
import json
import os
from pathlib import Path
import secrets
import select
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time

from thirtyna.core import UsageError
from thirtyna.runtime import host, ports, tunnel

REGISTRY = {"host": host.handle, "tunnel": tunnel.handle}
MODULE = "thirtyna.runtime.service"


def folder():
    return ((Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
             / "30na").resolve())


def send(stream, value):
    stream.write(json.dumps(value).encode() + b"\n")


def read(stream):
    line = stream.readline()
    if not line:
        raise ConnectionError("Agent disconnected")
    return json.loads(line)


def spawn(role, *fds):
    # Pin imports to this release regardless of the invoking shell's cwd.
    return subprocess.Popen([sys.executable, "-m", MODULE, role, *map(str, fds)],
                            cwd=Path(__file__).resolve().parents[2], pass_fds=fds,
                            env=dict(os.environ, XDG_DATA_HOME=str(folder().parent)),
                            start_new_session=True, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def control(action, name="host", bootstrap=False):
    private = folder() / ".runtime"
    if not bootstrap and not private.exists():
        return {"state": "down"}
    folder().mkdir(mode=0o700, parents=True, exist_ok=True)
    private.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = private.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise RuntimeError("Runtime directory must be private to its owner")
    state = private / "service.json"
    with (private / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if state.exists():
            info = json.loads(state.read_text())
            try:
                conn, stream = connect(info)
            except (ConnectionError, OSError, ValueError, RuntimeError):
                # A live supervisor retains the lease even if its handshake stalls.
                with (private / "lease").open("a") as lease:
                    try:
                        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError as exc:
                        raise RuntimeError("Service Agent unresponsive") from exc
            else:
                with conn, stream:
                    return command(stream, info, action, name)
        if not bootstrap:
            return {"state": "down"}
        with (private / "lease").open("a") as lease, socket.socket() as listener:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            info = dict(port=listener.getsockname()[1], key=secrets.token_hex(32))
            pending = state.with_suffix(".tmp")
            pending.write_text(json.dumps(info))
            pending.replace(state)
            spawn("service", listener.fileno(), lease.fileno())
        conn, stream = connect(info)
        with conn, stream:
            return command(stream, info, action, name)


def command(stream, info, action, name):
    nonce = read(stream)
    payload = [action, name]
    send(stream, [payload, signature(info["key"], nonce, payload)])
    result = read(stream)
    if "error" in result:
        raise RuntimeError(result["error"])
    return result


def connect(info, timeout=4):
    conn = socket.create_connection(("127.0.0.1", info["port"]), timeout=timeout)
    stream = conn.makefile("rwb", buffering=0)
    try:
        challenge = secrets.token_hex(32)
        send(stream, challenge)
        proof = json.loads(stream.readline(256))
        if not hmac.compare_digest(proof, signature(info["key"], challenge, "identity")):
            raise RuntimeError("Agent identity mismatch")
    except BaseException:
        stream.close()
        conn.close()
        raise
    return conn, stream


def authenticate(stream, key):
    challenge = json.loads(stream.readline(256))
    send(stream, signature(key, challenge, "identity"))
    nonce = secrets.token_hex(24)
    send(stream, nonce)
    payload, proof = json.loads(stream.readline(2048))
    if not hmac.compare_digest(proof, signature(key, nonce, payload)):
        raise ValueError("Invalid credentials")
    return nonce, payload


def signature(key, nonce, payload):
    data = json.dumps([nonce, payload], separators=(",", ":")).encode()
    return hmac.digest(bytes.fromhex(key), data, "sha256").hex()


def request(info, op, ip=None, timeout=4):
    conn, stream = connect(info, timeout=timeout)
    with conn, stream:
        nonce = read(stream)
        payload = [op, ip, os.getpid()]
        send(stream, [payload, signature(info["key"], nonce, payload)])
        result, proof = read(stream)
        if not hmac.compare_digest(proof, signature(info["key"], nonce, ["result", payload, result])):
            raise RuntimeError("Worker identity mismatch")
        if "usage" in result:
            raise UsageError(result["usage"])
        if "error" in result:
            raise RuntimeError(result["error"])
        return result


def worker(listener, lifetime, recovery_fd=None):
    packet = lifetime.recv(4096)
    if not packet:
        return
    config = json.loads(packet)
    name, key = config["name"], config["key"]
    if name == "tunnel":
        tunnel.initialize(recovery_fd, config["directory"], config["host"])
    last = None
    try:
        while True:
            timeout = 0.1 if name == "tunnel" and tunnel.needs_tick() else None
            ready, _, _ = select.select([lifetime, listener], [], [], timeout)
            if lifetime in ready:
                packet = lifetime.recv(4096)
                if not packet:
                    return
                if name == "tunnel":
                    tunnel.set_host(json.loads(packet))
            if name == "tunnel":
                tunnel.tick()
            if listener not in ready:
                continue
            conn, _ = listener.accept()
            with conn, conn.makefile("rwb", buffering=0) as stream:
                conn.settimeout(1)
                try:
                    nonce, payload = authenticate(stream, key)
                    op, ip, caller = payload
                    result = {"pid": os.getpid()}
                    if op == "ready":
                        result["last"] = last
                    else:
                        result["value"] = REGISTRY[name](folder(), op, ip)
                        last = dict(op=op, requester=caller, processor=os.getpid())
                except UsageError as exc:
                    result = {"usage": str(exc)}
                except RuntimeError as exc:
                    result = {"error": str(exc)}
                except (ValueError, TypeError, OSError):
                    continue
                try:
                    send(stream, [result, signature(key, nonce, ["result", payload, result])])
                except OSError:
                    pass

    finally:
        if name == "tunnel":
            tunnel.cleanup()


class Supervisor:
    def __init__(self):
        self.children = {}
        self.tunnel_recovery_fd = None
        self.tunnel_directory = None
        self.recovery_attempts = []
        self.recovery_warning = None
        self.port_channel, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        with child:
            self.allocator = spawn("ports", child.fileno())

    def stop(self, name, preserve_recovery=False):
        if name in self.children:
            proc, lifetime, _ = self.children.pop(name)
            lifetime.close()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                # Unreaped direct child: its PID cannot have been recycled.
                proc.kill()
                proc.wait()
        if name == "tunnel":
            if self.tunnel_directory is not None:
                shutil.rmtree(self.tunnel_directory, ignore_errors=True)
                self.tunnel_directory = None
            if not preserve_recovery:
                if self.tunnel_recovery_fd is not None:
                    os.close(self.tunnel_recovery_fd)
                    self.tunnel_recovery_fd = None
                self.recovery_attempts = []

    def ensure_host(self):
        if "host" in self.children and self.children["host"][0].poll() is not None:
            self.stop("host")
        if "host" not in self.children:
            self.start("host")

    def start(self, name):
        preferred = int(os.environ.get("THIRTYNA_PREFERRED_PORT", "0"))
        self.port_channel.send(str(preferred).encode())
        data, fds, _, _ = socket.recv_fds(self.port_channel, 512, 1)
        if not fds:
            raise RuntimeError("Port Agent unavailable")
        lease = json.loads(data)
        with socket.socket(fileno=fds[0]) as listener:
            lifetime, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            lifetime.settimeout(1)
            key = secrets.token_hex(32)
            config = dict(name=name, key=key)
            extra = []
            try:
                if name == "tunnel":
                    # The supervisor keeps an opaque, RAM-only descriptor across worker
                    # crashes. Only the Tunnel worker interprets the recovery journal.
                    if self.tunnel_recovery_fd is None:
                        self.tunnel_recovery_fd = os.memfd_create("30na-tunnel-recovery")
                    self.tunnel_directory = tempfile.mkdtemp(prefix="30na-w-", dir="/tmp")
                    config.update(directory=self.tunnel_directory, host=self.children["host"][2])
                    extra = [self.tunnel_recovery_fd]
                with child:
                    proc = spawn("worker", listener.fileno(), child.fileno(), *extra)
                info = dict(port=lease["port"], collision=lease["collision"], pid=proc.pid,
                            key=key, address="127.0.0.1")
                self.children[name] = proc, lifetime, info
                lifetime.sendall(json.dumps(config).encode())
            except BaseException:
                child.close()
                if name in self.children:
                    self.stop(name, preserve_recovery=True)
                else:
                    lifetime.close()
                    if name == "tunnel" and self.tunnel_directory is not None:
                        shutil.rmtree(self.tunnel_directory, ignore_errors=True)
                        self.tunnel_directory = None
                raise

    def refresh_tunnel_host(self):
        # Private inherited channel, not a client-supplied authorization reference.
        # No nested supervisor request from Tunnel: avoids lock inversion on concurrent CLI calls.
        self.children["tunnel"][1].sendall(json.dumps(self.children["host"][2]).encode())

    def recover_tunnel(self):
        child = self.children.get("tunnel")
        if child is None or child[0].poll() is None:
            return
        fd = self.tunnel_recovery_fd
        if fd is None or os.fstat(fd).st_size == 0:
            self.stop("tunnel")
            return
        now = time.monotonic()
        self.recovery_attempts = [t for t in self.recovery_attempts if now - t < 60]
        if len(self.recovery_attempts) >= 3:
            self.stop("tunnel")
            self.recovery_warning = "recovery_rate_limit"
            return
        self.recovery_attempts.append(now)
        self.stop("tunnel", preserve_recovery=True)
        try:
            self.ensure_host()
            self.start("tunnel")
        except (OSError, RuntimeError, ValueError):
            self.stop("tunnel")
            self.recovery_warning = "recovery_worker_start_failed"

    def dispatch(self, action, name):
        if name not in REGISTRY:
            raise ValueError("Unknown agent")
        if action == "stop":
            self.stop(name)
            if name == "tunnel":
                self.recovery_warning = None
        else:
            # A direct child can die after poll() but before the authenticated
            # readiness exchange. Retry lifecycle lookup once only if its death
            # is independently confirmed; never retry a live identity mismatch.
            for attempt in range(2):
                if name == "tunnel":
                    self.recover_tunnel()
                elif name in self.children and self.children[name][0].poll() is not None:
                    self.stop(name)
                if action == "ensure":
                    if name == "tunnel":
                        self.ensure_host()
                    if name not in self.children:
                        self.start(name)
                if name not in self.children:
                    break
                proc, _, info = self.children[name]
                try:
                    if action == "ensure" and name == "tunnel":
                        self.refresh_tunnel_host()
                    reply = request(info, "ready")
                    if reply["pid"] != info["pid"]:
                        raise RuntimeError("Unexpected worker PID")
                except (OSError, ValueError, RuntimeError):
                    if attempt:
                        raise
                    try:
                        proc.wait(timeout=0.25)
                    except subprocess.TimeoutExpired:
                        raise RuntimeError("Live worker readiness exchange failed")
                    if name == "tunnel":
                        self.recover_tunnel()
                    else:
                        self.stop(name)
                    continue
                break
        result = dict(state="down", service_pid=os.getpid(), port_pid=self.allocator.pid)
        if name in self.children:
            result.update(info, state="ready", last=reply["last"])
            if action != "ensure":
                del result["key"]
        result["domain_support"] = True
        if name == "tunnel":
            result["tunnel_protocol"] = 2
            if self.recovery_warning:
                result["recovery_warning"] = self.recovery_warning
        return result

    def close(self):
        for name in list(self.children):
            self.stop(name)
        self.stop("tunnel")
        self.port_channel.close()
        self.allocator.wait()


def serve(listener, lease):
    key = json.loads((folder() / ".runtime/service.json").read_text())["key"]
    supervisor = Supervisor()
    try:
        while True:
            # Periodic crash detection is active only while a Tunnel worker exists.
            timeout = 0.25 if "tunnel" in supervisor.children else None
            ready, _, _ = select.select([listener], [], [], timeout)
            if not ready:
                supervisor.recover_tunnel()
                continue
            conn, _ = listener.accept()
            with conn, conn.makefile("rwb", buffering=0) as stream:
                conn.settimeout(5)
                try:
                    _, (action, name) = authenticate(stream, key)
                    if action == "shutdown":
                        supervisor.close()
                        listener.close()
                        os.close(lease)
                        send(stream, {"state": "down"})
                        return
                    send(stream, supervisor.dispatch(action, name))
                except (OSError, ValueError, TypeError, RuntimeError) as exc:
                    try:
                        send(stream, {"error": str(exc)})
                    except OSError:
                        pass
    finally:
        supervisor.close()


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("action", choices=("service", "ports", "worker", "status", "stop", "shutdown"))
    cli.add_argument("fds", type=int, nargs="*")
    args = cli.parse_args()
    if args.action in ("status", "stop", "shutdown"):
        print(json.dumps(control(args.action)))
    else:
        if args.action == "service":
            serve(socket.socket(fileno=args.fds[0]), args.fds[1])
            sys.exit(0)
        if args.action == "worker":
            worker(socket.socket(fileno=args.fds[0]), socket.socket(fileno=args.fds[1]),
                   args.fds[2] if len(args.fds) == 3 else None)
        else:
            ports.serve(*(socket.socket(fileno=fd) for fd in args.fds))
