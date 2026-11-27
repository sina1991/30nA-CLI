"""Host operations execute exclusively in the worker; ID 1 is local."""
from contextlib import closing
import sqlite3

from thirtyna.core import UsageError
from thirtyna.address import host_address


def handle(folder, op, ip):
    if op == "lookup":
        if type(ip) is not int or ip < 2:
            raise UsageError("Remote host ID must be at least 2")
    elif op not in ("list", "ids"):
        ip = host_address(ip)
    try:
        with closing(sqlite3.connect(folder / "hosts.db")) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS hosts (ip TEXT PRIMARY KEY)")
            # Keep the original table and migrate IDs transactionally. ID 1 is
            # reserved permanently; AUTOINCREMENT prevents reuse after removal.
            db.execute("CREATE TABLE IF NOT EXISTS host_ids (id INTEGER PRIMARY KEY AUTOINCREMENT CHECK(id >= 1), ip TEXT UNIQUE)")
            db.execute("INSERT OR IGNORE INTO host_ids(id, ip) VALUES (1, NULL)")
            db.execute("DELETE FROM host_ids WHERE id > 1 AND ip NOT IN (SELECT ip FROM hosts)")
            db.execute("INSERT INTO host_ids(ip) SELECT ip FROM hosts WHERE ip NOT IN (SELECT ip FROM host_ids WHERE ip IS NOT NULL) ORDER BY ip")
            if op == "list":
                return [row[0] for row in db.execute("SELECT ip FROM hosts ORDER BY ip")]
            if op == "ids":
                return [dict(id=row[0], ip=row[1]) for row in db.execute("SELECT id, ip FROM host_ids WHERE id > 1 ORDER BY id")]
            if op == "lookup":
                row = db.execute("SELECT ip FROM host_ids WHERE id=?", (ip,)).fetchone()
                if row is None:
                    raise UsageError("Remote host ID not found")
                return row[0]
            if op in ("add", "register"):
                if op == "add":
                    db.execute("INSERT INTO hosts VALUES (?)", (ip,))
                else:
                    db.execute("INSERT OR IGNORE INTO hosts VALUES (?)", (ip,))
                row = db.execute("SELECT id FROM host_ids WHERE ip=?", (ip,)).fetchone()
                if row is None:
                    return db.execute("INSERT INTO host_ids(ip) VALUES (?)", (ip,)).lastrowid
                return row[0]
            if op == "remove":
                if not db.execute("DELETE FROM hosts WHERE ip=?", (ip,)).rowcount:
                    raise UsageError("Host not found")
                db.execute("DELETE FROM host_ids WHERE ip=?", (ip,))
            elif op == "exists":
                if not db.execute("SELECT 1 FROM hosts WHERE ip=?", (ip,)).fetchone():
                    raise UsageError("Host not found")
            else:
                raise UsageError("Unknown operation")
    except sqlite3.IntegrityError as exc:
        raise UsageError("Duplicate host") from exc
    except sqlite3.Error as exc:
        raise RuntimeError(f"Host storage failure: {exc}") from exc
