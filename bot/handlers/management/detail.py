"""سطح ۵: جزئیات لینک و ویرایش."""

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

from .common import _manage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# سطح ۵: جزئیات لینک (برچسب‌های R7: وضعیت پخش / دسترسی لینک)
# ---------------------------------------------------------------------------
async def show_link_detail(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    session_id: str,
) -> None:
    link = db.get_upload_by_id(session_id)
    if not link:
        await context.bot.send_message(chat_id, Msg.LINK_NOT_FOUND)
        return

    download_link = await build_download_link(context, session_id)
    access_text = (
        "فعال ✅" if link["status"] == "active" else "غیرفعال 🔴"
    )

    # R7: نمایش «اتمام پخش» اگر دکمه اتمام خورده باشد؛ وگرنه مقدار پایه
    if link.get("is_finished"):
        airing_text = "اتمام پخش"
    elif link.get("airing_status"):
        airing_text = link["airing_status"]
    else:
        airing_text = "نامشخص"

    is_cinema = link.get("anime_type") == "سینمایی"
    anime_type_label = link.get("anime_type") or "نامشخص"
    db_name = get_database_name(link.get("channel_chat_id"))

    lines = [
        "📋 جزئیات لینک:",
        "",
        f"⏳ وضعیت پخش: {airing_text}",
        f"🔗 دسترسی لینک: {access_text}",
    ]

    if link.get("is_ongoing"):
        lines.append("📺 عضو بخش انیمه‌های درحال پخش")

    lines.append(
        f"🎭 نوع انیمه: {'سینمایی' if is_cinema else anime_type_label}"
    )
    lines.append(f"🗄️ دیتابیس: {db_name}")
    physical_name = link["anime_name"]
    # R12: نام ظاهری مؤثر برای همین فصل/پارت (پیش‌فرض = نام واقعی)
    display_name = db.get_display_for(
        physical_name,
        link.get("season_num"),
        link.get("part_num"),
    )
    lines.append(f"📛 نام واقعی: {physical_name}")
    lines.append(f"🎭 نام ظاهری: {display_name}")

    if is_cinema:
        lines.append(
            f"🎞️ سینمایی شماره: {link.get('season_num') or 'نامشخص'}"
        )
    else:
        lines.append(f"🎞️ فصل: {link.get('season_num') or 'نامشخص'}")
        lines.append(f"📦 پارت: {link.get('part_num') or 'ندارد'}")
        lines.append(f"📺 قسمت‌ها: {link['episode_range']}")

    lines.extend(
        [
            f"📹 کیفیت: {link['quality']}",
            f"🔢 محدوده پیام: {link['channel_msg_range']}",
            f"👤 ایجاد کننده: {link['admin_id']}",
            f"📅 تاریخ ایجاد: {fmt_tehran(link['created_at'])}",
            "",
            "🔗 لینک:",
            f"<code>{download_link}</code>",
        ]
    )

    text = "\n".join(lines)

    toggle_label = (
        "🚫 غیرفعال کن" if link["status"] == "active" else "✅ فعال کن"
    )

    if is_cinema:
        keyboard = [
            [
                ib(
                    "✏️ ویرایش نام", callback_data=f"edit:name:{session_id}"),
                ib(
                    "🎬 ویرایش شماره سینمایی",
                    callback_data=f"edit:season:{session_id}",
                ),
            ],
            [
                ib(
                    "🎭 ویرایش نام ظاهری (همین فصل)",
                    callback_data=f"edit:alias:{session_id}",
                )
            ],
            [
                ib(
                    "📹 ویرایش کیفیت", callback_data=f"edit:quality:{session_id}"),
                ib(
                    "🔢 ویرایش محدوده", callback_data=f"edit:channel:{session_id}"),
            ],
            [
                ib(
                    toggle_label, callback_data=f"toggle:{session_id}"),
                ib(
                    "🗑️ حذف", callback_data=f"delete:{session_id}"),
            ],
            [
                ib("📋 بازگشت به لیست",
                                     callback_data="back_to_list"),
                ib(
                    "🏠 منوی اصلی", callback_data="back_to_main"),
            ],
        ]
    else:
        keyboard = [
            [
                ib(
                    "✏️ ویرایش نام", callback_data=f"edit:name:{session_id}"),
                ib(
                    "🔢 ویرایش فصل", callback_data=f"edit:season:{session_id}"),
            ],
            [
                ib(
                    "🎭 ویرایش نام ظاهری (همین فصل)",
                    callback_data=f"edit:alias:{session_id}",
                )
            ],
            [
                ib(
                    "📦 ویرایش پارت", callback_data=f"edit:part:{session_id}"),
                ib(
                    "📺 ویرایش قسمت‌ها", callback_data=f"edit:episode:{session_id}"),
            ],
            [
                ib(
                    "📹 ویرایش کیفیت", callback_data=f"edit:quality:{session_id}"),
                ib(
                    "🔢 ویرایش محدوده", callback_data=f"edit:channel:{session_id}"),
            ],
            [
                ib(
                    toggle_label, callback_data=f"toggle:{session_id}"),
                ib(
                    "🗑️ حذف", callback_data=f"delete:{session_id}"),
            ],
            [
                ib("📋 بازگشت به لیست",
                                     callback_data="back_to_list"),
                ib(
                    "🏠 منوی اصلی", callback_data="back_to_main"),
            ],
        ]

    manage = _manage(context)
    msg_id = manage.get("detail_message_id")
    new_id = await safe_edit_or_send(
        context,
        chat_id,
        text,
        InlineKeyboardMarkup(keyboard),
        msg_id,
        parse_mode="HTML",
    )
    manage["detail_message_id"] = new_id
    manage["current_session"] = session_id
    context.user_data["manage"] = manage
