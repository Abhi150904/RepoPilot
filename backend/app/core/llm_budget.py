from __future__ import annotations

from contextlib import closing
from hashlib import sha256
from pathlib import Path
import sqlite3
from uuid import uuid4


class BudgetExceededError(RuntimeError):
    pass


class LLMBudget:
    """Reserve conservative costs atomically across local worker processes."""

    def __init__(self, path: str, api_key: str, limit: float, run_limit: float):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.key_id = sha256(api_key.encode()).hexdigest()
        self.limit = limit
        self.run_limit = run_limit
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS reservations "
                "(id TEXT PRIMARY KEY, key_id TEXT NOT NULL, run_id TEXT NOT NULL, amount REAL NOT NULL)"
            )

    def reserve(self, amount: float, run_id: str) -> str:
        with closing(sqlite3.connect(self.path, timeout=30)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            total = db.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM reservations WHERE key_id = ?", (self.key_id,)
            ).fetchone()[0]
            run_total = db.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM reservations WHERE key_id = ? AND run_id = ?",
                (self.key_id, run_id),
            ).fetchone()[0]
            if total + amount > self.limit or run_total + amount > self.run_limit:
                raise BudgetExceededError(
                    "RepoPilot OpenAI spending guard blocked this request. "
                    f"Reserved/spent: ${total:.4f}; request reserve: ${amount:.4f}; "
                    f"total limit: ${self.limit:.2f}; run limit: ${self.run_limit:.2f}."
                )
            reservation = uuid4().hex
            db.execute("INSERT INTO reservations VALUES (?, ?, ?, ?)",
                       (reservation, self.key_id, run_id, amount))
            return reservation

    def settle(self, reservation: str, actual_cost: float | None) -> None:
        # Keep the full reservation when usage is unknown (timeouts, process crashes).
        if actual_cost is None:
            return
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE reservations SET amount = ? WHERE id = ? AND key_id = ?",
                       (actual_cost, reservation, self.key_id))
