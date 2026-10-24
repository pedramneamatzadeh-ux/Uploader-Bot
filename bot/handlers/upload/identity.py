"""وضعیت پخش، نوع انیمه و نام."""

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
    anime_type_keyboard,
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
    normalize_digits,
    normalize_optional_text,
    validate_anime_name,
    validate_channel_input,
    validate_episode_input,
)

from .cancel import cancel_upload
from .common import CANCEL_TEXT, _send_movie_question, _send_season_question

logger = logging.getLogger(__name__)


# ============================================================================
# وضعیت پخش (دیتابیس‌های سفارشی — بخشی از R7)
# ============================================================================
@admin_only
async def receive_airing_status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    if not query or not query.data:
        return CUSTOM_AIRING

    if query.data == "airing:ongoing":
        value = "درحال پخش"
    elif query.data == "airing:finished":
        value = "اتمام پخش"
    else:
        return CUSTOM_AIRING

    await query.answer()
    context.user_data["airing_status"] = value

    await query.edit_message_text(f"✅ وضعیت پخش: {value}")
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text="این انیمه سینمایی است یا سریالی؟",
        reply_markup=anime_type_keyboard(),
    )
    return ANIME_TYPE


# ============================================================================
# نوع انیمه / نام انیمه
# ============================================================================
@admin_only
async def receive_anime_type(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    if not update.message or not update.message.text:
        return ANIME_TYPE

    text = update.message.text.strip()
    if text == CANCEL_TEXT:
        return await cancel_upload(update, context)

    if text == "🎬 سینمایی":
        context.user_data["anime_type"] = "سینمایی"
    elif text == "📺 سریالی":
        context.user_data["anime_type"] = "سریالی"
    else:
        await update.message.reply_text(
            "❌ لطفاً یکی از گزینه‌ها را انتخاب کن:",
            reply_markup=anime_type_keyboard(),
        )
        return ANIME_TYPE

    await update.message.reply_text(
        f"✅ نوع: {text}\n\nاسم انیمه را وارد کن: (فقط حروف انگلیسی)",
        reply_markup=CANCEL_MENU,
    )
    return ANIME_NAME


@admin_only
async def receive_anime_type_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """B11: انتخاب نوع انیمه با دکمهٔ inline (uptype:*).

    هندلر متنی receive_anime_type هم برای کیبوردهای قدیمیِ باقی‌مانده
    در state می‌ماند.
    """
    query = update.callback_query
    if not query or not query.data:
        return ANIME_TYPE

    data = query.data

    if data == "uptype:cancel":
        await query.answer()
        await query.edit_message_text(Msg.UPLOAD_CANCELLED_INLINE)
        await go_to_main_menu(context, query.from_user.id)
        context.user_data.clear()
        return ConversationHandler.END

    if data == "uptype:movie":
        value = "سینمایی"
    elif data == "uptype:series":
        value = "سریالی"
    else:
        return ANIME_TYPE

    await query.answer()
    context.user_data["anime_type"] = value

    await query.edit_message_text(f"✅ نوع: {value}")
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text="اسم انیمه را وارد کن: (فقط حروف انگلیسی)",
        reply_markup=CANCEL_MENU,
    )
    return ANIME_NAME


@admin_only
async def receive_anime_name(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    if not update.message or not update.message.text:
        return ANIME_NAME

    text = update.message.text.strip()
    if text == CANCEL_TEXT:
        return await cancel_upload(update, context)

    valid, error = validate_anime_name(text)
    if not valid:
        await update.message.reply_text(
            f"❌ {error}",
            reply_markup=CANCEL_MENU,
        )
        return ANIME_NAME

    context.user_data["anime_name"] = text

    if context.user_data.get("anime_type") == "سینمایی":
        await _send_movie_question(update.message)
        return MOVIE_NUM

    await _send_season_question(update.message)
    return SEASON_NUM
