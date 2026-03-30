"""SQLite job queue for tracking analysis state."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# Valid status transitions through the pipeline
ACTIVE_STATUSES = (
    "pending",
    "pass1_done",
    "pass2_done",
    "quorum_pass",
    "quorum_fail",
    "retry_1",
    "retry_2",
    "retry_3",
)

TERMINAL_STATUSES = ("complete", "flagged_for_opus", "error", "removed")

ALL_STATUSES = ACTIVE_STATUSES + TERMINAL_STATUSES


class StateDB:
    """SQLite-backed job queue for the analysis pipeline.

    Each file in the target repo gets a row in the `jobs` table, tracking
    its progress through the two-pass analysis and quorum process.
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    def _create_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                file_path TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'pending',
                pass1_result TEXT,
                pass2_result TEXT,
                quorum_result TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                final_description TEXT,
                error_log TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

            CREATE TABLE IF NOT EXISTS run_metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        self._conn.commit()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # -- Job operations --

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def add_jobs(self, file_paths: list[str]):
        """Batch-insert new jobs as 'pending'. Skips paths that already exist."""
        now = self._now()
        self._conn.executemany(
            """INSERT OR IGNORE INTO jobs (file_path, status, created_at, updated_at)
               VALUES (?, 'pending', ?, ?)""",
            [(path, now, now) for path in file_paths],
        )
        self._conn.commit()

    def update_status(self, file_path: str, status: str, **fields):
        """Update a job's status and any additional fields.

        Accepts keyword arguments matching column names:
        pass1_result, pass2_result, quorum_result, retry_count,
        final_description, error_log.

        JSON-serializable values for result fields are automatically converted.
        """
        if status not in ALL_STATUSES:
            raise ValueError(f"Invalid status: {status!r}")

        sets = ["status = ?", "updated_at = ?"]
        values: list[Any] = [status, self._now()]

        json_fields = ("pass1_result", "pass2_result", "quorum_result")
        for key, value in fields.items():
            if key not in (
                "pass1_result", "pass2_result", "quorum_result",
                "retry_count", "final_description", "error_log",
            ):
                raise ValueError(f"Unknown field: {key!r}")
            if key in json_fields and not isinstance(value, str):
                value = json.dumps(value)
            sets.append(f"{key} = ?")
            values.append(value)

        values.append(file_path)
        self._conn.execute(
            f"UPDATE jobs SET {', '.join(sets)} WHERE file_path = ?",
            values,
        )
        self._conn.commit()

    def get_job(self, file_path: str) -> Optional[dict]:
        """Get a single job by file path, or None if not found."""
        row = self._conn.execute(
            "SELECT * FROM jobs WHERE file_path = ?", (file_path,)
        ).fetchone()
        return dict(row) if row else None

    def get_jobs_by_status(self, *statuses: str) -> list[dict]:
        """Get all jobs matching any of the given statuses."""
        placeholders = ", ".join("?" for _ in statuses)
        rows = self._conn.execute(
            f"SELECT * FROM jobs WHERE status IN ({placeholders})",
            statuses,
        ).fetchall()
        return [dict(row) for row in rows]

    def get_resumable_jobs(self) -> list[dict]:
        """Get all jobs that should be reprocessed on resume.

        Returns jobs not in a terminal state, ordered by their current
        position in the pipeline (earliest stage first).
        """
        placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)
        rows = self._conn.execute(
            f"""SELECT * FROM jobs WHERE status IN ({placeholders})
                ORDER BY
                    CASE status
                        WHEN 'pending' THEN 0
                        WHEN 'pass1_done' THEN 1
                        WHEN 'pass2_done' THEN 2
                        WHEN 'quorum_fail' THEN 3
                        WHEN 'retry_1' THEN 4
                        WHEN 'retry_2' THEN 5
                        WHEN 'retry_3' THEN 6
                        WHEN 'quorum_pass' THEN 7
                    END""",
            ACTIVE_STATUSES,
        ).fetchall()
        return [dict(row) for row in rows]

    def mark_removed(self, file_paths: list[str]):
        """Mark files that no longer exist in the repo as 'removed'."""
        now = self._now()
        self._conn.executemany(
            "UPDATE jobs SET status = 'removed', updated_at = ? WHERE file_path = ?",
            [(now, path) for path in file_paths],
        )
        self._conn.commit()

    def get_all_tracked_paths(self) -> set[str]:
        """Get all file paths currently in the database (any status)."""
        rows = self._conn.execute(
            "SELECT file_path FROM jobs WHERE status != 'removed'"
        ).fetchall()
        return {row["file_path"] for row in rows}

    # -- Progress stats --

    def get_progress(self) -> dict[str, int]:
        """Get counts of jobs by status."""
        rows = self._conn.execute(
            "SELECT status, COUNT(*) as count FROM jobs GROUP BY status"
        ).fetchall()
        return {row["status"]: row["count"] for row in rows}

    def get_total_counts(self) -> dict[str, int]:
        """Get summary counts for progress display."""
        progress = self.get_progress()
        total = sum(progress.values())
        completed = progress.get("complete", 0)
        flagged = progress.get("flagged_for_opus", 0)
        errors = progress.get("error", 0)
        removed = progress.get("removed", 0)
        in_progress = total - completed - flagged - errors - removed
        return {
            "total": total,
            "completed": completed,
            "flagged": flagged,
            "errors": errors,
            "removed": removed,
            "in_progress": in_progress,
        }

    # -- Run metadata --

    def set_metadata(self, key: str, value: str):
        """Set a run metadata key-value pair."""
        self._conn.execute(
            "INSERT OR REPLACE INTO run_metadata (key, value) VALUES (?, ?)",
            (key, value),
        )
        self._conn.commit()

    def get_metadata(self, key: str) -> Optional[str]:
        """Get a run metadata value by key, or None."""
        row = self._conn.execute(
            "SELECT value FROM run_metadata WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def get_all_metadata(self) -> dict[str, str]:
        """Get all run metadata as a dictionary."""
        rows = self._conn.execute("SELECT key, value FROM run_metadata").fetchall()
        return {row["key"]: row["value"] for row in rows}

    # -- Database state --

    def exists(self) -> bool:
        """Check if the database file exists and has the jobs table."""
        if not self.db_path.exists():
            return False
        row = self._conn.execute(
            "SELECT COUNT(*) as count FROM sqlite_master WHERE type='table' AND name='jobs'"
        ).fetchone()
        return row["count"] > 0
