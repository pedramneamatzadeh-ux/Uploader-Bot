"""کاربران، دانلودها و گزارش‌ها."""

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

class UsersMixin:

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------
    def save_or_update_user(
        self,
        user_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO users (
                    user_id,
                    username,
                    first_name,
                    last_name
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    last_activity = CURRENT_TIMESTAMP
                """,
                (
                    user_id,
                    username,
                    first_name,
                    last_name,
                ),
            )

    def get_all_users(self) -> List[Dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM users
                ORDER BY last_activity DESC
                """
            ).fetchall()

        return [dict(row) for row in rows]

    def get_all_user_ids(self) -> List[int]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT user_id FROM users"
            ).fetchall()

        return [row[0] for row in rows]

    def count_users(self) -> int:
        with self.connect() as connection:
            return connection.execute(
                "SELECT COUNT(*) FROM users"
            ).fetchone()[0]

    # ------------------------------------------------------------------
    # Downloads
    # ------------------------------------------------------------------
    def record_download(
        self,
        session_id: str,
        user_id: int,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO downloads (
                    session_id,
                    user_id
                )
                VALUES (?, ?)
                """,
                (session_id, user_id),
            )

    def get_top_anime(
        self,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    uploads.anime_name,
                    uploads.quality,
                    COUNT(downloads.id) AS download_count
                FROM downloads
                JOIN uploads
                    ON downloads.session_id = uploads.session_id
                GROUP BY uploads.session_id
                ORDER BY download_count DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [dict(row) for row in rows]

    def count_total_downloads(self) -> int:
        with self.connect() as connection:
            return connection.execute(
                "SELECT COUNT(*) FROM downloads"
            ).fetchone()[0]

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------
    def save_report(
        self,
        session_id: str,
        user_id: int,
        text: Optional[str] = None,
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO reports (
                    session_id,
                    user_id,
                    report_text
                )
                VALUES (?, ?, ?)
                """,
                (
                    session_id,
                    user_id,
                    text,
                ),
            )

            return cursor.lastrowid

    def get_all_reports(
        self,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        query = """
            SELECT
                reports.id,
                reports.session_id,
                reports.user_id,
                reports.report_text,
                reports.status,
                reports.created_at,
                uploads.anime_name,
                uploads.quality
            FROM reports
            JOIN uploads
                ON reports.session_id = uploads.session_id
        """

        params = ()

        if status:
            query += " WHERE reports.status = ?"
            params = (status,)

        query += " ORDER BY reports.created_at DESC"

        with self.connect() as connection:
            rows = connection.execute(
                query,
                params,
            ).fetchall()

        return [dict(row) for row in rows]

    def count_reports(
        self,
        status: Optional[str] = None,
    ) -> int:
        with self.connect() as connection:
            if status:
                return connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM reports
                    WHERE status = ?
                    """,
                    (status,),
                ).fetchone()[0]

            return connection.execute(
                "SELECT COUNT(*) FROM reports"
            ).fetchone()[0]

    def update_report_status(
        self,
        report_id: int,
        status: str,
    ) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE reports
                SET status = ?
                WHERE id = ?
                """,
                (
                    status,
                    report_id,
                ),
            )

            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Uploads
    # ------------------------------------------------------------------
    @staticmethod
    def derive_airing_status(chat_id: Any) -> Optional[str]:
        """وضعیت پخش پیش‌فرض را از روی کانال دیتابیس تعیین می‌کند.

        قانون: نام دیتابیس حاوی «درحال» ⇒ «درحال پخش»؛
        بقیه دیتابیس‌های اصلی (اتمام پخش/سینمایی) ⇒ «اتمام پخش».
        برای کانال‌های سفارشی (خارج از config.DATABASES) مقدار
        برنمی‌گرداند؛ صداکننده باید airing_status را خودش بدهد.
        """
        if chat_id is None or str(chat_id).strip() == "":
            if config.DATABASES:
                chat_id = config.DATABASES[0]["chat_id"]
            else:
                return None

        try:
            cid = int(chat_id)
        except (TypeError, ValueError):
            return None

        for db_entry in config.DATABASES:
            if db_entry["chat_id"] == cid:
                return (
                    "درحال پخش"
                    if "درحال" in db_entry["name"]
                    else "اتمام پخش"
                )

        return None
