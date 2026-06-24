"""SQLite state store for crash-safe rollback of system changes."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

_STATE_DIR = Path.home() / ".geospoof"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS changes (
    id INTEGER PRIMARY KEY,
    category TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


class StateStore:
    """Lightweight SQLite store that tracks every reversible change we make.

    Categories:
        nat_plist       — NAT plist backup/modification state
        wifi            — iPhone WiFi power state before we touched it
        internet_sharing — whether the sharing daemon was loaded by us
    """

    def __init__(self, state_dir: str | Path | None = None) -> None:
        self._state_dir = Path(state_dir) if state_dir else _STATE_DIR
        self._backup_dir = self._state_dir / "backups"
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._state_dir / "state.db"))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    # ── Core CRUD ─────────────────────────────────────────────────────

    def record(self, category: str, key: str, value: str | None = None) -> None:
        """Insert a change record."""
        self._conn.execute(
            "INSERT INTO changes (category, key, value) VALUES (?, ?, ?)",
            (category, key, value),
        )
        self._conn.commit()

    def get(self, category: str, key: str) -> str | None:
        """Get the most recent value for a category/key pair."""
        row = self._conn.execute(
            "SELECT value FROM changes WHERE category = ? AND key = ? ORDER BY id DESC LIMIT 1",
            (category, key),
        ).fetchone()
        return row[0] if row else None

    def get_all(self, category: str) -> list[tuple[str, str | None]]:
        """Return all (key, value) pairs for a category."""
        return self._conn.execute(
            "SELECT key, value FROM changes WHERE category = ? ORDER BY id",
            (category,),
        ).fetchall()

    def clear(self, category: str) -> None:
        """Remove all records for a category."""
        self._conn.execute("DELETE FROM changes WHERE category = ?", (category,))
        self._conn.commit()

    def clear_all(self) -> None:
        """Remove every record (full reset)."""
        self._conn.execute("DELETE FROM changes")
        self._conn.commit()

    def has_orphans(self) -> bool:
        """Return True if the DB has any leftover records from a previous run."""
        row = self._conn.execute("SELECT COUNT(*) FROM changes").fetchone()
        return row[0] > 0

    # ── File backup helpers ───────────────────────────────────────────

    def backup_file(self, src_path: str | Path, category: str) -> Path:
        """Copy *src_path* into the backup dir and record it in the DB.

        Returns the backup path.
        """
        src = Path(src_path)
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        dst = self._backup_dir / src.name
        shutil.copy2(src, dst)
        self.record(category, "backup_path", str(dst))
        self.record(category, "original_path", str(src))
        return dst

    def restore_file(self, category: str) -> bool:
        """Restore the backed-up file to its original location.

        Returns True if a backup was found and restored.
        """
        backup_path = self.get(category, "backup_path")
        original_path = self.get(category, "original_path")

        if backup_path and original_path:
            bp = Path(backup_path)
            if bp.exists():
                shutil.copy2(bp, original_path)
                bp.unlink()
            self.clear(category)
            return True
        return False

    def close(self) -> None:
        self._conn.close()
