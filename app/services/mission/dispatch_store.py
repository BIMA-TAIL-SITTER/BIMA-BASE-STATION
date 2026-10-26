"""Atomic mission snapshot + append-only audit trail in one SQLite transaction."""
import json
from pathlib import Path
import sqlite3
import threading
import time


class MissionStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS snapshot (id INTEGER PRIMARY KEY, body TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL, body TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, body TEXT NOT NULL)")
        self.db.commit()

    def load(self):
        with self._lock:
            row = self.db.execute("SELECT body FROM snapshot WHERE id=1").fetchone()
        return json.loads(row[0]) if row else None

    def load_config(self, key):
        with self._lock:
            row = self.db.execute("SELECT body FROM config WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_config(self, key, value):
        with self._lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO config VALUES (?, ?)", (key, json.dumps(value, allow_nan=False)))

    def save(self, state, event, **details):
        with self._lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO snapshot VALUES (1, ?)", (json.dumps(state, allow_nan=False),))
            self.db.execute("INSERT INTO events(at,body) VALUES (?,?)", (
                time.time(), json.dumps(dict(type=event, mission_id=state.get("plan", {}).get("mission_id"),
                    mission_version=state.get("plan", {}).get("version"), **details), allow_nan=False)))

    def events(self):
        with self._lock:
            return [dict(id=row[0], at=row[1], **json.loads(row[2]))
                    for row in self.db.execute("SELECT id,at,body FROM events ORDER BY id DESC LIMIT 50")]

    def close(self):
        self.db.close()
