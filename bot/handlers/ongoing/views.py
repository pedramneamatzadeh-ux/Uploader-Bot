"""نمایش لیست و جزئیات انیمه‌های درحال پخش."""

import logging
import sqlite3
import uuid
from typing import Any, Optional

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from ...config import config
from ...constants import (
    ONGOING_CREATE_NAME,
    ONGOING_CREATE_PART,
    ONGOING_CREATE_SEASON,
    ONGOING_DETAIL,
    ONGOING_EDIT,
    ONGOING_FIELD_MAP,
    ONGOING_LIST,
    ONGOING_UPLOAD_CONFIRM,
    ONGOING_UPLOAD_DB_SELECT,
    ONGOING_UPLOAD_EPISODE,
    ONGOING_UPLOAD_MODE,
    ONGOING_UPLOAD_MULTI_ASK,
    ONGOING_UPLOAD_MULTI_QUALITY,
    ONGOING_UPLOAD_MULTI_RANGE,
    ONGOING_UPLOAD_SELECT,
    ONGOING_UPLOAD_SINGLE_QUALITY,
    ONGOING_UPLOAD_SINGLE_RANGE,
    Msg,
)
from ...database import db
from ...decorators import admin_only
from ...keyboards import (
    ONGOING_CANCEL_MENU,
    ONGOING_PART_MENU,
    build_pagination_row,
    ib,
    main_menu_for,
    quality_keyboard,
)
from ...utils import (
    build_download_link,
    fmt_tehran,
    get_default_channel_chat_id,
    go_to_ongoing_list,
    normalize_optional_text,
    safe_edit_or_send,
    total_pages,
    validate_channel_input,
    validate_episode_input,
)

logger = logging.getLogger(__name__)


async def show_ongoing_anime_list(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    page: int = 0,
) -> None:
    manage = context.user_data.get("ongoing_manage", {})
    items = db.get_ongoing_animes(page=page, active_only=False)
    total = db.count_ongoing_animes(active_only=False)
    pages = total_pages(total, config.PAGE_SIZE)

    if not items:
        text = "📋 لیست انیمه‌های درحال پخش:\n\nهنوز انیمه‌ای ثبت نشده است."
        keyboard = [
            [ib("➕ افزودن انیمه", "success", callback_data="og_add")],
            [ib("🏠 منوی اصلی", "danger", callback_data="og_back_menu")],
        ]
    else:
        lines = ["📋 لیست انیمه‌های درحال پخش:\n"]
        keyboard = []

        for idx, item in enumerate(items, start=1):
            icon = "🟢" if item["status"] == "active" else "🔴"
            season = item.get("season_num") or "نامشخص"
            part = item.get("part_num") or "ندارد"
            lines.append(
                f"{idx}. {icon} {item['anime_name']} | فصل {season} | پارت {part}"
            )
            short = item["anime_name"]
            if len(short) > 20:
                short = short[:17] + "..."
            keyboard.append(
                [
                    ib(f"{idx}. {short}", "primary", callback_data=f"og_view:{item['id']}")
                ]
            )

        lines.append(f"\n📄 صفحه {page + 1} از {pages} ({total} انیمه)")
        text = "\n".join(lines)

        nav = build_pagination_row(
            page,
            pages,
            f"og_page:{page - 1}",
            "og_refresh",
            f"og_page:{page + 1}",
        )
        if nav:
            keyboard.append(nav)

        keyboard.append(
            [
                ib("➕ افزودن انیمه", "success", callback_data="og_add"),
                ib("📤 آپلود قسمت", "success", callback_data="og_to_upload"),
            ]
        )
        keyboard.append(
            [ib("🏠 منوی اصلی", "danger", callback_data="og_back_menu")]
        )

    msg_id = manage.get("list_message_id")
    new_id = await safe_edit_or_send(
        context, chat_id, text, InlineKeyboardMarkup(keyboard), msg_id
    )
    manage["list_message_id"] = new_id
    manage["page"] = page
    context.user_data["ongoing_manage"] = manage


async def show_ongoing_anime_detail(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    anime_id: int,
) -> None:
    item = db.get_ongoing_anime(anime_id)
    if not item:
        await context.bot.send_message(chat_id, "❌ انیمه پیدا نشد.")
        return

    status_text = "فعال ✅" if item["status"] == "active" else "غیرفعال 🔴"
    part_display = item.get("part_num") or "ندارد"

    # R7: آیا لینک‌های (نام+فصل+پارت) همگی اتمام پخش شده‌اند؟
    triple_name = item["anime_name"]
    triple_season = item.get("season_num")
    triple_part = item.get("part_num")
    total_links = db.count_uploads_triple(
        triple_name, triple_season, triple_part
    )
    finished_links = db.count_finished_uploads(
        triple_name, triple_season, triple_part
    )
    is_finished = total_links > 0 and finished_links == total_links

    text = (
        "📋 جزئیات انیمه درحال پخش:\n\n"
        f"🎬 نام: {item['anime_name']}\n"
        f"🎞️ فصل: {item.get('season_num') or 'نامشخص'}\n"
        f"📦 پارت: {part_display}\n"
        f"📊 وضعیت: {status_text}\n"
        f"⏳ پخش لینک‌ها: {'اتمام پخش 🏁' if is_finished else 'درحال پخش'}\n"
        f"👤 ثبت‌کننده: {item['admin_id']}\n"
        f"📅 ایجاد: {fmt_tehran(item['created_at'])}\n"
        f"♻️ بروزرسانی: {fmt_tehran(item['updated_at'])}"
    )

    toggle_label = "🚫 غیرفعال کن" if item["status"] == "active" else "✅ فعال کن"

    if is_finished:
        finish_row = [
            ib("↩️ بازگشت به درحال پخش", "danger", callback_data=f"og_unfinish:{anime_id}")
        ]
    else:
        finish_row = [
            ib("🏁 اتمام پخش این انیمه", "success", callback_data=f"og_finish:{anime_id}")
        ]

    keyboard = [
        [
            ib("✏️ ویرایش نام", "success", callback_data=f"og_edit:name:{anime_id}"),
            ib("🔢 ویرایش فصل", "success", callback_data=f"og_edit:season:{anime_id}"),
        ],
        [
            ib("📦 ویرایش پارت", "success", callback_data=f"og_edit:part:{anime_id}"),
            ib("📤 آپلود قسمت", "success", callback_data=f"og_upload_for:{anime_id}"),
        ],
        [
            ib(toggle_label, "success", callback_data=f"og_toggle:{anime_id}"),
            ib("🗑️ حذف", "danger", callback_data=f"og_delete:{anime_id}"),
        ],
        finish_row,
        [
            ib("📋 بازگشت به لیست", "danger", callback_data="og_back_list"),
            ib("🏠 منوی اصلی", "danger", callback_data="og_back_menu"),
        ],
    ]

    manage = context.user_data.get("ongoing_manage", {})
    msg_id = manage.get("detail_message_id")
    new_id = await safe_edit_or_send(
        context, chat_id, text, InlineKeyboardMarkup(keyboard), msg_id
    )
    manage["detail_message_id"] = new_id
    manage["current_id"] = anime_id
    context.user_data["ongoing_manage"] = manage
