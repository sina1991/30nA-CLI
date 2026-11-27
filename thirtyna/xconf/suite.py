"""Manage an isolated REALITY suite through the authenticated 3x-ui API."""
import base64
from getpass import getpass
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
from urllib.error import URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import (
    HTTPCookieProcessor, HTTPRedirectHandler, ProxyHandler, Request, build_opener,
)
import uuid

PLANS = (
    ("tcp", "xtls-rprx-vision", ""), ("tcp", "", ""), ("grpc", "", ""),
    ("xhttp", "", "packet-up"), ("xhttp", "", "stream-up"),
    ("xhttp", "", "stream-one"),
)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Panel:
    def __init__(self, base):
        self.base = base.rstrip("/").removesuffix("/panel").rstrip("/")
        url = urlsplit(self.base)
        if (not url.hostname or url.username or url.password or url.query or url.fragment
                or not (url.scheme == "https" or url.scheme == "http"
                        and url.hostname in ("127.0.0.1", "localhost", "::1"))):
            raise RuntimeError("Use an HTTPS panel base URL or loopback HTTP")
        self.client = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()), NoRedirect())
        self.csrf = None
        self.refresh_csrf()
        self.call("login", {
            "username": input("Panel username: ").strip(),
            "password": getpass("Panel password: "),
            "twoFactorCode": getpass("2FA code (Enter if disabled): ").strip(),
        })
        self.refresh_csrf()

    def refresh_csrf(self):
        self.csrf = self.call("csrf-token")
        if not isinstance(self.csrf, str) or not self.csrf:
            raise RuntimeError("Panel did not issue a CSRF token")

    def call(self, path, payload=None):
        headers = {"Accept": "application/json"}
        data = None
        if payload is not None:
            headers.update({"Content-Type": "application/json", "X-CSRF-Token": self.csrf})
            data = json.dumps(payload).encode()
        try:
            with self.client.open(Request(self.base + "/" + path, data, headers), timeout=30) as response:
                result = json.load(response)
        except (URLError, ValueError, TimeoutError) as exc:
            raise RuntimeError(f"Panel request failed at {path} ({getattr(exc, 'code', type(exc).__name__)})") from None
        if not isinstance(result, dict) or result.get("success") is not True:
            raise RuntimeError(f"Panel rejected {path}")
        return result.get("obj")

    def inbounds(self):
        rows = self.call("panel/api/inbounds/list")
        if not isinstance(rows, list):
            raise RuntimeError("Invalid panel inventory")
        return rows

    def inbound(self, row):
        return self.call(f"panel/api/inbounds/get/{int(row['id'])}")


def unpack(value):
    return json.loads(value) if isinstance(value, str) else value


def public_key(reality):
    private = reality["privateKey"]
    raw = base64.urlsafe_b64decode(private + "=" * (-len(private) % 4))
    if len(raw) != 32:
        raise RuntimeError("Invalid REALITY key")
    checked = subprocess.run(
        ["openssl", "pkey", "-inform", "DER", "-pubout", "-outform", "DER"],
        input=bytes.fromhex("302e020100300506032b656e04220420") + raw,
        capture_output=True, timeout=10,
    )
    prefix = bytes.fromhex("302a300506032b656e032100")
    if checked.returncode or not checked.stdout.startswith(prefix) or len(checked.stdout) != len(prefix) + 32:
        raise RuntimeError("Cannot derive REALITY public key")
    return base64.urlsafe_b64encode(checked.stdout[len(prefix):]).decode().rstrip("=")


def stream_for(source, name, network, mode):
    stream = {"network": network, "security": "reality", "realitySettings": source}
    if network == "tcp":
        stream["tcpSettings"] = {"header": {"type": "none"}}
    elif network == "grpc":
        stream["grpcSettings"] = {"serviceName": name, "multiMode": False}
    else:
        stream["xhttpSettings"] = {"path": "/" + name, "mode": mode}
    return stream


def build_payload(name, port, flow, stream):
    client = {"id": str(uuid.uuid4()), "email": name, "enable": True, "flow": flow,
              "subId": uuid.uuid4().hex[:16]}
    return {
        "enable": True, "remark": name, "port": port, "listen": "127.0.0.1", "protocol": "vless",
        "settings": json.dumps({"clients": [client], "decryption": "none", "fallbacks": []}),
        "streamSettings": json.dumps(stream),
        "sniffing": json.dumps({"enabled": False}),
    }


def profile(row, entry, name, port, network, flow, mode):
    stream = unpack(row["streamSettings"])
    settings = unpack(row["settings"])
    clients = settings["clients"]
    if (row.get("remark") != name or int(row["port"]) != port or not row["enable"]
            or row["protocol"] != "vless" or stream["security"] != "reality"
            or stream["network"] not in (("tcp", "raw") if network == "tcp" else (network,))
            or row.get("listen") not in ("", "0.0.0.0", "127.0.0.1")
            or settings.get("decryption") != "none" or len(clients) != 1
            or clients[0].get("email") != name or clients[0].get("enable") is not True
            or clients[0].get("flow", "") != flow):
        raise RuntimeError(f"Unexpected saved configuration for {name}")
    reality = stream["realitySettings"]
    params = dict(encryption="none", security="reality", type=network,
                  sni=reality["serverNames"][0], fp="chrome", pbk=public_key(reality),
                  sid=reality["shortIds"][0], spx="/")
    if flow:
        params["flow"] = flow
    if network == "grpc":
        params["serviceName"] = stream["grpcSettings"]["serviceName"]
    elif network == "xhttp":
        transport = stream["xhttpSettings"]
        if transport["mode"] != mode:
            raise RuntimeError(f"Unexpected XHTTP mode for {name}")
        params.update(path=transport["path"], mode=mode)
    return f"vless://{uuid.UUID(clients[0]['id'])}@{entry}:{port}?{urlencode(params)}#{name}"


def save_profiles(path, links):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".xconf-")
    try:
        with os.fdopen(fd, "w") as file:
            file.write("\n".join(links) + "\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def validate_new_inbounds(payloads):
    directory = Path("/usr/local/x-ui/bin")
    xray = next((path for path in sorted(directory.glob("xray*"))
                 if path.is_file() and os.access(path, os.X_OK)), None)
    if xray is None:
        raise RuntimeError("Run -make config on the standard 3x-ui server with Xray installed")
    runtime = json.loads((directory / "config.json").read_text())
    for payload in payloads:
        inbound = {key: payload[key] for key in ("port", "listen", "protocol")}
        inbound.update(tag=payload["remark"], settings=unpack(payload["settings"]),
                       streamSettings=unpack(payload["streamSettings"]))
        runtime["inbounds"].append(inbound)
    with tempfile.TemporaryDirectory(prefix="30na-xconf-validation-") as temporary:
        config = Path(temporary) / "config.json"
        config.write_text(json.dumps(runtime))
        checked = subprocess.run(
            [str(xray), "run", "-test", "-config", str(config)], cwd=directory,
            capture_output=True, timeout=30,
        )
    if checked.returncode:
        raise RuntimeError("Installed Xray rejected the proposed suite before any panel writes")


def export_suite(args):
    try:
        _export_suite(args)
    except (KeyError, ValueError, TypeError, IndexError, subprocess.TimeoutExpired):
        raise RuntimeError("Unexpected panel configuration or key derivation failure") from None


def _export_suite(args):
    panel = Panel(args.panel or input("Panel base URL: ").strip())
    rows = panel.inbounds()
    jobs = []
    for port, (network, flow, mode) in enumerate(PLANS, 25001):
        name = f"xconf-reality-{port}"
        matches = [row for row in rows if row.get("remark") == name]
        if len(matches) > 1:
            raise RuntimeError(f"Duplicate inbound {name}")
        if not matches:
            if not args.make:
                raise RuntimeError(f"Missing inbound {name}")
            if any(int(row["port"]) == port for row in rows):
                raise RuntimeError(f"Panel port conflict on {port}")
            with socket.socket() as probe:
                probe.bind(("0.0.0.0", port))
        jobs.append((name, port, network, flow, mode, panel.inbound(matches[0]) if matches else None))

    source = None
    if any(job[-1] is None for job in jobs):
        sources = [row for row in rows if int(row["port"]) == 443 and row["protocol"] == "vless"]
        if len(sources) != 1:
            raise RuntimeError("Expected one VLESS source inbound on port 443")
        source_row = panel.inbound(sources[0])
        source_stream = unpack(source_row["streamSettings"])
        if not source_row["enable"] or source_stream["security"] != "reality" or source_stream["network"] not in ("tcp", "raw"):
            raise RuntimeError("Source must be an enabled TCP/REALITY inbound")
        source = source_stream["realitySettings"]
        public_key(source)

    payloads = {
        port: build_payload(name, port, flow, stream_for(source, name, network, mode))
        for name, port, network, flow, mode, row in jobs if row is None
    }
    for name, port, network, flow, mode, row in jobs:
        if row is not None:
            profile(row, args.entry, name, port, network, flow, mode)
    if payloads:
        validate_new_inbounds(payloads.values())

    links = []
    for name, port, network, flow, mode, row in jobs:
        if row is None:
            panel.call("panel/api/inbounds/add", payloads[port])
            matches = [entry for entry in panel.inbounds() if entry.get("remark") == name]
            if len(matches) != 1:
                raise RuntimeError(f"Panel did not verify {name}")
            row = panel.inbound(matches[0])
        links.append(profile(row, args.entry, name, port, network, flow, mode))
        print(f"PANEL_VERIFIED {row['id']} {name}", flush=True)
    save_profiles(args.output, links)
    print(f"CONFIG_SAVED {args.output}")
