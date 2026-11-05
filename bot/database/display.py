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
        """نگاشت نام واقعی → برچسب سطح-نام (ردیف‌های season='' part='').

        R12: ردیف‌های سطح فصل/پارت اینجا دیده نمی‌شوند — این نگاشت
        همان رفتار قدیمی را برای لیست اول مدیریت حفظ می‌کند.
        """
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT anime_name, display_name "
                "FROM anime_display_names "
                "WHERE season_num = '' AND part_num = ''"
            ).fetchall()

        return {row["anime_name"]: row["display_name"] for row in rows}

    # ------------------------------------------------------------------
    # R12: نام ظاهری در سطح (نام واقعی، فصل، پارت)
    # ------------------------------------------------------------------
    def get_display_for(
        self,
        anime_name: str,
        season_num: Optional[str] = None,
        part_num: Optional[str] = None,
    ) -> str:
        """نام ظاهری مؤثر برای یک فصل/پارت مشخص.

        زنجیره: ردیف دقیق (نام، فصل، پارت) → برچسب پیش‌فرض کل نام
        (ردیف سطح-نام) → خود نام واقعی. هرگز از پارت دیگری ارث نمی‌برد.
        """
        season = str(season_num or "").strip()
        part = str(part_num or "").strip()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT display_name FROM anime_display_names "
                "WHERE anime_name = ? AND season_num = ? AND part_num = ?",
                (anime_name, season, part),
            ).fetchone()
            if row:
                return row["display_name"]
            row = connection.execute(
                "SELECT display_name FROM anime_display_names "
                "WHERE anime_name = ? AND season_num = '' AND part_num = ''",
                (anime_name,),
            ).fetchone()

        return row["display_name"] if row else anime_name

    def set_display_for(
        self,
        anime_name: str,
        season_num: Optional[str],
        part_num: Optional[str],
        display_name: str,
    ) -> None:
        """ثبت/به‌روزرسانی نام ظاهری برای همین (نام، فصل، پارت)."""
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO anime_display_names
                    (anime_name, season_num, part_num, display_name)
                VALUES (?, ?, ?, ?)
                """,
                (
                    anime_name,
                    str(season_num or "").strip(),
                    str(part_num or "").strip(),
                    display_name,
                ),
            )

    def clear_display_for(
        self,
        anime_name: str,
        season_num: Optional[str],
        part_num: Optional[str],
    ) -> bool:
        """حذف ردیف سطح فصل/پارت (بازگشت به پیش‌فرض)."""
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM anime_display_names "
                "WHERE anime_name = ? AND season_num = ? AND part_num = ?",
                (
                    anime_name,
                    str(season_num or "").strip(),
                    str(part_num or "").strip(),
                ),
            )
            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # B1: نام ظاهری در سطح *لینک* (session_id) — دکمه جزئیات لینک
    # ------------------------------------------------------------------
    def get_link_display(self, session_id: str) -> Optional[str]:
        """alias اختصاصی خود لینک؛ None یعنی ارثی (فصل → نام → واقعی)."""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT display_name FROM link_display_names "
                "WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return row["display_name"] if row else None

    def set_link_display(
        self,
        session_id: str,
        display_name: str,
    ) -> None:
        """ثبت/به‌روزرسانی alias سطح لینک (فقط همین لینک)."""
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO link_display_names
                    (session_id, display_name, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                """,
                (session_id, display_name),
            )

    def clear_link_display(self, session_id: str) -> bool:
        """حذف alias سطح لینک ⇒ بازگشت به ارثی فصل/نام/واقعی."""
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM link_display_names WHERE session_id = ?",
                (session_id,),
            )
            return cursor.rowcount > 0

    def get_effective_display_for_link(
        self,
        session_id: str,
    ) -> Optional[str]:
        """نام ظاهری مؤثر یک لینک: alias خود لینک → فصل/پارت → سطح-نام
        → نام واقعی. اگر لینک وجود نداشته باشد None."""
        with self.connect() as connection:
            link = connection.execute(
                "SELECT anime_name, season_num, part_num "
                "FROM uploads WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if not link:
            return None
        own = self.get_link_display(session_id)
        if own:
            return own
        return self.get_display_for(
            link["anime_name"],
            link["season_num"],
            link["part_num"],
        )

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
                        (anime_name, season_num, part_num, display_name)
                    VALUES (?, '', '', ?)
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
                    "WHERE anime_name = ? "
                    "AND season_num = '' AND part_num = ''",
                    (name,),
                )
                if cursor.rowcount:
                    removed.append(name)

        return removed

    def get_alias_groups(
        self,
        term: Optional[str] = None,
        sort: str = "alpha",
    ) -> List[Dict[str, Any]]:
        """R12-2: همه گروه‌های سطح ۱ (بدون صفحه‌بندی)."""
        return self._display_name_rows(term, sort)

    def get_l1_entry_for(self, anime_name: str) -> Optional[Dict[str, Any]]:
        """R16: ردیف سطح ۱ (نام ظاهری + اعضا) که این نام واقعی در آن است.

        برای «پرش مستقیم» جستجو به فصل/پارت/سینمایی؛ None یعنی یتیم.
        """
        if not anime_name:
            return None
        for group in self._display_name_rows():
            if anime_name in (group.get("names") or []):
                return group
        return None

    def _display_name_rows(
        self,
        term: Optional[str] = None,
        sort: str = "alpha",
        all_extras: bool = True,
    ) -> List[Dict[str, Any]]:
        """سطح ۱ (R12-2): گروه‌بندی بر اساس نام ظاهری *مؤثر* به‌ازای
        هر (نام واقعی، نوع، فصل، پارت).

        نام ظاهری مؤثر = ردیف دقیق سطح فصل/پارت → برچسب پیش‌فرض کل
        نام (سطح-نام) → خود نام واقعی. دو عضو با نام ظاهری مؤثر برابر
        در یک ردیف ادغام می‌شوند (حتی با نام‌های واقعی متفاوت)؛ عضو با
        نام ظاهری یکتا = یک انیمه جدا.

        شکل ردیف:
        - display_name: نام ظاهری گروه
        - members: ردیف‌های آماده سطح ۲ (هر عضو = نام/نوع/فصل/پارت +
          links + is_cinema) — مرتب با همان کلید سطح ۲
        - names: نام‌های واقعی اعضا (یکتا)
        - links: جمع لینک‌ها — cinema: OR — (کلیدهای سازگار با قبل)
        """
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    anime_name,
                    COALESCE(anime_type, '') AS anime_type,
                    COALESCE(season_num, '') AS season_num,
                    COALESCE(part_num, '') AS part_num,
                    COUNT(*) AS links,
                    MAX(
                        CASE
                            WHEN COALESCE(anime_type, '') = 'سینمایی'
                            THEN 1 ELSE 0
                        END
                    ) AS is_cinema,
                    MAX(created_at) AS last_created
                FROM uploads
                WHERE session_id NOT IN (
                    SELECT session_id FROM link_display_names
                )
                GROUP BY
                    anime_name,
                    COALESCE(anime_type, ''),
                    COALESCE(season_num, ''),
                    COALESCE(part_num, '')
                """
            ).fetchall()
            # B1: لینک‌هایی که alias اختصاصی دارند ⇒ عضو لینک‌محور جدا
            aliased_rows = connection.execute(
                """
                SELECT
                    uploads.session_id,
                    uploads.anime_name,
                    COALESCE(uploads.anime_type, '') AS anime_type,
                    COALESCE(uploads.season_num, '') AS season_num,
                    COALESCE(uploads.part_num, '') AS part_num,
                    uploads.created_at AS last_created,
                    link_display_names.display_name AS display_name
                FROM uploads
                JOIN link_display_names
                    ON uploads.session_id = link_display_names.session_id
                """
            ).fetchall()
            alias_rows = connection.execute(
                "SELECT anime_name, season_num, part_num, display_name "
                "FROM anime_display_names"
            ).fetchall()

        season_labels: Dict[Tuple[str, str, str], str] = {}
        legacy_labels: Dict[str, str] = {}
        for alias_row in alias_rows:
            key = (
                alias_row["anime_name"],
                alias_row["season_num"] or "",
                alias_row["part_num"] or "",
            )
            if key[1] == "" and key[2] == "":
                legacy_labels[key[0]] = alias_row["display_name"]
            else:
                season_labels[key] = alias_row["display_name"]

        groups: Dict[str, Dict[str, Any]] = {}

        def _add_group(
            display: str,
            physical: str,
            member: Dict[str, Any],
            links: int,
            cinema: int,
            last_created: Any,
        ) -> None:
            group = groups.get(display)
            if group is None:
                groups[display] = {
                    "display_name": display,
                    "names": [physical],
                    "members": [member],
                    "links": links,
                    "cinema": cinema,
                    "last_created": last_created,
                }
                return

            if physical not in group["names"]:
                group["names"].append(physical)
            group["members"].append(member)
            group["links"] += links
            group["cinema"] = max(group["cinema"], cinema)
            if last_created and (
                not group["last_created"] or last_created > group["last_created"]
            ):
                group["last_created"] = last_created

        for row in rows:
            physical = row["anime_name"]
            season = row["season_num"] or ""
            part = row["part_num"] or ""
            display = (
                season_labels.get((physical, season, part))
                or legacy_labels.get(physical)
                or physical
            )
            member = {
                "anime_name": physical,
                "anime_type": row["anime_type"] or "",
                "season_num": season,
                "part_num": part,
                "links": row["links"],
                "is_cinema": row["is_cinema"],
            }
            _add_group(
                display,
                physical,
                member,
                row["links"],
                row["is_cinema"],
                row["last_created"],
            )

        for row in aliased_rows:
            physical = row["anime_name"]
            cinema = 1 if (row["anime_type"] or "") == "سینمایی" else 0
            member = {
                "anime_name": physical,
                "anime_type": row["anime_type"] or "",
                "season_num": row["season_num"] or "",
                "part_num": row["part_num"] or "",
                "links": 1,
                "is_cinema": cinema,
                # نشانهٔ عضو لینک‌محور — سطح ۲ مستقیم به جزئیات می‌پرد
                "session_id": row["session_id"],
            }
            _add_group(
                row["display_name"],
                physical,
                member,
                1,
                cinema,
                row["last_created"],
            )

        result = list(groups.values())

        if term:
            needle = term.lower()
            # R16: اسم‌های جستجوی اضافی هم والد خود را بالا می‌آورند —
            # all_extras=False فقط دامنهٔ «انیمه» را حساب می‌کند (مبنای
            # تصمیم «پرش مستقیم» در handle_search_input).
            extra_hit_names = {
                row["anime_name"]
                for row in self.search_extra_names(needle)
                if all_extras or row["scope"] == "anime"
            }
            result = [
                group
                for group in result
                if needle in group["display_name"].lower()
                or any(
                    needle in name.lower() for name in group["names"]
                )
                or any(
                    name in extra_hit_names for name in group["names"]
                )
            ]

        # اعضا با همان کلید مرتب‌سازی سطح ۲ (سریالی اول، سینمایی آخر)
        for group in result:
            group["members"].sort(key=self._group_sort_key)

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
