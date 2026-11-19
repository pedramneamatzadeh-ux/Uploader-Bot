# -*- coding: utf-8 -*-
"""R40 — عیب‌یابی و تعمیر چیدمان پروژهٔ ربات (`python3 bot_fix.py`).

خطای رایج:
    ModuleNotFoundError: No module named 'bot.application'

تقریباً همیشه یعنی زیپ در **پوشهٔ اشتباه** باز شده و کد یک لایه تو رفته:
    پروژه/bot/bot/application.py     ← اشتباه
    پروژه/bot/application.py         ← درست

این اسکریپت:
  ۱) چیدمان را تشخیص می‌دهد،
  ۲) اگر کد یک لایه تو رفته باشد، خودش آن را یک پله بالا می‌آورد
     (فایل‌های `.env`، `uploads.db` و `uploads/` دست نمی‌خورند)،
  ۳) وجود فایل‌های ضروری را چک می‌کند،
  ۴) در صورت نصب بودن وابستگی‌ها، ایمپورت واقعی `bot.application` را
     امتحان می‌کند تا ایراد «ماژول نیست» یک‌بار برای همیشه تمام شود.

اجرا از ریشهٔ پروژه (همان‌جایی که `main.py` هست):
    python3 bot_fix.py
"""

import importlib
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

REQUIRED = [
    "main.py",
    "bot/__init__.py",
    "bot/application.py",
    "bot/constants.py",
    "bot/config.py",
    "bot/services/group_panel.py",
    "bot/handlers/base.py",
]


def _missing() -> list:
    return [p for p in REQUIRED if not os.path.isfile(os.path.join(ROOT, p))]


def _nested_source() -> str:
    """مسیر کدِ یک‌لایه‌توشده (اگر وجود داشته باشد)."""
    for candidate in ("bot/bot", os.path.join("bot", "bot")):
        full = os.path.join(ROOT, candidate)
        if os.path.isdir(full) and os.path.isfile(
            os.path.join(full, "application.py")
        ):
            return full
    return ""


def _move_up(src: str) -> None:
    """محتوای `bot/bot/` را داخل `bot/` ادغام می‌کند و پوشهٔ اضافه را پاک می‌کند."""
    dst = os.path.dirname(src)          # پروژه/bot
    for name in sorted(os.listdir(src)):
        s = os.path.join(src, name)
        d = os.path.join(dst, name)
        if os.path.isdir(s):
            if not os.path.isdir(d):
                os.makedirs(d)
            for child in os.listdir(s):
                sc = os.path.join(s, child)
                dc = os.path.join(d, child)
                if os.path.exists(dc):
                    if os.path.isdir(dc):
                        shutil.rmtree(dc)
                    else:
                        os.remove(dc)
                shutil.move(sc, dc)
            shutil.rmtree(s)
        else:
            if os.path.exists(d):
                if os.path.isdir(d):
                    shutil.rmtree(d)
                else:
                    os.remove(d)
            shutil.move(s, d)
    shutil.rmtree(src)


def _promote_root_files() -> list:
    """فایل‌های ریشه‌ای که اشتباهاً داخل `bot/` رفته‌اند را بالا می‌آورد.

    اگر `main.py` در ریشه نباشد ولی `bot/main.py` باشد، یعنی همه‌چیز داخل
    پوشهٔ bot باز شده؛ همان فایل‌ها یک پله بالا می‌آیند.
    """
    moved = []
    for name in ("main.py", "requirements.txt"):
        if os.path.isfile(os.path.join(ROOT, name)):
            continue
        src = os.path.join(ROOT, "bot", name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(ROOT, name))
            moved.append(name)
    return moved


def _purge_pycache() -> int:
    count = 0
    for dirpath, dirnames, _ in os.walk(os.path.join(ROOT, "bot")):
        for name in list(dirnames):
            if name == "__pycache__":
                shutil.rmtree(os.path.join(dirpath, name), ignore_errors=True)
                dirnames.remove(name)
                count += 1
    return count


def _report_version() -> str:
    path = os.path.join(ROOT, "bot", "constants.py")
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("BOT_VERSION = "):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "?"


def main() -> int:
    print("📂 پروژه:", ROOT)

    nested = _nested_source()
    if nested:
        print("🔧 چیدمان اشتباه تشخیص داده شد:", os.path.relpath(nested, ROOT))
        print("   کد یک لایه تو رفته است؛ در حال مرتب‌سازی…")
        _move_up(nested)
        removed = _purge_pycache()
        print(f"✅ مرتب شد. {removed} پوشهٔ __pycache__ پاک شد.")

    promoted = _promote_root_files()
    if promoted:
        print("🔧 این فایل‌ها از داخل پوشهٔ bot به ریشه منتقل شدند:",
              ", ".join(promoted))

    missing = _missing()
    if missing:
        print("❌ این فایل‌ها پیدا نشدند:")
        for item in missing:
            print("   -", item)
        print(
            "\nراهنما: محتوای زیپ باید در ریشهٔ پروژه باشد؛ یعنی کنار main.py\n"
            "یک پوشهٔ bot/ با application.py داخلش. اگر بعد از unzip ساختار\n"
            "پروژه/bot/bot/application.py شد، همین اسکریپت با یک بار اجرا درستش می‌کند."
        )
        return 1

    print("✅ چیدمان درست است و همهٔ فایل‌های ضروری وجود دارند.")
    print("🧩 نسخه:", _report_version())

    os.chdir(ROOT)
    sys.path.insert(0, ROOT)
    for name in [m for m in list(sys.modules) if m == "bot" or m.startswith("bot.")]:
        del sys.modules[name]

    try:
        module = importlib.import_module("bot.application")
    except ModuleNotFoundError as error:
        print("❌ ایمپورت ناموفق:", error)
        if error.name and not error.name.startswith("bot"):
            print(
                "   این خطا از کتابخانهٔ بیرونی است، نه چیدمان پروژه.\n"
                "   نصب وابستگی‌ها:  pip install -r requirements.txt"
            )
        return 1
    except Exception as error:      # noqa: BLE001 — پیام خوانا برای کاربر
        print(f"❌ ایمپورت خطا داد: {type(error).__name__}: {error}")
        return 1

    print("✅ ایمپورت bot.application موفق بود.")
    if hasattr(module, "build_application"):
        print("✅ build_application پیدا شد — حالا می‌توانی اجرا کنی: python3 main.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
