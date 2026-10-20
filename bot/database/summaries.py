"""خلاصه داستان فصل‌ها (R10) — یک خلاصه برای هر (نام + فصل)."""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class SummariesMixin:
    def get_season_summary(
        self,
        anime_name: str,
        season_num: str,
    ) -> Optional[Dict[str, Any]]:
        """خلاصه داستان یک فصل؛ اگر ثبت نشده باشد None."""
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id, anime_name, season_num, summary_text,
                    photo_file_id, created_by, created_at, updated_at
                FROM season_summaries
                WHERE anime_name = ? AND season_num = ?
                """,
                (anime_name, season_num or ""),
            ).fetchone()
            return dict(row) if row else None

    def get_season_summary_by_id(
        self,
        summary_id: int,
    ) -> Optional[Dict[str, Any]]:
        """خلاصه فصل با شماره رکورد — برای لینک اشتراک‌گذاری sm<id>."""
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id, anime_name, season_num, summary_text,
                    photo_file_id, created_by, created_at, updated_at
                FROM season_summaries
                WHERE id = ?
                """,
                (summary_id,),
            ).fetchone()
            return dict(row) if row else None

    def set_season_summary(
        self,
        anime_name: str,
        season_num: str,
        summary_text: str,
        photo_file_id: Optional[str] = None,
        created_by: Optional[int] = None,
    ) -> None:
        """ثبت/به‌روزرسانی خلاصه فصل (upsert روی نام+فصل).

        در به‌روزرسانی، created_by رکورد اصلی حفظ می‌شود.
        """
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO season_summaries (
                    anime_name, season_num, summary_text,
                    photo_file_id, created_by, updated_at
                )
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(anime_name, season_num) DO UPDATE SET
                    summary_text = excluded.summary_text,
                    photo_file_id = excluded.photo_file_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    anime_name,
                    season_num or "",
                    summary_text,
                    photo_file_id,
                    created_by,
                ),
            )

    def delete_season_summary(
        self,
        anime_name: str,
        season_num: str,
    ) -> bool:
        """حذف خلاصه فصل؛ خروجی = آیا رکوردی حذف شد."""
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM season_summaries "
                "WHERE anime_name = ? AND season_num = ?",
                (anime_name, season_num or ""),
            )
            return cursor.rowcount > 0
