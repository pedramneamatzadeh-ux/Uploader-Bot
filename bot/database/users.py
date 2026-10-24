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

    def get_top_anime_grouped(
        self,
        limit: int = 10,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """R8b: پرطرفدارها گروه‌بندی‌شده بر (نام، نوع، فصل، پارت).

        همه کیفیت‌ها با هم شمارش می‌شوند:
        - users_count = کاربران یکتا (هر کاربر برای هر فصل/پارت یک‌بار،
          حتی اگر چند کیفیت یا چندبار دانلود کرده باشد)
        - total_count = کل واقعی دانلودها
        """
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    uploads.anime_name,
                    COALESCE(uploads.anime_type, '') AS anime_type,
                    COALESCE(uploads.season_num, '') AS season_num,
                    COALESCE(uploads.part_num, '') AS part_num,
                    COUNT(DISTINCT downloads.user_id) AS users_count,
                    COUNT(downloads.id) AS total_count
                FROM downloads
                JOIN uploads
                    ON downloads.session_id = uploads.session_id
                GROUP BY
                    uploads.anime_name,
                    anime_type,
                    season_num,
                    part_num
                ORDER BY users_count DESC, total_count DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

        return [dict(row) for row in rows]

    def count_top_anime_groups(self) -> int:
        """R8b: تعداد کل گروه‌های (نام، نوع، فصل، پارت) دارای دانلود."""
        with self.connect() as connection:
            return connection.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT 1
                    FROM downloads
                    JOIN uploads
                        ON downloads.session_id = uploads.session_id
                    GROUP BY
                        uploads.anime_name,
                        COALESCE(uploads.anime_type, ''),
                        COALESCE(uploads.season_num, ''),
                        COALESCE(uploads.part_num, '')
                )
                """
            ).fetchone()[0]

    def get_user_download_info(self) -> Dict[int, Dict[str, Any]]:
        """R8a: برای هر کاربر — آخرین دانلود + شمار یکتای فصل/پارت.

        خروجی: {user_id: {"last": {...} یا None, "uniq": int}}
        """
        with self.connect() as connection:
            last_rows = connection.execute(
                """
                SELECT
                    downloads.user_id,
                    uploads.anime_name,
                    COALESCE(uploads.anime_type, '') AS anime_type,
                    COALESCE(uploads.season_num, '') AS season_num,
                    COALESCE(uploads.part_num, '') AS part_num,
                    uploads.quality,
                    downloads.downloaded_at
                FROM downloads
                JOIN uploads
                    ON downloads.session_id = uploads.session_id
                WHERE downloads.id IN (
                    SELECT MAX(id) FROM downloads GROUP BY user_id
                )
                """
            ).fetchall()
            uniq_rows = connection.execute(
                """
                SELECT
                    downloads.user_id,
                    COUNT(DISTINCT
                        uploads.anime_name || '|' ||
                        COALESCE(uploads.anime_type, '') || '|' ||
                        COALESCE(uploads.season_num, '') || '|' ||
                        COALESCE(uploads.part_num, '')
                    ) AS uniq_count
                FROM downloads
                JOIN uploads
                    ON downloads.session_id = uploads.session_id
                GROUP BY downloads.user_id
                """
            ).fetchall()

        info: Dict[int, Dict[str, Any]] = {}
        for row in uniq_rows:
            info[row["user_id"]] = {"last": None, "uniq": row["uniq_count"]}
        for row in last_rows:
            entry = info.setdefault(
                row["user_id"], {"last": None, "uniq": 0}
            )
            entry["last"] = dict(row)
        return info

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

    def get_report_by_id(
        self,
        report_id: int,
    ) -> Optional[Dict[str, Any]]:
        """R8c: جزئیات کامل یک گزارش + اطلاعات فایل + یوزرنیم گزارش‌دهنده."""
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    reports.id,
                    reports.session_id,
                    reports.user_id,
                    reports.report_text,
                    reports.status,
                    reports.created_at,
                    uploads.anime_name,
                    COALESCE(uploads.anime_type, '') AS anime_type,
                    COALESCE(uploads.season_num, '') AS season_num,
                    COALESCE(uploads.part_num, '') AS part_num,
                    uploads.episode_range,
                    uploads.quality,
                    uploads.channel_chat_id,
                    uploads.channel_msg_range,
                    COALESCE(uploads.status, 'active') AS upload_status,
                    users.username AS reporter_username
                FROM reports
                JOIN uploads
                    ON reports.session_id = uploads.session_id
                LEFT JOIN users
                    ON users.user_id = reports.user_id
                WHERE reports.id = ?
                """,
                (report_id,),
            ).fetchone()

        return dict(row) if row else None

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
