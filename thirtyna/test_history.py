"""Private, append-only test observations and rolling profile classifications."""
import hashlib
import json
from pathlib import Path
import sqlite3
import statistics
import time

from thirtyna.core import UsageError

DEFAULT_POLICY = dict(good_success=0.95, bad_success=0.70, failure_margin=0.15)


def profile_key(link):
    from thirtyna.vless_test import config_for
    try:
        config, _, _ = config_for(link, 0)
        value = json.dumps(config["outbounds"], sort_keys=True, separators=(",", ":"))
    except ValueError:
        value = link.split("#", 1)[0]
    return hashlib.sha256(value.encode()).hexdigest()


def connection(path):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    path.chmod(0o600)
    db.execute("""CREATE TABLE IF NOT EXISTS observations(
        run TEXT, profile TEXT, at REAL, bytes INTEGER, summary TEXT, samples TEXT,
        PRIMARY KEY(run, profile))""")
    db.execute("CREATE INDEX IF NOT EXISTS profile_window ON observations(bytes,profile,at)")
    db.execute("CREATE INDEX IF NOT EXISTS time_window ON observations(bytes,at)")
    return db


def record(path, run, link, size, summary, samples):
    key = profile_key(link)
    db = connection(path)
    try:
        with db:
            db.execute("INSERT OR REPLACE INTO observations VALUES (?,?,?,?,?,?)",
                       (run, key, time.time(), size, json.dumps(summary), json.dumps(samples)))
    finally:
        db.close()


def aggregate(rows):
    attempts = sum(row["summary"]["requested_runs"] for row in rows)
    successes = sum(row["summary"]["successful_runs"] for row in rows)
    valid = [sample for row in rows for sample in row["samples"] if sample["status"] == "OK"]
    return dict(
        runs=len(rows), attempts=attempts, successes=successes,
        failures=attempts - successes,
        success_rate=successes / attempts if attempts else None,
        median_Mbps=statistics.median(sample["download_Mbps"] for sample in valid) if valid else None,
        median_ttfb_ms=statistics.median(sample["ttfb_ms"] for sample in valid) if valid else None,
    )


def catalog(path, size, hours=24, min_runs=3, policy=None, now=None):
    policy = DEFAULT_POLICY if policy is None else policy
    if (not isinstance(policy, dict) or set(policy) != set(DEFAULT_POLICY)
            or not all(isinstance(value, (int, float)) and not isinstance(value, bool)
                       for value in policy.values())
            or not 0 <= policy["bad_success"] <= policy["good_success"] <= 1
            or not 0 <= policy["failure_margin"] <= 1):
        raise UsageError("Invalid classification policy")
    now = time.time() if now is None else now
    db = connection(path)
    try:
        db.execute("BEGIN")
        latest = db.execute("""
            SELECT o.profile,o.at,o.summary FROM observations o
            JOIN (SELECT profile,MAX(at) at FROM observations WHERE bytes=? AND at<=? GROUP BY profile) m
            ON o.profile=m.profile AND o.at=m.at WHERE o.bytes=?""", (size, now, size)).fetchall()
        recent = db.execute(
            "SELECT profile,at,summary,samples FROM observations WHERE bytes=? AND at>=? AND at<=?",
            (size, now - max(hours, 168) * 3600, now)).fetchall()
    finally:
        db.close()
    by_profile = {}
    for key, at, summary, samples in recent:
        by_profile.setdefault(key, []).append(dict(at=at, summary=json.loads(summary),
                                                  samples=json.loads(samples)))
    entries = []
    for key, at, summary in latest:
        if at > now:
            continue
        summary = json.loads(summary)
        history = by_profile.get(key, [])
        selected = [row for row in history if row["at"] >= now - hours * 3600]
        metrics = aggregate(selected)
        windows = {label: aggregate([row for row in history if row["at"] >= now - period * 3600])
                   for label, period in (("1h", 1), ("24h", 24), ("7d", 168))}
        entries.append(dict(key=key, protocol=summary["protocol"], endpoint=summary["endpoint"],
                            label=summary["label"], route=summary["route"], last_seen=at,
                            status=summary["status"], metrics=metrics, windows=windows))
    eligible = [row for row in entries if row["metrics"]["runs"] >= min_runs
                and row["status"] != "CONFIG_ERROR"]
    fleet_attempts = sum(row["metrics"]["attempts"] for row in eligible)
    fleet_failures = sum(row["metrics"]["failures"] for row in eligible)
    mean_failure = fleet_failures / fleet_attempts if fleet_attempts else 0
    speeds = [row["metrics"]["median_Mbps"] for row in eligible
              if row["metrics"]["median_Mbps"] is not None]
    median_speed = statistics.median(speeds) if speeds else 0
    groups = {"1": [], "2": [], "3": []}
    for row in entries:
        metrics = row["metrics"]
        success = metrics["success_rate"]
        tier, reason = "2", "INSUFFICIENT_HISTORY" if metrics["runs"] else "STALE"
        if row["status"] == "CONFIG_ERROR":
            tier, reason = "3", "INVALID_OR_UNSUPPORTED_CONFIGURATION"
        elif metrics["runs"] >= min_runs and success is not None:
            if (success < policy["bad_success"]
                    or 1 - success > mean_failure + policy["failure_margin"]):
                tier, reason = "3", "HIGH_FAILURE_RATE"
            elif (success >= policy["good_success"] and 1 - success <= mean_failure
                  and (metrics["median_Mbps"] or 0) >= median_speed):
                tier, reason = "1", "RELIABLE_AND_FAST"
            else:
                reason = "RESERVE"
        row.update(tier=int(tier), reason=reason)
        groups[tier].append(row)
    for rows in groups.values():
        rows.sort(key=lambda row: (-(row["metrics"]["success_rate"] or 0),
                                   -(row["metrics"]["median_Mbps"] or 0)))
    return dict(generated_at=now, window_hours=hours, bytes=size, min_runs=min_runs,
                policy=policy, fleet_failure_rate=mean_failure,
                fleet_median_Mbps=median_speed, lists=groups)


def save_json(result, destination):
    import os
    import tempfile
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".catalog-", dir=destination.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(result, stream, indent=2)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


def display(result, destination):
    save_json(result, destination)
    print(f"WINDOW_HOURS {result['window_hours']} BYTES {result['bytes']} MIN_RUNS {result['min_runs']}")
    for tier, title in (("1", "RECOMMENDED"), ("2", "RESERVE / EVALUATING"), ("3", "UNRELIABLE")):
        print(f"LIST {tier} {title}")
        for row in result["lists"][tier]:
            metrics = row["metrics"]
            rate = metrics["success_rate"]
            percentage = "-" if rate is None else f"{rate * 100:.1f}%"
            print(f"  {row['key'][:12]} {row['protocol']} {row['endpoint']} "
                  f"success={percentage} Mbps={metrics['median_Mbps']} "
                  f"runs={metrics['runs']} {row['reason']}")
    print("CATALOG", destination)
