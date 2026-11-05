"""شروع آپلود + انتخاب دیتابیس."""

import logging
import re
import sqlite3
import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler
from typing import Any, List

from ...config import config
from ...constants import (
    ALL_QUALITIES,
    ANIME_NAME,
    ANIME_TYPE,
    CONFIRM,
    CUSTOM_AIRING,
    DB_SELECT,
    EPISODE_RANGE,
    MOVIE_NUM,
    MULTI_QUALITY,
    MULTI_QUALITY_CHANNEL,
    PART_NUM,
    SEASON_NUM,
    Msg,
)
from ...database import db
from ...decorators import admin_only
from ...keyboards import (
    CANCEL_MENU,
    airing_status_keyboard,
    db_select_page1_keyboard,
    db_select_page2_keyboard,
    main_menu_for,
    movie_keyboard,
    part_keyboard,
    quality_multiselect_keyboard,
    season_keyboard,
)
from ...utils import (
    build_download_link,
    get_default_channel_chat_id,
    go_to_main_menu,
    register_panel_message,
    normalize_digits,
    normalize_optional_text,
    validate_anime_name,
    validate_channel_input,
    validate_episode_input,
)

from .common import PAGE1_TEXT, PAGE2_TEXT, _ask_anime_name_for

logger = logging.getLogger(__name__)


# ============================================================================
# شروع و انتخاب دیتابیس (صفحه ۱ اصلی / صفحه ۲ سفارشی)
# ============================================================================
@admin_only
async def start_upload(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    context.user_data.clear()

    custom_databases = db.get_custom_databases()

    if update.message:
        sent = await update.message.reply_text(
            PAGE1_TEXT,
            reply_markup=db_select_page1_keyboard(
                config.DATABASES,
                bool(custom_databases),
            ),
        )
        register_panel_message(context, sent.message_id)
    return DB_SELECT


@admin_only
async def select_database(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    if not query or not query.data:
        return DB_SELECT

    await query.answer()
    data = query.data

    if data == "dbsel_cancel":
        await query.edit_message_text(Msg.UPLOAD_CANCELLED_INLINE)
        await go_to_main_menu(context, query.from_user.id)
        context.user_data.clear()
        return ConversationHandler.END

    if data == "dbsel_pg2":
        custom_databases = db.get_custom_databases()
        if not custom_databases:
            await query.answer(
                "📭 دیتابیس سفارشی وجود ندارد.",
                show_alert=True,
            )
            return DB_SELECT
        await query.edit_message_text(
            PAGE2_TEXT,
            reply_markup=db_select_page2_keyboard(custom_databases),
        )
        return DB_SELECT

    if data == "dbsel_pg1":
        await query.edit_message_text(
            PAGE1_TEXT,
            reply_markup=db_select_page1_keyboard(
                config.DATABASES,
                bool(db.get_custom_databases()),
            ),
        )
        return DB_SELECT

    if data.startswith("dbsel_c:"):
        custom_databases = db.get_custom_databases()
        try:
            idx = int(data.split(":", 1)[1])
        except ValueError:
            idx = -1

        if idx < 0 or idx >= len(custom_databases):
            await query.answer("❌ دیتابیس نامعتبر.", show_alert=True)
            return DB_SELECT

        row = custom_databases[idx]
        context.user_data["channel_chat_id"] = row["chat_id"]
        context.user_data["db_name"] = row["name"]

        await query.edit_message_text(
            f"🗄️ دیتابیس انتخاب‌شده: {row['name']}"
        )
        sent = await context.bot.send_message(
            chat_id=query.from_user.id,
            text=(
                "⏳ وضعیت پخش این انیمه چیست؟\n"
                "(برای نمایش در جزئیات لینک ذخیره می‌شود)"
            ),
            reply_markup=airing_status_keyboard(),
        )
        register_panel_message(context, sent.message_id)
        return CUSTOM_AIRING

    # دیتابیس‌های اصلی: dbsel:<idx>
    try:
        idx = int(data.split(":", 1)[1])
    except ValueError:
        idx = -1

    if idx < 0 or idx >= len(config.DATABASES):
        await query.answer("❌ دیتابیس نامعتبر.", show_alert=True)
        return DB_SELECT

    dbx = config.DATABASES[idx]
    context.user_data["channel_chat_id"] = dbx["chat_id"]
    context.user_data["db_name"] = dbx["name"]

    # نوع انیمه برای دیتابیس‌های اصلی به‌صورت خودکار تعیین می‌شود
    is_cinema = "سینمایی" in dbx["name"]
    anime_type = "سینمایی" if is_cinema else "سریالی"
    context.user_data["anime_type"] = anime_type

    await query.edit_message_text(
        f"🗄️ دیتابیس انتخاب‌شده: {dbx['name']}\n"
        f"🏷️ نوع انیمه (خودکار): {anime_type}"
    )
    await _ask_anime_name_for(update, context)
    return ANIME_NAME
