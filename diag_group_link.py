# -*- coding: utf-8 -*-
"""عیب‌یابِ لینک فصل — روی سرور اجرا کن:  python3 diag_group_link.py [کد یا نام انیمه]

بدون اتصال به تلگرام کار می‌کند و فقط دیتابیس را می‌خواند. اگر کد لینک را
بدهی (`s_xxxx`)، همان ردیف را بررسی می‌کند؛ اگر نام بدهی همهٔ ردیف‌های آن
انیمه را. خروجی برای من بفرست تا دقیقاً علت را پیدا کنم.
"""

import glob
import json
import os
import shutil
import sqlite3
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_HINTS = [os.path.join(ROOT, "uploads.db")] + sorted(
    glob.glob(os.path.join(ROOT, "*.db"))
)

print("=" * 70)
print("۱) فایل‌های دیتابیس و نسخهٔ کد")
print("=" * 70)
for path in dict.fromkeys(DB_HINTS):
    if not os.path.exists(path):
        continue
    size = os.path.getsize(path)
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        uploads = conn.execute("SELECT COUNT(*) FROM uploads").fetchone()[0]
        try:
            links = conn.execute("SELECT COUNT(*) FROM group_links").fetchone()[0]
        except sqlite3.Error:
            links = "جدول نیست"
        conn.close()
        print(f"  {path}  ({size/1024/1024:.1f} MB)  uploads={uploads}  group_links={links}")
    except sqlite3.Error as err:
        print(f"  {path}  خطا: {err}")

version_file = os.path.join(ROOT, "bot", "constants.py")
if os.path.exists(version_file):
    for line in open(version_file, encoding="utf-8"):
        if line.startswith("BOT_VERSION"):
            print("  نسخهٔ کد روی سرور:", line.strip())

print()
print("=" * 70)
print("۲) کوئری بخشنده (همان چیزی که نسخهٔ 1.6.1 استفاده می‌کند)")
print("=" * 70)

DB = os.path.join(ROOT, "uploads.db")
if not os.path.exists(DB):
    print("  ! uploads.db پیدا نشد")
    sys.exit(1)

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

try:
    rows = conn.execute("SELECT * FROM group_links").fetchall()
except sqlite3.Error as err:
    print(f"  ! جدول group_links نیست ({err}) ⇒ نسخهٔ کد قدیمی است")
    sys.exit(1)

needle = (sys.argv[1] if len(sys.argv) > 1 else "").strip()

if needle.startswith("s_"):
    targets = [r for r in rows if r["share_code"] == needle]
elif needle:
    targets = [r for r in rows if needle.lower() in (r["anime_name"] or "").lower()]
else:
    targets = rows

if not targets:
    print(f"  ! ردیفی برای {needle!r} پیدا نشد (از {len(rows)} ردیف)")
    print("  نمونه‌ها:", [r["share_code"] for r in rows[:5]])
    sys.exit(0)

for row in targets[:20]:
    name = row["anime_name"]
    season = row["season_num"] or ""
    part = row["part_num"] or ""
    print(f"\n  ── {row['share_code']} | {name!r} season={season!r} part={part!r} "
          f"type={row['anime_type']!r} status={row['status']}")

    # (الف) کوئری سختِ نسخهٔ 1.6.0
    strict = conn.execute(
        "SELECT COUNT(*) FROM uploads WHERE anime_name=? "
        "AND COALESCE(season_num,'')=? AND COALESCE(part_num,'')=? "
        "AND COALESCE(anime_type,'')=?",
        (name, season, part, row["anime_type"] or ""),
    ).fetchone()[0]
    # (ب) کوئری بخشندهٔ نسخهٔ 1.6.1
    loose = conn.execute(
        "SELECT quality, COUNT(*) n, "
        "SUM(CASE WHEN COALESCE(status,'active')='active' THEN 1 ELSE 0 END) act "
        "FROM uploads WHERE anime_name=? AND COALESCE(season_num,'')=? "
        "AND COALESCE(part_num,'')=? GROUP BY quality",
        (name, season, part),
    ).fetchall()
    print(f"     کوئری سخت (1.6.0): {strict} ردیف | کوئری بخشنده (1.6.1): "
          f"{sum(r['n'] for r in loose)} ردیف در {len(loose)} کیفیت")
    for r in loose:
        print(f"        - {r['quality']}: {r['n']} لینک (فعال {r['act']})")

    # (ج) نام‌های مشابه (تایپوی فاصله/کاراکتر)
    if not loose:
        similar = conn.execute(
            "SELECT DISTINCT anime_name FROM uploads "
            "WHERE anime_name LIKE ? LIMIT 5",
            ("%" + name.replace(" ", "%") + "%",),
        ).fetchall()
        print("     نام‌های مشابه در uploads:",
              [r["anime_name"] for r in similar] or "هیچ")

    if not loose:
        grp_rows = conn.execute(
            "SELECT COALESCE(season_num,''), COALESCE(part_num,''), COUNT(*) "
            "FROM uploads WHERE anime_name=? GROUP BY 1,2",
            (name,),
        ).fetchall()
        print(f"     گروه‌های این انیمه در uploads: "
              f"{[(r[0], r[1], r[2]) for r in grp_rows]}")
        if len(grp_rows) == 1:
            print("     ⇒ نسخهٔ 1.6.2 این را خودکار به همان گروه هدایت می‌کند")
        elif len(grp_rows) > 1:
            print("     ⇒ چند فصل/پارت دارد؛ لینک هر فصل باید جدا باشد "
                  "(نسخهٔ 1.6.2 عمداً حدس نمی‌زند)")

conn.close()
print("\n" + "=" * 70)
print("پایان — این خروجی را برای من بفرست")
print("=" * 70)
