"""Service layer for managing pull request gate skip settings persistence."""

import asyncio
import logging
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from forge.config import get_settings
from forge.models.gate_skip import PRGateSkipSettings

logger = logging.getLogger(__name__)


class GateSkipService:
    """Service to persist and retrieve gate-skipping configurations for pull requests."""

    _initialized = False

    @classmethod
    def _init_db(cls, db_path: str) -> None:
        """Initialize the database and create the table if it doesn't exist."""
        if cls._initialized:
            return

        path = Path(db_path)
        if path != Path(":memory:"):
            path.parent.mkdir(parents=True, exist_ok=True)

        with closing(sqlite3.connect(db_path)) as conn, conn:
            conn.execute(
                """
                    CREATE TABLE IF NOT EXISTS pr_gate_skip_settings (
                        repo TEXT NOT NULL,
                        pr_number INTEGER NOT NULL,
                        skip_gate BOOLEAN NOT NULL CHECK (skip_gate IN (0, 1)),
                        updated_by TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (repo, pr_number)
                    )
                    """
            )
        cls._initialized = True

    @classmethod
    def _get_connection(cls) -> sqlite3.Connection:
        """Get a database connection."""
        settings = get_settings()
        db_path = settings.database_path
        cls._init_db(db_path)
        return sqlite3.connect(db_path)

    @classmethod
    async def set_skip_status(cls, repo: str, pr_number: int, skip: bool, user: str) -> None:
        """Set the gate-skipping configuration for a pull request."""

        def _execute() -> None:
            now_str = datetime.utcnow().isoformat()
            with closing(cls._get_connection()) as conn, conn:
                conn.execute(
                    """
                    INSERT INTO pr_gate_skip_settings (repo, pr_number, skip_gate, updated_by, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(repo, pr_number) DO UPDATE SET
                        skip_gate=excluded.skip_gate,
                        updated_by=excluded.updated_by,
                        updated_at=excluded.updated_at
                    """,
                    (repo, pr_number, 1 if skip else 0, user, now_str),
                )

        await asyncio.to_thread(_execute)

    @classmethod
    async def get_skip_status(cls, repo: str, pr_number: int) -> bool:
        """Retrieve the gate-skipping configuration for a pull request.

        Returns:
            True if skipping is enabled, False otherwise.
        """

        def _execute() -> bool:
            with closing(cls._get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT skip_gate FROM pr_gate_skip_settings WHERE repo = ? AND pr_number = ?",
                    (repo, pr_number),
                )
                row = cursor.fetchone()
                if row is None:
                    return False
                return bool(row[0])

        return await asyncio.to_thread(_execute)

    @classmethod
    async def get_skip_settings(cls, repo: str, pr_number: int) -> PRGateSkipSettings | None:
        """Retrieve full gate-skipping settings for a pull request."""

        def _execute() -> PRGateSkipSettings | None:
            with closing(cls._get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT repo, pr_number, skip_gate, updated_by, updated_at "
                    "FROM pr_gate_skip_settings WHERE repo = ? AND pr_number = ?",
                    (repo, pr_number),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                return PRGateSkipSettings(
                    repo=row[0],
                    pr_number=row[1],
                    skip_gate=bool(row[2]),
                    updated_by=row[3],
                    updated_at=datetime.fromisoformat(row[4]),
                )

        return await asyncio.to_thread(_execute)


async def set_skip_status(repo: str, pr_number: int, skip: bool, user: str) -> None:
    """Module-level helper to set the gate-skipping configuration for a pull request."""
    await GateSkipService.set_skip_status(repo, pr_number, skip, user)


async def get_skip_status(repo: str, pr_number: int) -> bool:
    """Module-level helper to retrieve the gate-skipping configuration for a pull request."""
    return await GateSkipService.get_skip_status(repo, pr_number)
