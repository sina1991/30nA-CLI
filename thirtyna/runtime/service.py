"""Linux per-user service supervisor and authenticated loopback workers."""
import argparse
import fcntl
import hmac
import json
import os
from pathlib import Path
import secrets
import select
import socket
import stat
import subprocess
import sys

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


def connect(info):
    conn = socket.create_connection(("127.0.0.1", info["port"]), timeout=4)
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


def request(info, op, ip=None):
    conn, stream = connect(info)
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


def worker(listener, lifetime):
    with lifetime.makefile("rb") as config:
        name, key = read(config)
    last = None
    try:
        while True:
            timeout = 0.1 if name == "tunnel" and tunnel.needs_tick() else None
            ready, _, _ = select.select([lifetime, listener], [], [], timeout)
            if lifetime in ready:
                return
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
        self.port_channel, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        with child:
            self.allocator = spawn("ports", child.fileno())

    def stop(self, name):
        if name in self.children:
            proc, lifetime, _ = self.children.pop(name)
            lifetime.close()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                # Unreaped direct child: its PID cannot have been recycled.
                proc.kill()
                proc.wait()

    def start(self, name):
        preferred = int(os.environ.get("THIRTYNA_PREFERRED_PORT", "0"))
        self.port_channel.send(str(preferred).encode())
        data, fds, _, _ = socket.recv_fds(self.port_channel, 512, 1)
        if not fds:
            raise RuntimeError("Port Agent unavailable")
        lease = json.loads(data)
        with socket.socket(fileno=fds[0]) as listener:
            lifetime, child = socket.socketpair()
            with child:
                proc = spawn("worker", listener.fileno(), child.fileno())
            info = dict(port=lease["port"], collision=lease["collision"], pid=proc.pid,
                        key=secrets.token_hex(32), address="127.0.0.1")
            self.children[name] = proc, lifetime, info
            lifetime.sendall(json.dumps([name, info["key"]]).encode() + b"\n")

    def dispatch(self, action, name):
        if name not in REGISTRY:
            raise ValueError("Unknown agent")
        if action == "stop":
            self.stop(name)
        if name in self.children and self.children[name][0].poll() is not None:
            self.stop(name)
        if action == "ensure" and name not in self.children:
            self.start(name)
        result = dict(state="down", service_pid=os.getpid(), port_pid=self.allocator.pid)
        if name in self.children:
            info = self.children[name][2]
            reply = request(info, "ready")
            if reply["pid"] != info["pid"]:
                raise RuntimeError("Unexpected worker PID")
            result.update(info, state="ready", last=reply["last"])
            if action != "ensure":
                del result["key"]
        return result

    def close(self):
        for name in list(self.children):
            self.stop(name)
        self.port_channel.close()
        self.allocator.wait()


def serve(listener, lease):
    key = json.loads((folder() / ".runtime/service.json").read_text())["key"]
    supervisor = Supervisor()
    try:
        while True:
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
        target = {"ports": ports.serve, "worker": worker}[args.action]
        target(*(socket.socket(fileno=fd) for fd in args.fds))
