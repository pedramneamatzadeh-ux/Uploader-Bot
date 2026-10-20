"""نام‌های ظاهری انیمه‌ها (جدول anime_display_names)."""

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

class DisplayMixin:

    # ------------------------------------------------------------------
    # سلسله‌مراتب «مدیریت فایل‌ها» (مرحله ۴ — R5)
    # ------------------------------------------------------------------
    def get_display_map(self) -> Dict[str, str]:
        """نگاشت نام واقعی → برچسب ظاهری (فقط ردیف‌های دارای برچسب)."""
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT anime_name, display_name "
                "FROM anime_display_names"
            ).fetchall()

        return {row["anime_name"]: row["display_name"] for row in rows}

    def set_display_names(
        self,
        anime_names: List[str],
        display_name: str,
    ) -> int:
        """برچسب ظاهری را برای نام(های) واقعی ثبت/به‌روز می‌کند.

        فقط برچسب سطح ۱ عوض می‌شود؛ نام لینک‌ها و رکوردها دست نمی‌خورند.
        """
        with self.connect() as connection:
            for name in anime_names:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO anime_display_names
                        (anime_name, display_name)
                    VALUES (?, ?)
                    """,
                    (name, display_name),
                )

        return len(anime_names)

    def names_for_display(self, display_name: str) -> List[str]:
        """نام‌های واقعی که برچسب ظاهری‌شان برابر display_name است."""
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT anime_name FROM uploads"
            ).fetchall()

        display_map = self.get_display_map()
        return [
            row["anime_name"]
            for row in rows
            if display_map.get(row["anime_name"], row["anime_name"])
            == display_name
        ]

    def split_display_name(
        self,
        anime_name: str,
        shared_display: str,
        members: List[str],
    ) -> List[str]:
        """عضو را از ردیف ادغام‌شده جدا می‌کند (حذف برچسبش).

        اگر برچسب مشترک == نام واقعی عضو انتخابی، برچسب بقیه اعضا هم
        حذف می‌شود (وگرنه دوباره کنار هم گروه می‌شوند ⇒ کل ادغام باز می‌شود).
        خروجی: نام‌هایی که برچسب‌شان حذف شد.
        """
        if shared_display == anime_name:
            targets = list(dict.fromkeys(members))
        else:
            targets = [anime_name]

        removed: List[str] = []
        with self.connect() as connection:
            for name in targets:
                cursor = connection.execute(
                    "DELETE FROM anime_display_names "
                    "WHERE anime_name = ?",
                    (name,),
                )
                if cursor.rowcount:
                    removed.append(name)

        return removed

    def _display_name_rows(
        self,
        term: Optional[str] = None,
        sort: str = "alpha",
    ) -> List[Dict[str, Any]]:
        """سطح ۱: گروه‌بندی انیمه‌ها بر اساس برچسب ظاهری.

        ردیف‌هایی که برچسب یکسان داشته باشند یکی می‌شوند (ادغام ظاهری):
        جمع لینک‌ها، پرچم سینمایی OR، لیست نام‌های واقعی.
        """
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    anime_name,
                    COUNT(*) AS links,
                    MAX(
                        CASE
                            WHEN COALESCE(anime_type, '') = 'سینمایی'
                            THEN 1 ELSE 0
                        END
                    ) AS cinema,
                    MAX(created_at) AS last_created
                FROM uploads
                GROUP BY anime_name
                """
            ).fetchall()

        display_map = self.get_display_map()
        groups: Dict[str, Dict[str, Any]] = {}

        for row in rows:
            physical = row["anime_name"]
            display = display_map.get(physical, physical)
            group = groups.get(display)
            if group is None:
                groups[display] = {
                    "display_name": display,
                    "names": [physical],
                    "links": row["links"],
                    "cinema": row["cinema"],
                    "last_created": row["last_created"],
                }
                continue

            group["names"].append(physical)
            group["links"] += row["links"]
            group["cinema"] = max(group["cinema"], row["cinema"])
            last = row["last_created"]
            if last and (
                not group["last_created"] or last > group["last_created"]
            ):
                group["last_created"] = last

        result = list(groups.values())

        if term:
            needle = term.lower()
            result = [
                group
                for group in result
                if needle in group["display_name"].lower()
                or any(
                    needle in name.lower() for name in group["names"]
                )
            ]

        # مرتب‌سازی مثل `_ANIME_SORTS` قبلی، اما روی برچسب/گروه
        if sort == "new":
            result.sort(key=lambda group: group["display_name"])
            result.sort(
                key=lambda group: group["last_created"] or "",
                reverse=True,
            )
        elif sort == "old":
            result.sort(key=lambda group: group["display_name"])
            result.sort(key=lambda group: group["last_created"] or "")
        elif sort == "count":
            result.sort(key=lambda group: group["display_name"])
            result.sort(key=lambda group: group["links"], reverse=True)
        else:  # alpha (پیش‌فرض)
            result.sort(key=lambda group: group["display_name"])

        for group in result:
            group.pop("last_created", None)

        return result
