"""CRUD لینک‌های آپلود + شمارش‌ها."""

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

class UploadsMixin:

    def save_upload(
        self,
        session_id: str,
        data: Dict[str, Any],
        admin_id: int,
    ) -> None:
        channel_chat_id = data.get("channel_chat_id")

        if channel_chat_id is not None:
            channel_chat_id = str(channel_chat_id)

        airing_status = data.get("airing_status") or (
            self.derive_airing_status(channel_chat_id)
        )

        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO uploads (
                    session_id,
                    anime_name,
                    season_num,
                    part_num,
                    episode_range,
                    quality,
                    channel_msg_range,
                    admin_id,
                    is_ongoing,
                    ongoing_anime_id,
                    anime_type,
                    channel_chat_id,
                    airing_status,
                    is_bluray
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    data["anime_name"],
                    data.get("season_num"),
                    data.get("part_num"),
                    data["episode_range"],
                    data["quality"],
                    data["channel_msg_range"],
                    admin_id,
                    int(data.get("is_ongoing", 0)),
                    data.get("ongoing_anime_id"),
                    data.get("anime_type", ""),
                    channel_chat_id,
                    airing_status,
                    int(data.get("is_bluray", 0) or 0),
                ),
            )

    def get_upload(
        self,
        session_id: str,
    ) -> Optional[Dict[str, Any]]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    anime_name,
                    season_num,
                    part_num,
                    episode_range,
                    quality,
                    channel_msg_range,
                    COALESCE(status, 'active') AS status,
                    COALESCE(anime_type, '') AS anime_type,
                    channel_chat_id,
                    COALESCE(is_bluray, 0) AS is_bluray
                FROM uploads
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()

        return dict(row) if row else None

    def get_upload_by_id(
        self,
        session_id: str,
    ) -> Optional[Dict[str, Any]]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    session_id,
                    anime_name,
                    season_num,
                    part_num,
                    episode_range,
                    quality,
                    channel_msg_range,
                    COALESCE(status, 'active') AS status,
                    admin_id,
                    created_at,
                    COALESCE(is_ongoing, 0) AS is_ongoing,
                    ongoing_anime_id,
                    COALESCE(anime_type, '') AS anime_type,
                    channel_chat_id,
                    airing_status,
                    COALESCE(is_finished, 0) AS is_finished,
                    COALESCE(is_bluray, 0) AS is_bluray
                FROM uploads
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()

        return dict(row) if row else None

    def get_all_uploads(
        self,
        page: int = 0,
    ) -> List[Dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    session_id,
                    anime_name,
                    season_num,
                    part_num,
                    episode_range,
                    quality,
                    channel_msg_range,
                    COALESCE(status, 'active') AS status,
                    created_at,
                    COALESCE(is_ongoing, 0) AS is_ongoing,
                    COALESCE(anime_type, '') AS anime_type
                FROM uploads
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (
                    config.PAGE_SIZE,
                    page * config.PAGE_SIZE,
                ),
            ).fetchall()

        return [dict(row) for row in rows]

    def count_all_uploads(self) -> int:
        with self.connect() as connection:
            return connection.execute(
                "SELECT COUNT(*) FROM uploads"
            ).fetchone()[0]

    def search_uploads(
        self,
        term: str,
        page: int = 0,
    ) -> List[Dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    session_id,
                    anime_name,
                    season_num,
                    part_num,
                    episode_range,
                    quality,
                    channel_msg_range,
                    COALESCE(status, 'active') AS status,
                    created_at,
                    COALESCE(is_ongoing, 0) AS is_ongoing,
                    COALESCE(anime_type, '') AS anime_type
                FROM uploads
                WHERE anime_name LIKE ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (
                    f"%{term}%",
                    config.PAGE_SIZE,
                    page * config.PAGE_SIZE,
                ),
            ).fetchall()

        return [dict(row) for row in rows]

    def count_search_uploads(
        self,
        term: str,
    ) -> int:
        with self.connect() as connection:
            return connection.execute(
                """
                SELECT COUNT(*)
                FROM uploads
                WHERE anime_name LIKE ?
                """,
                (f"%{term}%",),
            ).fetchone()[0]

    def update_upload(
        self,
        session_id: str,
        field: str,
        value: Any,
    ) -> bool:
        if field not in ALLOWED_UPLOAD_UPDATE_FIELDS:
            logger.error(
                "تلاش برای به‌روزرسانی ستون غیرمجاز: %s",
                field,
            )
            return False

        with self.connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE uploads
                SET {field} = ?
                WHERE session_id = ?
                """,
                (
                    value,
                    session_id,
                ),
            )

            return cursor.rowcount > 0

    def toggle_status(
        self,
        session_id: str,
    ) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT status
                FROM uploads
                WHERE session_id = ?
                """,
                (session_id,),
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
                UPDATE uploads
                SET status = ?
                WHERE session_id = ?
                """,
                (
                    new_status,
                    session_id,
                ),
            )

            return True

    def delete_upload(
        self,
        session_id: str,
    ) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM uploads
                WHERE session_id = ?
                """,
                (session_id,),
            )

            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # اتمام پخش برگشت‌پذیر (مرحله ۴ — R7)
    # کلید تطبیق: نام + فصل + پارت (تأکید کاربر: فقط همین سه‌تایی)
    # ------------------------------------------------------------------
    def count_uploads_triple(
        self,
        anime_name: str,
        season_num: Optional[str],
        part_num: Optional[str],
    ) -> int:
        with self.connect() as connection:
            return connection.execute(
                """
                SELECT COUNT(*)
                FROM uploads
                WHERE
                    anime_name = ?
                    AND COALESCE(season_num, '') = COALESCE(?, '')
                    AND COALESCE(part_num, '') = COALESCE(?, '')
                """,
                (anime_name, season_num, part_num),
            ).fetchone()[0]

    def count_finished_uploads(
        self,
        anime_name: str,
        season_num: Optional[str],
        part_num: Optional[str],
    ) -> int:
        with self.connect() as connection:
            return connection.execute(
                """
                SELECT COUNT(*)
                FROM uploads
                WHERE
                    anime_name = ?
                    AND COALESCE(season_num, '') = COALESCE(?, '')
                    AND COALESCE(part_num, '') = COALESCE(?, '')
                    AND COALESCE(is_finished, 0) = 1
                """,
                (anime_name, season_num, part_num),
            ).fetchone()[0]

    def set_finished_for_triple(
        self,
        anime_name: str,
        season_num: Optional[str],
        part_num: Optional[str],
        finished: bool,
    ) -> int:
        """لینک‌های هم‌نام+هم‌فصل+هم‌پارت را اتمام/درحال پخش می‌کند.

        تعداد لینک‌های تغییرکرده را برمی‌گرداند.
        """
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE uploads
                SET is_finished = ?
                WHERE
                    anime_name = ?
                    AND COALESCE(season_num, '') = COALESCE(?, '')
                    AND COALESCE(part_num, '') = COALESCE(?, '')
                """,
                (
                    int(finished),
                    anime_name,
                    season_num,
                    part_num,
                ),
            )

            return cursor.rowcount

    def get_group_bluray(
        self,
        anime_name: str,
        season_num: Optional[str],
        part_num: Optional[str],
        episode_range: Optional[str] = None,
    ) -> int:
        """B20/B22: وضعیت بلوری گروه — اگر حتی یک لینک بلوری باشد ۱.

        با episode_range فقط لینک‌های همان اپیزود بررسی می‌شوند
        (None = کل فصل/پارت/سینمایی).
        """
        sql = """
            SELECT COALESCE(MAX(is_bluray), 0) AS bl
            FROM uploads
            WHERE
                anime_name = ?
                AND COALESCE(season_num, '') = COALESCE(?, '')
                AND COALESCE(part_num, '') = COALESCE(?, '')
        """
        params: list = [anime_name, season_num, part_num]
        if episode_range is not None:
            sql += " AND COALESCE(episode_range, '') = ?"
            params.append(episode_range)
        with self.connect() as connection:
            row = connection.execute(sql, tuple(params)).fetchone()

            return int(row["bl"]) if row else 0

    def set_group_bluray(
        self,
        anime_name: str,
        season_num: Optional[str],
        part_num: Optional[str],
        is_bluray: int,
        episode_range: Optional[str] = None,
    ) -> int:
        """B20/B22: لینک‌های هم‌نام+هم‌فصل+هم‌پارت را بلوری/غیربلوری
        می‌کند (دوطرفه). با episode_range فقط همان اپیزود.
        تعداد لینک‌های تغییرکرده را برمی‌گرداند."""
        sql = """
            UPDATE uploads
            SET is_bluray = ?
            WHERE
                anime_name = ?
                AND COALESCE(season_num, '') = COALESCE(?, '')
                AND COALESCE(part_num, '') = COALESCE(?, '')
        """
        params: list = [int(is_bluray), anime_name, season_num, part_num]
        if episode_range is not None:
            sql += " AND COALESCE(episode_range, '') = ?"
            params.append(episode_range)
        with self.connect() as connection:
            cursor = connection.execute(sql, tuple(params))

            return cursor.rowcount

    def get_quality_counts(self) -> List[Dict[str, Any]]:
        """R13: تعداد لینک‌ها به تفکیک کیفیت (نزولی)."""
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    COALESCE(quality, '') AS quality,
                    COUNT(*) AS cnt
                FROM uploads
                GROUP BY COALESCE(quality, '')
                ORDER BY COUNT(*) DESC
                """
            ).fetchall()

        return [dict(row) for row in rows]

    def get_stats_groups(self) -> List[Dict[str, Any]]:
        """R13: گروه‌های فیزیکی (نام، فصل، پارت، نوع) با تعداد لینک
        و وضعیت بلوری — برای آمار دیتابیس."""
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    anime_name,
                    COALESCE(season_num, '') AS season_num,
                    COALESCE(part_num, '') AS part_num,
                    COALESCE(anime_type, '') AS anime_type,
                    COUNT(*) AS cnt,
                    COALESCE(MAX(is_bluray), 0) AS bluray
                FROM uploads
                GROUP BY
                    anime_name,
                    COALESCE(season_num, ''),
                    COALESCE(part_num, ''),
                    COALESCE(anime_type, '')
                """
            ).fetchall()

        return [dict(row) for row in rows]
