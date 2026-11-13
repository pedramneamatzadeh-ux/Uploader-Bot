"""سطح ۴: کیفیت‌ها."""

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

from .common import QUALITY_ORDER, _append_name_buttons, _group_label, _manage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# سطح ۴: کیفیت‌های همان قسمت (سینمایی: همه کیفیت‌های آن شماره)
# ---------------------------------------------------------------------------
async def show_quality_list(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    manage = _manage(context)
    name = manage.get("display_name") or manage.get("name") or ""
    season = manage.get("season") or ""
    part = manage.get("part") or ""
    episode = manage.get("episode")
    is_cinema = bool(manage.get("is_cinema"))

    rows = list(manage.get("l4") or [])
    rows.sort(
        key=lambda row: QUALITY_ORDER.get(row.get("quality"), 99)
    )
    manage["l4"] = rows
    manage["level"] = 4

    head_parts = [name]
    group_title = _group_label(season, part, is_cinema)
    head_parts.append(group_title)
    if episode:
        head_parts.append(f"قسمت {episode}")

    title = "📹 " + " | ".join(head_parts) + " — کیفیت‌ها:\n\n"

    keyboard = []

    if not rows:
        text = title + "لینکی یافت نشد. 😕"
    else:
        quality_counts = Counter(
            row.get("quality") for row in rows
        )
        episode_set = {
            row.get("episode_range") or "" for row in rows
        }

        lines = []
        for idx, row in enumerate(rows):
            icon = "🟢" if row.get("status") == "active" else "🔴"
            label = row.get("quality") or "نامشخص"

            if quality_counts[row.get("quality")] > 1:
                label += f" | {row.get('channel_msg_range')}"

            if not episode and len(episode_set) > 1:
                row_episode = row.get("episode_range") or ""
                if row_episode:
                    label += f" | قسمت {row_episode}"

            lines.append(f"{idx + 1}. {icon} {label}")
            keyboard.append(
                [
                    ib(
                        f"{icon} {label}",
                        callback_data=f"m4:{idx}",
                        style="primary",
                    )
                ]
            )

        text = title + "\n".join(lines)

    # R23: ترتیب دکمه‌های صفحهٔ کیفیت‌های سینمایی (درخواست کاربر):
    # اسم ظاهری/واقعی ← افزودن کیفیت جدید ← خلاصه داستان ← بلوری ← اسم‌ها
    if is_cinema:
        _append_name_buttons(keyboard, manage)

    if rows:
        # P17 — «افزودن کیفیت جدید» از صفحه‌ی جزئیات به اینجا منتقل شد:
        # مرجع = اولین لینک همین لیست (نام/فصل/پارت/قسمت از آن کپی
        # می‌شود و فقط کیفیت و محدوده پرسیده می‌شود).
        keyboard.append(
            [
                ib(
                    "➕ افزودن کیفیت جدید",
                    callback_data=f"add_quality:{rows[0]['session_id']}",
                    style="success",
                )
            ]
        )

    if is_cinema:
        # R10: خلاصه داستان (سینمایی: صفحه کیفیت‌ها، چون صفحه قسمت ندارد)
        keyboard.append(
            [
                ib(
                    "📝 خلاصه داستان فصل",
                    callback_data="mg_sum",
                )
            ]
        )

    # B22: تاگل بلوری — دامنه فقط اپیزود انتخاب‌شده (سینمایی: کل فیلم)
    _bluray_on = db.get_group_bluray(
        manage.get("name") or "",
        manage.get("season") or "",
        manage.get("part") or "",
        episode_range=manage.get("episode"),
    )
    keyboard.append(
        [
            ib(
                (
                    "🖨 بلوری: ✅ هست"
                    if _bluray_on
                    else "🖨 بلوری: ❌ نیست"
                ),
                callback_data="mg_bluray_ep",
                style="primary",
            )
        ]
    )

    if is_cinema:
        # R16: اسم‌های جستجوی اضافی — فقط همین سینمایی (سینمایی
        # صفحهٔ قسمت ندارد؛ صفحهٔ کیفیت‌ها میزبان دامنهٔ گروه است)
        keyboard.append(
            [
                ib(
                    "📛 اسم‌های این سینمایی",
                    callback_data="mg_extra:group",
                    style="primary",
                )
            ]
        )

    keyboard.append(
        [
            ib("◀️ بازگشت", callback_data="mg_back"),
            ib(
                "🏠 منوی اصلی", callback_data="back_to_main"
            ),
        ]
    )

    markup = InlineKeyboardMarkup(keyboard)
    msg_id = manage.get("list_message_id")
    new_id = await safe_edit_or_send(context, chat_id, text, markup, msg_id)
    manage["list_message_id"] = new_id
    context.user_data["manage"] = manage
