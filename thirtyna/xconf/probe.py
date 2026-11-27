"""Measure the public egress of one isolated proxy configuration."""
import ipaddress
import json
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from thirtyna.vless_test import config_for, owns_listener, stop_client


def egress(link, xray, expected=None):
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    try:
        config, _, _ = config_for(link, port)
    except ValueError:
        raise RuntimeError("Invalid or unsupported profile") from None
    with tempfile.TemporaryDirectory(prefix="30na-xconf-") as directory:
        path = Path(directory) / "client.json"
        path.write_text(json.dumps(config))
        process = subprocess.Popen(
            [str(xray), "run", "-config", str(path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 8
            while not owns_listener(process.pid, port):
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("Xray did not open the SOCKS listener")
                time.sleep(0.1)
            response = subprocess.run(
                ["curl", "-q", "-fsS", "--noproxy", "", "--proxy",
                 f"socks5h://127.0.0.1:{port}", "--connect-timeout", "8",
                 "--max-time", "20", "https://ipinfo.io/ip"],
                capture_output=True, text=True,
            )
            if response.returncode:
                raise RuntimeError(f"IPinfo request failed (curl {response.returncode})")
            try:
                address = ipaddress.ip_address(response.stdout.strip())
            except ValueError:
                raise RuntimeError("IPinfo did not return a valid IP") from None
            if not address.is_global or address.is_multicast:
                raise RuntimeError("IPinfo did not return a public IP")
            if expected is not None and address != expected:
                raise RuntimeError(f"Unexpected egress {address}")
            return str(address)
        finally:
            stop_client(process)
