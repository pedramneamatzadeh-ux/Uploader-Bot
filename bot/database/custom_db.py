"""دیتابیس‌های سفارشی."""

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

class CustomDbMixin:

    # ------------------------------------------------------------------
    # Custom databases (دیتابیس‌های سفارشی)
    # ------------------------------------------------------------------
    def save_custom_database(
        self,
        name: str,
        chat_id: Any,
        created_by: Optional[int] = None,
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO custom_databases (name, chat_id, created_by)
                VALUES (?, ?, ?)
                """,
                (name.strip(), str(chat_id).strip(), created_by),
            )

            return cursor.lastrowid

    def get_custom_databases(self) -> List[Dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, name, chat_id, created_by, created_at
                FROM custom_databases
                ORDER BY id ASC
                """
            ).fetchall()

        return [dict(row) for row in rows]

    def delete_custom_database(self, db_id: int) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM custom_databases WHERE id = ?",
                (db_id,),
            )

            return cursor.rowcount > 0
