"""گروه‌بندی سلسله‌مراتبی و تغییرنام."""

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

class GroupsMixin:

    def list_anime_names(
        self,
        term: Optional[str] = None,
        sort: str = "alpha",
        page: int = 0,
    ) -> List[Dict[str, Any]]:
        """سطح ۱: فهرست برچسب‌های ظاهری (پس از ادغام) با تعداد لینک."""
        start = page * config.PAGE_SIZE
        rows = self._display_name_rows(term, sort)
        return rows[start:start + config.PAGE_SIZE]

    def count_anime_names(
        self,
        term: Optional[str] = None,
    ) -> int:
        """تعداد ردیف‌های سطح ۱ پس از ادغام بر اساس برچسب."""
        return len(self._display_name_rows(term))

    @staticmethod
    def _group_sort_key(group: Dict[str, Any]) -> tuple:
        """مرتب‌سازی سطح ۲: سریالی‌ها (عددی ↑، غیرعددی، بدون فصل) سپس فیلم‌ها."""
        cinema = 1 if group.get("is_cinema") else 0

        season = group.get("season_num") or ""
        if season.isdigit():
            season_key = (0, int(season), "")
        elif season:
            season_key = (1, 0, season)
        else:
            season_key = (2, 0, "")

        part = group.get("part_num") or ""
        if part.isdigit():
            part_key = (0, int(part), "")
        elif part:
            part_key = (1, 0, part)
        else:
            part_key = (2, 0, "")

        return (cinema, season_key, part_key)

    def get_upload_groups(
        self,
        anime_name: str,
    ) -> List[Dict[str, Any]]:
        """سطح ۲: گروه‌های (نوع, فصل, پارت) یک انیمه با تعداد لینک.

        گروه‌های سینمایی و سریالی از هم جدا می‌شوند (رفع باگ نام مخلوط:
        فیلم «شماره 1» دیگر با «فصل 1» ادغام نمی‌شود).
        خروجی مرتب‌شده: سریالی‌ها اول، فیلم‌ها آخر.
        """
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    COALESCE(anime_type, '') AS anime_type,
                    COALESCE(season_num, '') AS season_num,
                    COALESCE(part_num, '') AS part_num,
                    COUNT(*) AS links,
                    MAX(
                        CASE
                            WHEN COALESCE(anime_type, '') = 'سینمایی'
                            THEN 1 ELSE 0
                        END
                    ) AS is_cinema
                FROM uploads
                WHERE anime_name = ?
                GROUP BY
                    COALESCE(anime_type, ''),
                    COALESCE(season_num, ''),
                    COALESCE(part_num, '')
                """,
                (anime_name,),
            ).fetchall()

        groups = [dict(row) for row in rows]
        groups.sort(key=self._group_sort_key)

        return groups

    def get_combined_groups(
        self,
        anime_names: List[str],
    ) -> List[Dict[str, Any]]:
        """گروه‌های چند نام واقعی زیر هم (برای ردیف ادغام‌شده سطح ۱).

        هر گروه کلید `anime_name` (نام واقعی خودش) را حمل می‌کند تا
        کوئری‌های سطح ۳/۴ با نام درست زده شوند. مرتب‌سازی: همان کلید سطح ۲.
        """
        combined: List[Dict[str, Any]] = []
        for physical in anime_names:
            for group in self.get_upload_groups(physical):
                group["anime_name"] = physical
                combined.append(group)

        combined.sort(key=self._group_sort_key)
        return combined

    def get_episode_entries(
        self,
        anime_name: str,
        season_num: str,
        part_num: str,
        anime_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """سطح ۳: قسمت‌های یک گروه (هر آپلود جدا = یک ورودی).

        با anime_type گروه فیلتر می‌کند تا لینک‌های فیلم/سریال مخلوط نشود.
        """
        where_clause = """
                anime_name = ?
                AND COALESCE(season_num, '') = COALESCE(?, '')
                AND COALESCE(part_num, '') = COALESCE(?, '')
        """
        params: List[Any] = [anime_name, season_num, part_num]

        if anime_type is not None:
            where_clause += (
                " AND COALESCE(anime_type, '') = COALESCE(?, '')"
            )
            params.append(anime_type)

        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    COALESCE(episode_range, '') AS episode_range,
                    COUNT(*) AS links
                FROM uploads
                WHERE {where_clause}
                GROUP BY COALESCE(episode_range, '')
                """,
                params,
            ).fetchall()

        return [dict(row) for row in rows]

    def get_group_links(
        self,
        anime_name: str,
        season_num: str,
        part_num: str,
        episode_range: Optional[str] = None,
        anime_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """سطح ۴: لینک‌های (نوع+نام+فصل+پارت)؛ برای سینمایی episode_range=None
        ⇒ همه قسمت‌های آن شماره (ادغام سطح «قسمت» طبق R5).

        با anime_type گروه فیلتر می‌کند تا لینک‌های فیلم/سریال مخلوط نشود.
        """
        where_clause = """
                anime_name = ?
                AND COALESCE(season_num, '') = COALESCE(?, '')
                AND COALESCE(part_num, '') = COALESCE(?, '')
        """
        params: List[Any] = [anime_name, season_num, part_num]

        if anime_type is not None:
            where_clause += (
                " AND COALESCE(anime_type, '') = COALESCE(?, '')"
            )
            params.append(anime_type)

        if episode_range is not None:
            where_clause += (
                " AND COALESCE(episode_range, '') = COALESCE(?, '')"
            )
            params.append(episode_range)

        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    session_id,
                    quality,
                    channel_msg_range,
                    COALESCE(status, 'active') AS status,
                    COALESCE(is_finished, 0) AS is_finished,
                    COALESCE(episode_range, '') AS episode_range
                FROM uploads
                WHERE {where_clause}
                ORDER BY quality
                """,
                params,
            ).fetchall()

        return [dict(row) for row in rows]

    def rename_animes(
        self,
        old_names: List[str],
        new_name: str,
    ) -> Tuple[int, int]:
        """نام واقعی یک یا چند انیمه را در uploads و ongoing_animes عوض می‌کند.

        اگر new_name از قبل وجود داشته باشد = ادغام واقعی (لینک‌ها زیر
        نام مقصد جمع می‌شوند). برچسب‌های ظاهری نام‌های قدیمی حذف می‌شوند؛
        هویت (برچسب) مقصد دست‌نخورده می‌ماند.
        خروجی: (تعداد لینک‌های تغییرکرده، تعداد انیمه‌های درحال پخش).
        """
        targets = [
            name
            for name in dict.fromkeys(old_names)
            if name and name != new_name
        ]

        uploads_count = 0
        ongoing_count = 0

        with self.connect() as connection:
            for old_name in targets:
                uploads_count += connection.execute(
                    """
                    UPDATE uploads
                    SET anime_name = ?
                    WHERE anime_name = ?
                    """,
                    (new_name, old_name),
                ).rowcount
                ongoing_count += connection.execute(
                    """
                    UPDATE ongoing_animes
                    SET
                        anime_name = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE anime_name = ?
                    """,
                    (new_name, old_name),
                ).rowcount
                # R10: انتقال خلاصه داستان فصل‌ها (در ادغام، مقصد برنده است)
                connection.execute(
                    """
                    DELETE FROM season_summaries
                    WHERE anime_name = ?
                      AND season_num IN (
                          SELECT season_num FROM season_summaries
                          WHERE anime_name = ?
                      )
                    """,
                    (old_name, new_name),
                )
                connection.execute(
                    "UPDATE season_summaries "
                    "SET anime_name = ? WHERE anime_name = ?",
                    (new_name, old_name),
                )
                connection.execute(
                    "DELETE FROM anime_display_names "
                    "WHERE anime_name = ?",
                    (old_name,),
                )

        return uploads_count, ongoing_count

    def is_cinema_name(self, anime_name: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM uploads
                WHERE
                    anime_name = ?
                    AND COALESCE(anime_type, '') = 'سینمایی'
                LIMIT 1
                """,
                (anime_name,),
            ).fetchone()

        return row is not None
