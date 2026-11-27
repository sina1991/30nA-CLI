"""Host operations execute exclusively in the worker."""
from contextlib import closing
import ipaddress
import sqlite3

from thirtyna.core import UsageError


def handle(folder, op, ip):
    if op != "list":
        ip = str(ipaddress.ip_address(ip))
    try:
        with closing(sqlite3.connect(folder / "hosts.db")) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS hosts (ip TEXT PRIMARY KEY)")
            if op == "list":
                return [row[0] for row in db.execute("SELECT ip FROM hosts ORDER BY ip")]
            if op == "add":
                db.execute("INSERT INTO hosts VALUES (?)", (ip,))
            elif op == "remove":
                if not db.execute("DELETE FROM hosts WHERE ip=?", (ip,)).rowcount:
                    raise UsageError("Host not found")
            elif op == "exists":
                if not db.execute("SELECT 1 FROM hosts WHERE ip=?", (ip,)).fetchone():
                    raise UsageError("Host not found")
            else:
                raise UsageError("Unknown operation")
    except sqlite3.IntegrityError as exc:
        raise UsageError("Duplicate host") from exc
    except sqlite3.Error as exc:
        raise RuntimeError(f"Host storage failure: {exc}") from exc
