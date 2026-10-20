"""مدیریت انیمه‌های درحال پخش."""

import logging
import sqlite3
import uuid
from typing import Any, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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
    ONGOING_MENU,
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
    ONGOING_MENU_MARKUP,
    ONGOING_PART_MENU,
    build_pagination_row,
    main_menu_for,
    quality_keyboard,
)
from ...utils import (
    build_download_link,
    fmt_tehran,
    get_default_channel_chat_id,
    go_to_ongoing_menu,
    normalize_optional_text,
    safe_edit_or_send,
    total_pages,
    validate_channel_input,
    validate_episode_input,
)

from .upload import prompt_ongoing_db_or_episode, show_ongoing_upload_select
from .views import show_ongoing_anime_detail, show_ongoing_anime_list

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# مدیریت انیمه‌ها
# ---------------------------------------------------------------------------
async def start_ongoing_manage(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    context.user_data["ongoing_manage"] = {"page": 0}
    await show_ongoing_anime_list(update.message.chat_id, context, 0)
    return ONGOING_LIST


@admin_only
async def handle_ongoing_manage_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id
    data = query.data
    manage = context.user_data.get("ongoing_manage", {})

    if data == "og_back_menu":
        await query.edit_message_text("✅ به منوی انیمه‌های درحال پخش برگشتید.")
        await go_to_ongoing_menu(context, chat_id)
        return ONGOING_MENU

    if data in ("og_back_list", "og_refresh"):
        await show_ongoing_anime_list(chat_id, context, manage.get("page", 0))
        return ONGOING_LIST

    if data.startswith("og_page:"):
        page = max(0, int(data.split(":", 1)[1]))
        await show_ongoing_anime_list(chat_id, context, page)
        return ONGOING_LIST

    if data == "og_add":
        context.user_data["ongoing_new"] = {}
        await query.edit_message_text("➕ نام انیمه درحال پخش را وارد کن:")
        return ONGOING_CREATE_NAME

    if data == "og_to_upload":
        await show_ongoing_upload_select(chat_id, context, 0, query.message.message_id)
        return ONGOING_UPLOAD_SELECT

    if data.startswith("og_view:"):
        anime_id = int(data.split(":", 1)[1])
        await show_ongoing_anime_detail(chat_id, context, anime_id)
        return ONGOING_DETAIL

    if data.startswith("og_edit:"):
        _, field, raw_id = data.split(":", 2)
        anime_id = int(raw_id)

        prompts = {
            "name": "✏️ نام جدید انیمه را وارد کن:",
            "season": "🔢 فصل جدید را وارد کن:",
            "part": "📦 پارت جدید را وارد کن:\n(اگر ندارد دکمه «ندارد ➖» را بزن)",
        }

        context.user_data["ongoing_edit"] = {"id": anime_id, "field": field}

        if field == "part":
            kb = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "ندارد ➖",
                            callback_data=f"og_edit_part_none:{anime_id}",
                        )
                    ]
                ]
            )
            await query.edit_message_text(
                prompts["part"] + "\n\nبرای لغو، دکمه «لغو» را بزن.",
                reply_markup=kb,
            )
        else:
            await query.edit_message_text(
                prompts.get(field, "مقدار جدید را وارد کن:")
                + "\n\nبرای لغو، دکمه «لغو» را بزن.",
            )
        return ONGOING_EDIT

    if data.startswith("og_edit_part_none:"):
        anime_id = int(data.split(":", 1)[1])
        if db.update_ongoing_anime(anime_id, "part_num", ""):
            await query.answer("✅ پارت حذف شد.")
            context.user_data.pop("ongoing_edit", None)
            await show_ongoing_anime_detail(chat_id, context, anime_id)
        else:
            await query.answer("❌ خطا در ذخیره.")
        return ONGOING_DETAIL

    if data.startswith("og_toggle:"):
        anime_id = int(data.split(":", 1)[1])
        if db.toggle_ongoing_status(anime_id):
            await query.answer("✅ وضعیت تغییر کرد.")
        else:
            await query.answer("❌ خطا در تغییر وضعیت.")
        await show_ongoing_anime_detail(chat_id, context, anime_id)
        return ONGOING_DETAIL

    # --- R7: اتمام پخش انیمه (برگشت‌پذیر) ---
    if data.startswith("og_finish_yes:"):
        anime_id = int(data.split(":", 1)[1])
        item = db.get_ongoing_anime(anime_id)
        if not item:
            await query.answer("❌ انیمه پیدا نشد.")
            return ONGOING_LIST

        changed = db.set_finished_for_triple(
            item["anime_name"],
            item.get("season_num"),
            item.get("part_num"),
            finished=True,
        )
        db.set_ongoing_airing(anime_id, active=False)
        await query.answer(
            f"✅ {changed} لینک به «اتمام پخش» تغییر کرد؛ "
            "انیمه از لیست آپلود قسمت جدید خارج شد.",
        )
        await show_ongoing_anime_detail(chat_id, context, anime_id)
        return ONGOING_DETAIL

    if data.startswith("og_unfinish_yes:"):
        anime_id = int(data.split(":", 1)[1])
        item = db.get_ongoing_anime(anime_id)
        if not item:
            await query.answer("❌ انیمه پیدا نشد.")
            return ONGOING_LIST

        changed = db.set_finished_for_triple(
            item["anime_name"],
            item.get("season_num"),
            item.get("part_num"),
            finished=False,
        )
        db.set_ongoing_airing(anime_id, active=True)
        await query.answer(
            f"✅ {changed} لینک به «درحال پخش» برگشت؛ "
            "انیمه دوباره فعال شد.",
        )
        await show_ongoing_anime_detail(chat_id, context, anime_id)
        return ONGOING_DETAIL

    if data.startswith("og_unfinish:"):
        anime_id = int(data.split(":", 1)[1])
        item = db.get_ongoing_anime(anime_id)
        if not item:
            await query.answer("❌ انیمه پیدا نشد.")
            return ONGOING_LIST

        await query.edit_message_text(
            "↩️ مطمئنی می‌خواهی این انیمه دوباره «درحال پخش» شود؟\n\n"
            f"🎬 {item['anime_name']}\n"
            "لینک‌های هم‌نام + هم‌فصل + هم‌پارت به حالت درحال پخش "
            "برمی‌گردند و انیمه دوباره در لیست آپلود قسمت جدید فعال می‌شود.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "✅ بله، برگردان",
                            callback_data=f"og_unfinish_yes:{anime_id}",
                        ),
                        InlineKeyboardButton(
                            "❌ انصراف",
                            callback_data=f"og_view:{anime_id}",
                        ),
                    ]
                ]
            ),
        )
        return ONGOING_DETAIL

    if data.startswith("og_finish:"):
        anime_id = int(data.split(":", 1)[1])
        item = db.get_ongoing_anime(anime_id)
        if not item:
            await query.answer("❌ انیمه پیدا نشد.")
            return ONGOING_LIST

        total = db.count_uploads_triple(
            item["anime_name"],
            item.get("season_num"),
            item.get("part_num"),
        )
        await query.edit_message_text(
            "🏁 مطمئنی این انیمه تمام پخش شد؟\n\n"
            f"🎬 {item['anime_name']}\n"
            f"🔗 {total} لینک هم‌نام + هم‌فصل + هم‌پارت به "
            "«اتمام پخش» تغییر می‌کند\n"
            "انیمه از لیست انتخاب «آپلود قسمت جدید» خارج و در لیست "
            "مدیریت 🔴 می‌شود\n\n"
            "(برگشت‌پذیر است)",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "✅ بله، اتمام پخش کن",
                            callback_data=f"og_finish_yes:{anime_id}",
                        ),
                        InlineKeyboardButton(
                            "❌ انصراف",
                            callback_data=f"og_view:{anime_id}",
                        ),
                    ]
                ]
            ),
        )
        return ONGOING_DETAIL

    if data.startswith("og_delete:"):
        anime_id = int(data.split(":", 1)[1])
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ بله، حذف کن",
                    callback_data=f"og_confirm_delete:{anime_id}",
                ),
                InlineKeyboardButton(
                    "❌ خیر", callback_data=f"og_view:{anime_id}"),
            ]
        ]
        await query.edit_message_text(
            "⚠️ مطمئنی می‌خواهی این انیمه را حذف کنی?\n"
            "لینک‌های قبلاً ساخته‌شده حذف نمی‌شوند، فقط اطلاعات پیش‌فرض حذف می‌شود.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return ONGOING_DETAIL

    if data.startswith("og_confirm_delete:"):
        anime_id = int(data.split(":", 1)[1])
        if db.delete_ongoing_anime(anime_id):
            await query.edit_message_text("✅ انیمه حذف شد.")
            manage.pop("detail_message_id", None)
            context.user_data["ongoing_manage"] = manage
            await show_ongoing_anime_list(chat_id, context, manage.get("page", 0))
            return ONGOING_LIST
        await query.answer("❌ خطا در حذف.")
        return ONGOING_DETAIL

    if data.startswith("og_upload_for:"):
        anime_id = int(data.split(":", 1)[1])
        item = db.get_ongoing_anime(anime_id)
        if not item:
            await query.answer("❌ انیمه پیدا نشد.")
            return ONGOING_DETAIL

        context.user_data["ongoing_upload"] = {
            "ongoing_anime_id": item["id"],
            "anime_name": item["anime_name"],
            "season_num": item.get("season_num"),
            "part_num": item.get("part_num"),
        }
        return await prompt_ongoing_db_or_episode(query, context)

    await query.answer(Msg.INVALID_COMMAND)
    return ONGOING_LIST
