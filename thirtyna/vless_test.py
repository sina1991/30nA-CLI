"""Run isolated Xray clients and measure VLESS profiles from the controller."""
import csv
import datetime
import json
import os
from pathlib import Path
import re
import socket
import statistics
import subprocess
import tempfile
import time
from urllib.parse import parse_qs, unquote, urlsplit

from thirtyna.core import UsageError

DOWNLOAD_URL = "https://speed.cloudflare.com/__down"


def load_profiles(path):
    profiles = []
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        for link in re.findall(r"vless://[^\s]+", line):
            profiles.append(dict(id=len(profiles) + 1, line=line_number,
                                 link=link.rstrip("'\"`")))
    if not profiles:
        raise UsageError("No vless:// profiles found in " + str(path))
    return profiles


def config_for(link, port):
    uri = urlsplit(link)
    query = parse_qs(uri.query, keep_blank_values=True)

    def value(name, default=""):
        return query.get(name, [default])[0]

    if not uri.hostname or not uri.port or not uri.username:
        raise ValueError("INVALID_LINK")
    if value("type", "tcp").lower() not in ("tcp", "raw"):
        raise ValueError("UNSUPPORTED_TRANSPORT")
    if value("headerType", "none") not in ("", "none"):
        raise ValueError("UNSUPPORTED_HEADER")
    if value("encryption", "none") not in ("", "none"):
        raise ValueError("UNSUPPORTED_ENCRYPTION")
    security = value("security", "none").lower()
    if security not in ("none", "tls", "reality"):
        raise ValueError("UNSUPPORTED_SECURITY")
    user = dict(id=unquote(uri.username), encryption="none")
    if value("flow"):
        user["flow"] = value("flow")
    stream = dict(network="tcp", security=security)
    if security == "reality":
        if not value("pbk") or not value("sni"):
            raise ValueError("MISSING_REALITY_PARAMETER")
        stream["realitySettings"] = dict(
            serverName=value("sni"), fingerprint=value("fp", "chrome"),
            password=value("pbk"), shortId=value("sid"), spiderX=value("spx", "/"))
    elif security == "tls":
        tls = dict(serverName=value("sni", uri.hostname))
        if value("fp"):
            tls["fingerprint"] = value("fp")
        if value("alpn"):
            tls["alpn"] = value("alpn").split(",")
        tls["allowInsecure"] = value("allowInsecure", "0").lower() in ("1", "true")
        stream["tlsSettings"] = tls
    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [{"listen": "127.0.0.1", "port": port, "protocol": "socks",
                      "settings": {"auth": "noauth", "udp": False}}],
        "outbounds": [{"protocol": "vless",
                       "settings": {"vnext": [{"address": uri.hostname, "port": uri.port,
                                                "users": [user]}]},
                       "streamSettings": stream}],
    }
    endpoint = f"{uri.hostname}:{uri.port}"
    label = " ".join(unquote(uri.fragment).split()) or endpoint
    return config, endpoint, label


def owns_listener(pid, port):
    try:
        inodes = {row.split()[9] for row in Path("/proc/net/tcp").read_text().splitlines()[1:]
                  if row.split()[3] == "0A" and row.split()[1] == f"0100007F:{port:04X}"}
        sockets = {"socket:[" + inode + "]" for inode in inodes}
        return any(os.readlink(fd) in sockets for fd in Path(f"/proc/{pid}/fd").iterdir())
    except OSError:
        return False


def stop_client(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def measure_profile(profile, args, directory, routes):
    name = f"profile-{profile['id']:03d}"
    summary = dict(profile=name, source_line=profile["line"], label="", endpoint="",
                   route="", status="FAILED", successful_runs=0, requested_runs=args.count,
                   median_download_Mbps=None, median_ttfb_ms=None)
    samples = []
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix=".client-", dir=directory) as temporary:
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            config, endpoint, label = config_for(profile["link"], port)
            route = routes.get(endpoint, label)
            summary.update(endpoint=endpoint, label=label, route=route)
            print("  " + route, flush=True)
            config_path = Path(temporary) / "config.json"
            config_path.write_text(json.dumps(config))
            config_path.chmod(0o600)
            with (directory / (name + ".log")).open("wb") as log:
                checked = subprocess.run(
                    [str(args.xray), "run", "-test", "-config", str(config_path)],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=log, timeout=15)
                if checked.returncode:
                    raise RuntimeError("CONFIG_ERROR")
                process = subprocess.Popen(
                    [str(args.xray), "run", "-config", str(config_path)],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=log)
                deadline = time.monotonic() + 10
                while not owns_listener(process.pid, port):
                    if process.poll() is not None:
                        raise RuntimeError("CLIENT_EXITED")
                    if time.monotonic() >= deadline:
                        raise RuntimeError("CLIENT_START_TIMEOUT")
                    time.sleep(0.1)
                for attempt in range(1, args.count + 1):
                    if process.poll() is not None or not owns_listener(process.pid, port):
                        raise RuntimeError("CLIENT_EXITED")
                    row = dict(profile=name, endpoint=endpoint, route=route, run=attempt, status="FAILED", curl_exit=None,
                               http=None, download_bytes=None, ttfb_ms=None,
                               total_s=None, download_Mbps=None)
                    try:
                        result = subprocess.run(
                            ["curl", "-q", "--silent", "--show-error", "--fail",
                             "--noproxy", "", "--proxy", f"socks5h://127.0.0.1:{port}",
                             "--connect-timeout", str(args.connect_timeout),
                             "--max-time", str(args.timeout), "--output", "/dev/null",
                             "--write-out",
                             "%{http_code} %{size_download} %{time_starttransfer} %{time_total} %{speed_download}",
                             DOWNLOAD_URL + "?bytes=" + str(args.bytes)],
                            capture_output=True, text=True, timeout=args.timeout + 5)
                        row["curl_exit"] = result.returncode
                        if result.stderr:
                            log.write(result.stderr.encode())
                            log.flush()
                        values = result.stdout.split()
                        if len(values) == 5:
                            http, size, ttfb, total, speed = values
                            row.update(http=http, download_bytes=int(float(size)),
                                       ttfb_ms=round(float(ttfb) * 1000, 2),
                                       total_s=round(float(total), 3),
                                       download_Mbps=round(float(speed) * 8 / 1_000_000, 3))
                            if result.returncode == 0:
                                row["status"] = "OK" if row["download_bytes"] == args.bytes else "INCOMPLETE"
                    except subprocess.TimeoutExpired:
                        row["status"] = "TIMEOUT"
                    samples.append(row)
                    print(f"  run={attempt} {row['status']} speed={row['download_Mbps']} Mbps "
                          f"TTFB={row['ttfb_ms']} ms", flush=True)
                    if attempt < args.count:
                        time.sleep(args.interval)
    except ValueError:
        summary["status"] = "CONFIG_ERROR"
    except RuntimeError as exc:
        summary["status"] = str(exc)
    except subprocess.TimeoutExpired:
        summary["status"] = "CLIENT_TIMEOUT"
    except OSError:
        summary["status"] = "SYSTEM_ERROR"
    finally:
        stop_client(process)
    valid = [row for row in samples if row["status"] == "OK"]
    summary["successful_runs"] = len(valid)
    if summary["status"] == "FAILED":
        summary["status"] = "OK" if len(valid) == args.count else "PARTIAL" if valid else "FAILED"
    if valid:
        summary["median_download_Mbps"] = statistics.median(row["download_Mbps"] for row in valid)
        summary["median_ttfb_ms"] = statistics.median(row["ttfb_ms"] for row in valid)
    return summary, samples


def write_reports(directory, summaries, details):
    fields = {
        "summary": ["profile", "source_line", "label", "endpoint", "route", "status",
                    "successful_runs", "requested_runs", "median_download_Mbps", "median_ttfb_ms"],
        "details": ["profile", "endpoint", "route", "run", "status", "curl_exit",
                    "http", "download_bytes", "ttfb_ms", "total_s", "download_Mbps"],
    }
    for name, rows in (("summary", summaries), ("details", details)):
        (directory / (name + ".json")).write_text(json.dumps(rows, indent=2))
        with (directory / (name + ".csv")).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields[name])
            writer.writeheader()
            writer.writerows(rows)
    ranked = sorted(summaries, key=lambda row: (
        -row["successful_runs"], -(row["median_download_Mbps"] or 0),
        row["median_ttfb_ms"] if row["median_ttfb_ms"] is not None else float("inf")))
    lines = ["# VLESS test report", "",
             "| Profile | Route | Status | Success | Median Mbps | TTFB ms |",
             "| --- | --- | --- | --- | --- | --- |"]
    for row in ranked:
        route = row["route"].replace("|", "/")
        lines.append(f"| {row['profile']} | {route} | {row['status']} | "
                     f"{row['successful_runs']}/{row['requested_runs']} | "
                     f"{row['median_download_Mbps']} | {row['median_ttfb_ms']} |")
    report = "\n".join(lines) + "\n"
    (directory / "report.md").write_text(report)
    return report


def execute(args, profiles):
    routes = {}
    route_file = args.routes or args.profiles.with_name("routes.json")
    if args.routes is not None or route_file.exists():
        try:
            routes = json.loads(route_file.read_text())
        except ValueError as exc:
            raise UsageError("Invalid route-label JSON") from exc
        if not isinstance(routes, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                   for k, v in routes.items()):
            raise UsageError("Routes must be a JSON object mapping host:port to route text")
    args.output.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(
        prefix=datetime.datetime.now().strftime("%Y%m%d-%H%M%S-"), dir=args.output))
    summaries, details = [], []
    print("REPORT_DIRECTORY", directory, flush=True)
    try:
        for number, profile in enumerate(profiles, 1):
            print(f"[{number}/{len(profiles)}] profile-{profile['id']:03d}", flush=True)
            summary, samples = measure_profile(profile, args, directory, routes)
            summaries.append(summary)
            details.extend(samples)
            write_reports(directory, summaries, details)
    except KeyboardInterrupt:
        write_reports(directory, summaries, details)
        print("INTERRUPTED; completed profiles saved in", directory)
        return 130
    print(write_reports(directory, summaries, details))
    print("REPORT_DIRECTORY", directory)
    return 0 if all(row["status"] == "OK" for row in summaries) else 1
