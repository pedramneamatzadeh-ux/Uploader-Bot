"""کمکی‌های مشترک مدیریت (وضعیت، برچسب گروه، مرتب‌سازی)."""

import logging
import sqlite3
import uuid
from collections import Counter

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from ...config import config
from ...constants import (
    ALL_QUALITIES,
    MANAGE_DETAIL,
    MANAGE_EDIT,
    MANAGE_EPISODES,
    MANAGE_GROUPS,
    MANAGE_LIST,
    MANAGE_QUALITIES,
    MANAGE_SEARCH,
    UPLOAD_FIELD_MAP,
    Msg,
)
from ...database import db
from ...decorators import admin_only
from ...keyboards import (
    ib,
    build_add_quality_keyboard,
    build_pagination_row,
    build_quality_edit_keyboard,
    main_menu_for,
)
from ...utils import (
    build_download_link,
    fmt_tehran,
    get_database_name,
    go_to_main_menu,
    normalize_optional_text,
    parse_range,
    safe_edit_or_send,
    total_pages,
    validate_anime_name,
    validate_channel_input,
    validate_episode_input,
)

logger = logging.getLogger(__name__)

SORT_MODES = ["alpha", "new", "old", "count"]

SORT_LABELS = {
    "alpha": "الفبایی",
    "new": "جدیدترین",
    "old": "قدیمی‌ترین",
    "count": "تعداد لینک",
}

QUALITY_ORDER = {
    quality: idx for idx, quality in enumerate(ALL_QUALITIES)
}


# مرتب‌سازی سطح اول (دکمه چرخه‌ای — مرحله ۴ / R5)
def _manage(context: ContextTypes.DEFAULT_TYPE) -> dict:
    """dict وضعیت مدیریت را با مقادیر پیش‌فرض برمی‌گرداند."""
    manage = context.user_data.get("manage")
    if not isinstance(manage, dict):
        manage = {}
        context.user_data["manage"] = manage

    manage.setdefault("page", 0)
    manage.setdefault("mode", "list")
    manage.setdefault("search_term", None)
    manage.setdefault("sort", "alpha")
    manage.setdefault("level", 1)
    return manage


def _group_label(season: str, part: str, is_cinema: bool) -> str:
    season = season or ""
    part = part or ""

    if is_cinema:
        base = f"Movie {season}" if season else "Movie ?"
    elif season:
        base = f"Season {season}"
    else:
        base = "بدون فصل"

    if part:
        base += f" | Part {part}"

    return base


def _episode_sort_key(item: dict) -> tuple:
    rng = parse_range(item.get("episode_range") or "")
    if rng is None:
        return (1, 0, 0)
    return (0, rng[0], rng[1])


def _append_name_buttons(keyboard, manage) -> None:
    # مرحله ۵د: دکمه‌های مدیریت اسم بعد از انتخاب فصل/فیلم/قسمت
    # — هر دو در یک ردیف (تصمیم کاربر)؛ دکمهٔ جداسازی حذف شد.
    keyboard.append(
        [
            ib(
                "✏️ تغییر اسم ظاهری", callback_data="rename_display"
            ),
            ib(
                "🔁 تغییر اسم واقعی", callback_data="rename_physical"
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
def _level_state(manage: dict) -> int:
    """state متناظر با سطح فعلی مدیریت."""
    level = manage.get("level", 1)
    if level == 4:
        return MANAGE_QUALITIES
    if level == 3:
        return MANAGE_EPISODES
    if level == 2:
        return MANAGE_GROUPS
    return MANAGE_LIST
