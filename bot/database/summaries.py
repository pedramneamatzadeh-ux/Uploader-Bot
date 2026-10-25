"""خلاصه داستان فصل/پارت (R10+B14) — یک خلاصه برای هر (نام، فصل، پارت).

ردیف‌های قدیمی (پیش از B14) با part_num='' ذخیره شده‌اند و به‌عنوان
«خلاصهٔ اشتراکی کل فصل» عمل می‌کنند: اگر برای (نام، فصل، پارت) خلاصهٔ
مستقیمی ثبت نشده باشد، همان ردیف اشتراکی برگردانده می‌شود (fallback).
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_SELECT_COLS = """
    id, anime_name, season_num, part_num, summary_text,
    photo_file_id, created_by, created_at, updated_at
"""


class SummariesMixin:
    def get_season_summary(
        self,
        anime_name: str,
        season_num: str,
        part_num: str = "",
    ) -> Optional[Dict[str, Any]]:
        """خلاصهٔ (نام، فصل، پارت)؛ fallback به ردیف اشتراکی part=''.

        اگر هیچ‌کدام ثبت نشده باشد None.
        """
        with self.connect() as connection:
            row = connection.execute(
                f"SELECT {_SELECT_COLS} FROM season_summaries "
                "WHERE anime_name = ? AND season_num = ? AND part_num = ?",
                (anime_name, season_num or "", part_num or ""),
            ).fetchone()
            if row is None and (part_num or "") != "":
                # B14: خلاصهٔ اشتراکی قدیمیِ کل فصل
                row = connection.execute(
                    f"SELECT {_SELECT_COLS} FROM season_summaries "
                    "WHERE anime_name = ? AND season_num = ? "
                    "AND part_num = ''",
                    (anime_name, season_num or ""),
                ).fetchone()
            return dict(row) if row else None

    def get_season_summary_by_id(
        self,
        summary_id: int,
    ) -> Optional[Dict[str, Any]]:
        """خلاصه با شماره رکورد — برای لینک اشتراک‌گذاری sm<id>."""
        with self.connect() as connection:
            row = connection.execute(
                f"SELECT {_SELECT_COLS} FROM season_summaries WHERE id = ?",
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
        part_num: str = "",
    ) -> None:
        """ثبت/به‌روزرسانی خلاصه (upsert روی نام+فصل+پارت).

        در به‌روزرسانی، created_by رکورد اصلی حفظ می‌شود. ردیف
        اشتراکی قدیمی (part='') دست‌نخورده می‌ماند تا پارت‌های دیگر
        همچنان fallback داشته باشند.
        """
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO season_summaries (
                    anime_name, season_num, part_num, summary_text,
                    photo_file_id, created_by, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(anime_name, season_num, part_num) DO UPDATE SET
                    summary_text = excluded.summary_text,
                    photo_file_id = excluded.photo_file_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    anime_name,
                    season_num or "",
                    part_num or "",
                    summary_text,
                    photo_file_id,
                    created_by,
                ),
            )

    def delete_season_summary(
        self,
        anime_name: str,
        season_num: str,
        part_num: str = "",
    ) -> bool:
        """حذف خلاصهٔ (نام، فصل، پارت)؛ اگر نبود، ردیف اشتراکی فصل.

        خروجی = آیا رکوردی حذف شد.
        """
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM season_summaries "
                "WHERE anime_name = ? AND season_num = ? AND part_num = ?",
                (anime_name, season_num or "", part_num or ""),
            )
            if cursor.rowcount == 0 and (part_num or "") != "":
                # آنچه کاربر دیده ردیف اشتراکی بوده ⇒ همان حذف می‌شود
                cursor = connection.execute(
                    "DELETE FROM season_summaries "
                    "WHERE anime_name = ? AND season_num = ? "
                    "AND part_num = ''",
                    (anime_name, season_num or ""),
                )
            return cursor.rowcount > 0
