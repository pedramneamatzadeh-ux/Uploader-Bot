"""انیمه‌های درحال پخش."""

import json
import logging
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

from ..config import config
from ..constants import (
    ALLOWED_ONGOING_UPDATE_FIELDS,
    ALLOWED_UPLOAD_UPDATE_FIELDS,
)

logger = logging.getLogger(__name__)

class OngoingMixin:

    def set_ongoing_airing(
        self,
        ongoing_id: int,
        active: bool,
    ) -> bool:
        """انیمه درحال پخش را فعال/غیرفعال می‌کند (اتمام پخش / بازگشت)."""
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE ongoing_animes
                SET
                    status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                ("active" if active else "inactive", ongoing_id),
            )

            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Ongoing anime
    # ------------------------------------------------------------------
    def save_ongoing_anime(
        self,
        data: Dict[str, Any],
        admin_id: int,
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO ongoing_animes (
                    anime_name,
                    season_num,
                    part_num,
                    admin_id
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    data["anime_name"],
                    data.get("season_num"),
                    data.get("part_num"),
                    admin_id,
                ),
            )

            return cursor.lastrowid

    def get_ongoing_anime(
        self,
        anime_id: int,
    ) -> Optional[Dict[str, Any]]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    anime_name,
                    season_num,
                    part_num,
                    COALESCE(status, 'active') AS status,
                    admin_id,
                    created_at,
                    updated_at
                FROM ongoing_animes
                WHERE id = ?
                """,
                (anime_id,),
            ).fetchone()

        return dict(row) if row else None

    def get_ongoing_animes(
        self,
        page: int = 0,
        active_only: bool = False,
    ) -> List[Dict[str, Any]]:
        where_clause = (
            "WHERE status = 'active'"
            if active_only
            else ""
        )

        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    id,
                    anime_name,
                    season_num,
                    part_num,
                    COALESCE(status, 'active') AS status,
                    admin_id,
                    created_at,
                    updated_at
                FROM ongoing_animes
                {where_clause}
                ORDER BY updated_at DESC, created_at DESC
                LIMIT ? OFFSET ?
                """,
                (
                    config.PAGE_SIZE,
                    page * config.PAGE_SIZE,
                ),
            ).fetchall()

        return [dict(row) for row in rows]

    def count_ongoing_animes(
        self,
        active_only: bool = False,
    ) -> int:
        where_clause = (
            "WHERE status = 'active'"
            if active_only
            else ""
        )

        with self.connect() as connection:
            return connection.execute(
                f"""
                SELECT COUNT(*)
                FROM ongoing_animes
                {where_clause}
                """
            ).fetchone()[0]

    def update_ongoing_anime(
        self,
        anime_id: int,
        field: str,
        value: Any,
    ) -> bool:
        if field not in ALLOWED_ONGOING_UPDATE_FIELDS:
            logger.error(
                "ستون غیرمجاز برای ongoing_animes: %s",
                field,
            )
            return False

        with self.connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE ongoing_animes
                SET
                    {field} = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    value,
                    anime_id,
                ),
            )

            return cursor.rowcount > 0

    def toggle_ongoing_status(
        self,
        anime_id: int,
    ) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT status
                FROM ongoing_animes
                WHERE id = ?
                """,
                (anime_id,),
            ).fetchone()

            if not row:
                return False

            new_status = (
                "inactive"
                if row["status"] == "active"
                else "active"
            )

            connection.execute(
                """
                UPDATE ongoing_animes
                SET
                    status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    new_status,
                    anime_id,
                ),
            )

            return True

    def delete_ongoing_anime(
        self,
        anime_id: int,
    ) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM ongoing_animes
                WHERE id = ?
                """,
                (anime_id,),
            )

            return cursor.rowcount > 0
