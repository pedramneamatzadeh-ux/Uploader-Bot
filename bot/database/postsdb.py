"""پست‌های کانال."""

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

class PostsMixin:

    # ------------------------------------------------------------------
    # Posts
    # ------------------------------------------------------------------
    def save_post(
        self,
        post_id: str,
        post_name: str,
        admin_id: int,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO posts (
                    post_id,
                    post_name,
                    admin_id
                )
                VALUES (?, ?, ?)
                """,
                (
                    post_id,
                    post_name,
                    admin_id,
                ),
            )

    def add_post_message(
        self,
        post_id: str,
        chat_id: int,
        message_id: int,
        order: int,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO post_messages (
                    post_id,
                    chat_id,
                    message_id,
                    message_order
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    post_id,
                    chat_id,
                    message_id,
                    order,
                ),
            )

    def get_post(
        self,
        post_id: str,
    ) -> Optional[Dict[str, Any]]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    post_id,
                    post_name,
                    admin_id,
                    COALESCE(status, 'active') AS status,
                    created_at
                FROM posts
                WHERE post_id = ?
                """,
                (post_id,),
            ).fetchone()

        return dict(row) if row else None

    def get_post_messages(
        self,
        post_id: str,
    ) -> List[Dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    chat_id,
                    message_id
                FROM post_messages
                WHERE post_id = ?
                ORDER BY message_order ASC
                """,
                (post_id,),
            ).fetchall()

        return [dict(row) for row in rows]

    def get_all_posts(
        self,
        page: int = 0,
    ) -> List[Dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    post_id,
                    post_name,
                    admin_id,
                    COALESCE(status, 'active') AS status,
                    created_at
                FROM posts
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (
                    config.PAGE_SIZE,
                    page * config.PAGE_SIZE,
                ),
            ).fetchall()

        return [dict(row) for row in rows]

    def count_all_posts(self) -> int:
        with self.connect() as connection:
            return connection.execute(
                "SELECT COUNT(*) FROM posts"
            ).fetchone()[0]

    def toggle_post_status(
        self,
        post_id: str,
    ) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT status
                FROM posts
                WHERE post_id = ?
                """,
                (post_id,),
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
                UPDATE posts
                SET status = ?
                WHERE post_id = ?
                """,
                (
                    new_status,
                    post_id,
                ),
            )

            return True

    def delete_post(
        self,
        post_id: str,
    ) -> bool:
        with self.connect() as connection:
            connection.execute(
                """
                DELETE FROM post_messages
                WHERE post_id = ?
                """,
                (post_id,),
            )

            cursor = connection.execute(
                """
                DELETE FROM posts
                WHERE post_id = ?
                """,
                (post_id,),
            )

            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # B4: آمار تحویل پست‌ها + تغییر نام
    # ------------------------------------------------------------------
    def record_post_delivery(
        self,
        post_id: str,
        user_id: int,
    ) -> None:
        """ثبت یک تحویل موفق پست (برای آمار «📥 N بار | 👥 M کاربر»)."""
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO post_deliveries (post_id, user_id)
                VALUES (?, ?)
                """,
                (post_id, user_id),
            )

    def get_post_delivery_stats(
        self,
        post_id: str,
    ) -> Dict[str, int]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(DISTINCT user_id) AS users
                FROM post_deliveries
                WHERE post_id = ?
                """,
                (post_id,),
            ).fetchone()
        if not row:
            return {"total": 0, "users": 0}
        return {"total": row["total"] or 0, "users": row["users"] or 0}

    def get_all_post_delivery_stats(self) -> Dict[str, Dict[str, int]]:
        """آمار تحویل همه پست‌ها یک‌جا (برای لیست)."""
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    post_id,
                    COUNT(*) AS total,
                    COUNT(DISTINCT user_id) AS users
                FROM post_deliveries
                GROUP BY post_id
                """
            ).fetchall()
        return {
            row["post_id"]: {
                "total": row["total"] or 0,
                "users": row["users"] or 0,
            }
            for row in rows
        }

    def rename_post(
        self,
        post_id: str,
        new_name: str,
    ) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE posts SET post_name = ? WHERE post_id = ?",
                (new_name, post_id),
            )
            return cursor.rowcount > 0
