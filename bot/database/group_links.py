"""R26: لینک گروه (فصل/پارت/سینمایی/OVA) + کوئری‌های پنل کاربر.

هر گروه یک `share_code` پایدار دارد که در لینک `?start=s_<code>` استفاده
می‌شود. حذف یا غیرفعال‌شدن لینک‌های کیفیت روی این کد اثری ندارد.
"""

import logging
import secrets
import sqlite3
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# پیشوند کد لینک گروه — session_idهای فعلی UUID هستند و هیچ‌وقت با s_
# شروع نمی‌شوند، پس تفکیک در /start بدون کوئری اضافه ممکن است.
GROUP_CODE_PREFIX = "s_"
_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"
_CODE_LEN = 8


class GroupLinkMixin:

    # ------------------------------------------------------------------
    # ساخت / خواندن کد
    # ------------------------------------------------------------------
    @staticmethod
    def _group_key(
        anime_name: str,
        season_num: Optional[str],
        part_num: Optional[str],
        anime_type: Optional[str],
    ) -> tuple:
        return (
            anime_name or "",
            (season_num or "").strip(),
            (part_num or "").strip(),
            (anime_type or "").strip(),
        )

    @staticmethod
    def _new_code() -> str:
        body = "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LEN))
        return GROUP_CODE_PREFIX + body

    def get_or_create_group_link(
        self,
        anime_name: str,
        season_num: Optional[str] = None,
        part_num: Optional[str] = None,
        anime_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """کد گروه را برمی‌گرداند؛ اگر نبود می‌سازد (idempotent).

        خروجی: {"share_code", "status", "created": bool}
        """
        key = self._group_key(anime_name, season_num, part_num, anime_type)

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT share_code, status
                FROM group_links
                WHERE anime_name = ?
                  AND season_num = ?
                  AND part_num = ?
                  AND anime_type = ?
                """,
                key,
            ).fetchone()

            if row:
                return {
                    "share_code": row["share_code"],
                    "status": row["status"],
                    "created": False,
                }

            # ساخت کد یکتا (تصادم تقریباً محال است، ولی محافظت داریم)
            for _ in range(10):
                code = self._new_code()
                try:
                    connection.execute(
                        """
                        INSERT INTO group_links (
                            anime_name, season_num, part_num,
                            anime_type, share_code
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (*key, code),
                    )
                    return {
                        "share_code": code,
                        "status": "active",
                        "created": True,
                    }
                except sqlite3.IntegrityError:
                    exists = connection.execute(
                        "SELECT share_code FROM group_links "
                        "WHERE anime_name = ? AND season_num = ? "
                        "AND part_num = ? AND anime_type = ?",
                        key,
                    ).fetchone()
                    if exists:  # درخواست هم‌زمان
                        return {
                            "share_code": exists["share_code"],
                            "status": "active",
                            "created": False,
                        }
                    continue

            raise sqlite3.IntegrityError(
                "ساخت کد یکتا برای لینک گروه ممکن نشد"
            )

    def get_group_link(self, share_code: str) -> Optional[Dict[str, Any]]:
        code = (share_code or "").strip()
        if not code.startswith(GROUP_CODE_PREFIX):
            return None

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    anime_name,
                    season_num,
                    part_num,
                    anime_type,
                    share_code,
                    status
                FROM group_links
                WHERE share_code = ?
                """,
                (code,),
            ).fetchone()

        return dict(row) if row else None

    def set_group_link_status(self, share_code: str, active: bool) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE group_links
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE share_code = ?
                """,
                ("active" if active else "inactive", (share_code or "").strip()),
            )
            return cursor.rowcount > 0

    def count_group_links(self) -> int:
        with self.connect() as connection:
            return connection.execute(
                "SELECT COUNT(*) FROM group_links"
            ).fetchone()[0]

    def _sync_group_link_type(self) -> int:
        """R26-fix: نوعِ ثبت‌شده در group_links را با uploads هم‌راستا می‌کند.

        اگر یک گروه (نام+فصل+پارت) در uploads فقط یک نوع داشته باشد، همان
        نوع در ردیف لینک ثبت می‌شود؛ ردیف‌های تکراری (هم‌گروه با نوع متفاوت)
        حذف نمی‌شوند ولی کد فعالِ آن‌ها به همین گروه اشاره می‌کند.
        خروجی: تعداد ردیف‌های اصلاح‌شده.
        """
        fixed = 0
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    anime_name,
                    COALESCE(season_num, '') AS season_num,
                    COALESCE(part_num, '') AS part_num,
                    GROUP_CONCAT(DISTINCT COALESCE(anime_type, '')) AS types
                FROM uploads
                GROUP BY anime_name, COALESCE(season_num, ''),
                         COALESCE(part_num, '')
                """
            ).fetchall()

            for row in rows:
                types = [t for t in (row["types"] or "").split(",") if t]
                if len(types) != 1:
                    continue
                cursor = connection.execute(
                    """
                    UPDATE group_links
                    SET anime_type = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE anime_name = ?
                      AND season_num = ?
                      AND part_num = ?
                      AND anime_type <> ?
                    """,
                    (
                        types[0],
                        row["anime_name"],
                        row["season_num"],
                        row["part_num"],
                        types[0],
                    ),
                )
                fixed += cursor.rowcount

        if fixed:
            logger.info("نوع %s ردیف لینک فصل با uploads هم‌راستا شد.", fixed)

        return fixed

    def _heal_orphan_group_links(self) -> int:
        """R26c: ردیف‌های لینکِ بی‌صاحب را به گروه واقعی وصل می‌کند.

        «بی‌صاحب» = ردیفی که (نام، فصل، پارت) آن دیگر در `uploads` نیست
        (مثلاً نام انیمه بعد از آپلود تغییر کرده است). اگر انیمه فقط **یک**
        گروه داشته باشد، ردیف به آن هدایت می‌شود؛ اگر مقصد از قبل ردیف
        داشته باشد، ردیف یتیم حذف می‌شود (کد مقصد می‌ماند).
        خروجی: تعداد ردیف‌های اصلاح/حذف‌شده.
        """
        changed = 0

        with self.connect() as connection:
            orphans = connection.execute(
                """
                SELECT id, anime_name, season_num, part_num, anime_type
                FROM group_links AS g
                WHERE NOT EXISTS (
                    SELECT 1 FROM uploads AS u
                    WHERE u.anime_name = g.anime_name
                      AND COALESCE(u.season_num, '') = g.season_num
                      AND COALESCE(u.part_num, '') = g.part_num
                )
                """
            ).fetchall()

            for row in orphans:
                targets = connection.execute(
                    """
                    SELECT COALESCE(season_num, '') AS season_num,
                           COALESCE(part_num, '') AS part_num,
                           COALESCE(anime_type, '') AS anime_type
                    FROM uploads
                    WHERE anime_name = ?
                    GROUP BY 1, 2, 3
                    """,
                    (row["anime_name"],),
                ).fetchall()

                if len(targets) != 1:
                    continue

                target = targets[0]
                taken = connection.execute(
                    """
                    SELECT id FROM group_links
                    WHERE anime_name = ? AND season_num = ?
                      AND part_num = ? AND id <> ?
                    """,
                    (
                        row["anime_name"],
                        target["season_num"],
                        target["part_num"],
                        row["id"],
                    ),
                ).fetchone()

                if taken:
                    connection.execute(
                        "DELETE FROM group_links WHERE id = ?", (row["id"],)
                    )
                else:
                    connection.execute(
                        """
                        UPDATE group_links
                        SET season_num = ?, part_num = ?, anime_type = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (
                            target["season_num"],
                            target["part_num"],
                            target["anime_type"],
                            row["id"],
                        ),
                    )
                changed += 1

        if changed:
            logger.warning(
                "%s ردیف لینک فصل که با فصل/پارت واقعی هم‌خوان نبود اصلاح شد.",
                changed,
            )

        return changed

    def backfill_group_links(self) -> int:
        """R26: برای همهٔ گروه‌های موجود در uploads کد لینک می‌سازد.

        یک‌بار در استارت اجرا می‌شود؛ گروه‌های دارای کد دست‌نخورده می‌مانند.
        خروجی: تعداد کدهای تازه‌ساخته‌شده.
        """
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT
                    anime_name,
                    COALESCE(season_num, '') AS season_num,
                    COALESCE(part_num, '') AS part_num,
                    COALESCE(anime_type, '') AS anime_type
                FROM uploads
                """
            ).fetchall()

        self._sync_group_link_type()
        self._heal_orphan_group_links()

        created = 0
        for row in rows:
            if not row["anime_name"]:
                continue
            result = self.get_or_create_group_link(
                row["anime_name"],
                row["season_num"],
                row["part_num"],
                row["anime_type"],
            )
            if result["created"]:
                created += 1

        if created:
            logger.info("%s لینک فصل/پارت ساخته شد.", created)

        return created

    # ------------------------------------------------------------------
    # دادهٔ پنل کاربر
    # ------------------------------------------------------------------
    def _resolve_scope(self, group: Dict[str, Any]) -> Dict[str, Any]:
        """R26c: اگر (نام، فصل، پارت) این ردیف در uploads چیزی نداشت،
        نزدیک‌ترین گروهِ همان انیمه را برمی‌گرداند.

        فقط وقتی که آن انیمه **دقیقاً یک** گروه (فصل/پارت) در uploads
        داشته باشد — تا هرگز فایل‌های فصل دیگری به کاربر نشان داده نشود.
        """
        name = group.get("anime_name") or ""
        season = group.get("season_num") or ""
        part = group.get("part_num") or ""

        with self.connect() as connection:
            count = connection.execute(
                """
                SELECT COUNT(*) FROM uploads
                WHERE anime_name = ?
                  AND COALESCE(season_num, '') = ?
                  AND COALESCE(part_num, '') = ?
                """,
                (name, season, part),
            ).fetchone()[0]

            if count:
                return group

            rows = connection.execute(
                """
                SELECT
                    COALESCE(season_num, '') AS season_num,
                    COALESCE(part_num, '') AS part_num
                FROM uploads
                WHERE anime_name = ?
                GROUP BY 1, 2
                """,
                (name,),
            ).fetchall()

        if len(rows) != 1:
            return group

        fixed = dict(group)
        fixed["season_num"] = rows[0]["season_num"]
        fixed["part_num"] = rows[0]["part_num"]
        logger.warning(
            "لینک فصل %s: فصل/پارت %r/%r در uploads نبود؛ به %r/%r هدایت شد.",
            group.get("share_code"),
            season,
            part,
            fixed["season_num"],
            fixed["part_num"],
        )
        return fixed

    def get_group_qualities(self, group: Dict[str, Any]) -> List[Dict[str, Any]]:
        """کیفیت‌های موجود یک گروه با تعداد قسمت و لینک فعال."""
        group = self._resolve_scope(group)

        # R26-fix: فقط نام+فصل+پارت معیار است؛ `anime_type` فقط تعیین‌کنندهٔ
        # «سینمایی بودن» (برای برچسب) است، نه فیلتر سخت — ردیف group_links
        # ممکن است از مسیری با نوع خالی/متفاوت ساخته شده باشد و نباید پنل
        # را خالی کند. گروه سینمایی/سریالیِ هم‌نام با شمارهٔ متفاوت هم جدا
        # می‌ماند (شماره فصل/پارت بخشی از کلید است).
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    quality,
                    COUNT(DISTINCT COALESCE(episode_range, '')) AS episodes,
                    SUM(
                        CASE WHEN COALESCE(status, 'active') = 'active'
                             THEN 1 ELSE 0 END
                    ) AS active_links,
                    COUNT(*) AS links
                FROM uploads
                WHERE anime_name = ?
                  AND COALESCE(season_num, '') = COALESCE(?, '')
                  AND COALESCE(part_num, '') = COALESCE(?, '')
                GROUP BY quality
                """,
                (
                    group.get("anime_name", ""),
                    group.get("season_num", ""),
                    group.get("part_num", ""),
                ),
            ).fetchall()

        result = [
            dict(row) for row in rows
            if row["active_links"]  # کیفیت بدون لینک فعال نمایش داده نشود
        ]
        from ..constants import ALL_QUALITIES

        order = {q: idx for idx, q in enumerate(ALL_QUALITIES)}
        result.sort(
            key=lambda row: (
                order.get(row.get("quality"), 99),
                row.get("quality") or "",
            )
        )
        return result

    def get_group_episodes(
        self,
        group: Dict[str, Any],
        quality: str,
    ) -> List[Dict[str, Any]]:
        """قسمت‌های یک کیفیت در یک گروه.

        خروجی: [{"episode_range", "links", "session_ids": [...]}] — مرتب‌سازی
        در لایهٔ نمایش انجام می‌شود (جدیدترین اول).
        """
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    COALESCE(episode_range, '') AS episode_range,
                    COUNT(*) AS links,
                    GROUP_CONCAT(session_id, '|') AS session_ids,
                    SUM(
                        CASE WHEN COALESCE(status, 'active') = 'active'
                             THEN 1 ELSE 0 END
                    ) AS active_links
                FROM uploads
                WHERE anime_name = ?
                  AND COALESCE(season_num, '') = COALESCE(?, '')
                  AND COALESCE(part_num, '') = COALESCE(?, '')
                  AND quality = ?
                GROUP BY COALESCE(episode_range, '')
                """,
                (
                    group.get("anime_name", ""),
                    group.get("season_num", ""),
                    group.get("part_num", ""),
                    quality,
                ),
            ).fetchall()

        episodes: List[Dict[str, Any]] = []
        for row in rows:
            if not row["active_links"]:
                continue
            episode = dict(row)
            episode["session_ids"] = [
                item for item in (row["session_ids"] or "").split("|") if item
            ]
            episodes.append(episode)

        return episodes
