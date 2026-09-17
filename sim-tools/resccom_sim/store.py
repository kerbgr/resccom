"""Encrypted-at-rest local subscriber store (WBS 3.2-a).

The file on disk is always ciphertext (crypto.py). Each operation decrypts
it into a 0600 temp file, runs a normal SQLite statement against it, and
re-encrypts the result back to disk. A store that doesn't exist yet starts
from a fresh empty in-memory database.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Callable, TypeVar

from .crypto import decrypt, encrypt
from .model import Subscriber

SCHEMA = """
CREATE TABLE IF NOT EXISTS subscribers (
    imsi TEXT PRIMARY KEY,
    key TEXT NOT NULL,
    opc TEXT NOT NULL,
    amf TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    node_class_notes TEXT NOT NULL DEFAULT '',
    lbo_roaming_allowed INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
"""

T = TypeVar("T")


class SubscriberExistsError(Exception):
    def __init__(self, imsi: str) -> None:
        super().__init__(f"subscriber already exists: {imsi}")
        self.imsi = imsi


class SubscriberConflictError(Exception):
    """`add_if_missing` found an existing subscriber with the same IMSI but different fields."""

    def __init__(self, imsi: str) -> None:
        super().__init__(
            f"subscriber {imsi} already exists with different key/opc/amf/label/notes -- "
            "not touching it (use `sub remove` first if this is intentional)"
        )
        self.imsi = imsi


class SubscriberStore:
    def __init__(self, path: Path, passphrase: str) -> None:
        self.path = path
        self.passphrase = passphrase

    def _load_plaintext_db(self) -> bytes:
        if not self.path.exists():
            conn = sqlite3.connect(":memory:")
            try:
                conn.executescript(SCHEMA)
                return conn.serialize()
            finally:
                conn.close()
        return decrypt(self.path.read_bytes(), self.passphrase)

    def _with_db(self, fn: Callable[[sqlite3.Connection], T], *, mutate: bool) -> T:
        plaintext = self._load_plaintext_db()
        fd, tmp_name = tempfile.mkstemp(prefix="resccom-sim-", suffix=".db")
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            os.chmod(tmp, 0o600)
            tmp.write_bytes(plaintext)
            conn = sqlite3.connect(tmp)
            try:
                conn.executescript(SCHEMA)
                # `CREATE TABLE IF NOT EXISTS` doesn't touch a table that
                # already exists under an older schema -- a store written
                # before this field existed loads here with no
                # lbo_roaming_allowed column at all. Add it, defaulting
                # existing rows to 1 (True): "records written before this
                # field load as True" (TASKS.md 3.3-c v2e).
                cols = {row[1] for row in conn.execute("PRAGMA table_info(subscribers)")}
                if "lbo_roaming_allowed" not in cols:
                    conn.execute(
                        "ALTER TABLE subscribers ADD COLUMN lbo_roaming_allowed INTEGER NOT NULL DEFAULT 1"
                    )
                result = fn(conn)
                conn.commit()
            finally:
                conn.close()
            if mutate:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_bytes(encrypt(tmp.read_bytes(), self.passphrase))
                os.chmod(self.path, 0o600)
            return result
        finally:
            tmp.unlink(missing_ok=True)

    def add(self, sub: Subscriber) -> None:
        def _add(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO subscribers"
                " (imsi, key, opc, amf, label, node_class_notes, lbo_roaming_allowed, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    sub.imsi, sub.key, sub.opc, sub.amf, sub.label, sub.node_class_notes,
                    int(sub.lbo_roaming_allowed), sub.created_at,
                ),
            )

        try:
            self._with_db(_add, mutate=True)
        except sqlite3.IntegrityError as exc:
            raise SubscriberExistsError(sub.imsi) from exc

    def add_if_missing(self, sub: Subscriber) -> bool:
        """Add `sub`, tolerating an identical existing subscriber with the same IMSI.

        Returns True if a row was inserted, False if an identical one was
        already there. Raises SubscriberConflictError if the existing row's
        key/opc/amf/label/node_class_notes differ from `sub`'s -- this never
        silently overwrites a subscriber it didn't expect. For rigs sharing
        one dev store (WBS 3.2-e): each rig adds its own IMSI this way
        instead of `rm -f`-ing the store, so the store becomes the union of
        every rig's test subscribers.
        """

        def _add_if_missing(conn: sqlite3.Connection) -> bool:
            row = conn.execute(
                "SELECT key, opc, amf, label, node_class_notes, lbo_roaming_allowed"
                " FROM subscribers WHERE imsi = ?",
                (sub.imsi,),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO subscribers"
                    " (imsi, key, opc, amf, label, node_class_notes, lbo_roaming_allowed, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        sub.imsi, sub.key, sub.opc, sub.amf, sub.label, sub.node_class_notes,
                        int(sub.lbo_roaming_allowed), sub.created_at,
                    ),
                )
                return True
            existing = (row[0], row[1], row[2], row[3], row[4], bool(row[5]))
            wanted = (sub.key, sub.opc, sub.amf, sub.label, sub.node_class_notes, sub.lbo_roaming_allowed)
            if existing != wanted:
                raise SubscriberConflictError(sub.imsi)
            return False

        return self._with_db(_add_if_missing, mutate=True)

    def list_all(self) -> list[Subscriber]:
        def _list(conn: sqlite3.Connection) -> list[Subscriber]:
            rows = conn.execute(
                "SELECT imsi, key, opc, label, node_class_notes, amf, lbo_roaming_allowed, created_at"
                " FROM subscribers ORDER BY created_at"
            ).fetchall()
            return [
                Subscriber(
                    imsi=row[0], key=row[1], opc=row[2], label=row[3],
                    node_class_notes=row[4], amf=row[5],
                    lbo_roaming_allowed=bool(row[6]), created_at=row[7],
                )
                for row in rows
            ]

        return self._with_db(_list, mutate=False)

    def set_lbo_roaming_allowed(self, imsi: str, allowed: bool) -> bool:
        """Flip an existing subscriber's roaming mode (`sub edit --home-routed`).

        Returns False if no such subscriber exists.
        """

        def _update(conn: sqlite3.Connection) -> bool:
            cur = conn.execute(
                "UPDATE subscribers SET lbo_roaming_allowed = ? WHERE imsi = ?",
                (int(allowed), imsi),
            )
            return cur.rowcount > 0

        return self._with_db(_update, mutate=True)

    def imsis(self) -> set[str]:
        def _imsis(conn: sqlite3.Connection) -> set[str]:
            return {row[0] for row in conn.execute("SELECT imsi FROM subscribers")}

        return self._with_db(_imsis, mutate=False)

    def remove(self, imsi: str) -> bool:
        def _remove(conn: sqlite3.Connection) -> bool:
            cur = conn.execute("DELETE FROM subscribers WHERE imsi = ?", (imsi,))
            return cur.rowcount > 0

        return self._with_db(_remove, mutate=True)
