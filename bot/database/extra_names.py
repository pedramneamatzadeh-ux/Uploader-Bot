# -*- coding: utf-8 -*-
"""R16 — اسم‌های واقعیِ اضافی (فقط جستجو) در سه دامنه.

- ``scope='anime'``: برای همهٔ فصل/پارت/سینمایی‌های یک نام واقعی —
  در سطح ۱ مدیریت برای **هر** نام واقعی ردیف ثبت می‌شود تا پس از
  «✂️ جداسازی» هم اسم‌ها زیر هر نام بمانند.
- ``scope='group'``: فقط یک فصل/پارت/سینمایی (سه‌گانه نام، فصل، پارت).
- ``scope='link'``: فقط یک لینک (session_id).

تصمیم‌های کاربر: فقط انگلیسی (validate_anime_name)، فقط در جستجوی
مدیریت اثر می‌کند (جای دیگری نمایش داده نمی‌شود)، افزودن گروهی با
جداکنندهٔ «,» یا «،». یکتایی بدون حساسیت به بزرگی/کوچکی حروف
(COLLATE NOCASE روی ستون + INSERT OR IGNORE).
"""
from typing import Any, Dict, List, Optional


class ExtraNamesMixin:
    def add_extra_names(
        self,
        scope: str,
        extra_names: List[str],
        real_names: Optional[List[str]] = None,
        season_num: str = "",
        part_num: str = "",
        session_id: str = "",
    ) -> List[str]:
        """اسم‌های اضافی را ثبت می‌کند؛ فهرست اسم‌هایی که *واقعاً* اضافه
        شدند (تکراری‌ها — حتی با حروف بزرگ/کوچک متفاوت — حذف می‌شوند).

        anchors: در ``anime`` همهٔ real_names؛ در ``group`` اولین real_name
        به‌همراه season/part؛ در ``link`` اولین real_name به‌همراه session_id.
        """
        names_in = [n for n in (real_names or []) if n]
        if scope == "anime":
            anchors = [(n, "", "", "") for n in names_in]
        elif scope == "group":
            anchors = [
                (names_in[0] if names_in else "",
                 season_num or "", part_num or "", "")
            ]
        elif scope == "link":
            anchors = [
                (names_in[0] if names_in else "",
                 "", "", session_id or "")
            ]
        else:
            raise ValueError(f"دامنهٔ نامعتبر: {scope}")

        added: List[str] = []
        seen = set()
        with self.connect() as connection:
            for raw in extra_names:
                clean = (raw or "").strip()
                if not clean or clean.lower() in seen:
                    continue
                seen.add(clean.lower())
                hit = 0
                for anchor in anchors:
                    cur = connection.execute(
                        "INSERT OR IGNORE INTO anime_extra_names ("
                        "  scope, anime_name, season_num, part_num,"
                        "  session_id, extra_name"
                        ") VALUES (?, ?, ?, ?, ?, ?)",
                        (scope, anchor[0], anchor[1], anchor[2],
                         anchor[3], clean),
                    )
                    hit += cur.rowcount or 0
                if hit:
                    added.append(clean)
        return added

    def list_extra_names(
        self,
        scope: str,
        real_names: Optional[List[str]] = None,
        season_num: str = "",
        part_num: str = "",
        session_id: str = "",
    ) -> List[str]:
        """اسم‌های اضافیِ یک دامنه (یکتا، مرتب الفبایی بدون حساسیت حروف)."""
        names_in = [n for n in (real_names or []) if n]
        with self.connect() as connection:
            if scope == "anime":
                if not names_in:
                    return []
                marks = ",".join("?" * len(names_in))
                rows = connection.execute(
                    "SELECT DISTINCT extra_name FROM anime_extra_names "
                    f"WHERE scope = 'anime' AND anime_name IN ({marks}) "
                    "ORDER BY extra_name",
                    names_in,
                ).fetchall()
            elif scope == "group":
                rows = connection.execute(
                    "SELECT DISTINCT extra_name FROM anime_extra_names "
                    "WHERE scope = 'group' AND anime_name = ? "
                    "AND season_num = ? AND part_num = ? "
                    "ORDER BY extra_name",
                    (names_in[0] if names_in else "",
                     season_num or "", part_num or ""),
                ).fetchall()
            else:  # link
                rows = connection.execute(
                    "SELECT DISTINCT extra_name FROM anime_extra_names "
                    "WHERE scope = 'link' AND session_id = ? "
                    "ORDER BY extra_name",
                    (session_id or "",),
                ).fetchall()
            return [r[0] for r in rows]

    def delete_extra_name(
        self,
        scope: str,
        extra_name: str,
        real_names: Optional[List[str]] = None,
        season_num: str = "",
        part_num: str = "",
        session_id: str = "",
    ) -> int:
        """حذف یک اسم اضافی از دامنه؛ تعداد ردیف‌های حذف‌شده."""
        names_in = [n for n in (real_names or []) if n]
        with self.connect() as connection:
            if scope == "anime":
                if not names_in:
                    return 0
                marks = ",".join("?" * len(names_in))
                cur = connection.execute(
                    "DELETE FROM anime_extra_names "
                    "WHERE scope = 'anime' AND extra_name = ? "
                    f"AND anime_name IN ({marks})",
                    [extra_name] + names_in,
                )
            elif scope == "group":
                cur = connection.execute(
                    "DELETE FROM anime_extra_names "
                    "WHERE scope = 'group' AND extra_name = ? "
                    "AND anime_name = ? AND season_num = ? AND part_num = ?",
                    (extra_name, names_in[0] if names_in else "",
                     season_num or "", part_num or ""),
                )
            else:  # link
                cur = connection.execute(
                    "DELETE FROM anime_extra_names "
                    "WHERE scope = 'link' AND extra_name = ? "
                    "AND session_id = ?",
                    (extra_name, session_id or ""),
                )
            return cur.rowcount or 0

    def delete_link_extra_names(self, session_id: str) -> int:
        """پاک‌سازی اسم‌های لینک‌محور هنگام حذف خود لینک."""
        with self.connect() as connection:
            cur = connection.execute(
                "DELETE FROM anime_extra_names "
                "WHERE scope = 'link' AND session_id = ?",
                (session_id or "",),
            )
            return cur.rowcount or 0

    def search_extra_names(self, term: str) -> List[Dict[str, Any]]:
        """تطابق بریده‌ای و بدون حساسیت حروف روی همهٔ دامنه‌ها.

        خروجی: ردیف‌های dict با scope/anime_name/season_num/part_num/
        session_id/extra_name — لایهٔ جستجو از آن برای «پرش مستقیم»
        (یک نتیجهٔ فصل/لینک) و ادغام والد در لیست سطح ۱ استفاده می‌کند.
        """
        needle = (term or "").strip()
        if not needle:
            return []
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT scope, anime_name, season_num, part_num, "
                "       session_id, extra_name "
                "FROM anime_extra_names "
                "WHERE extra_name LIKE '%' || ? || '%'",
                (needle,),
            ).fetchall()
            return [
                {
                    "scope": r[0],
                    "anime_name": r[1],
                    "season_num": r[2],
                    "part_num": r[3],
                    "session_id": r[4],
                    "extra_name": r[5],
                }
                for r in rows
            ]
