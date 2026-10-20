"""منوی اصلی درحال پخش."""

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

from .manage import start_ongoing_manage
from .upload import start_ongoing_upload

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# منوی اصلی بخش درحال پخش
# ---------------------------------------------------------------------------
@admin_only
async def start_ongoing(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "📺 بخش انیمه‌های درحال پخش را انتخاب کن:",
        reply_markup=ONGOING_MENU_MARKUP,
    )
    return ONGOING_MENU


@admin_only
async def ongoing_menu_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    text = update.message.text.strip()

    if text == "آپلود قسمت جدید":
        return await start_ongoing_upload(update, context)

    if text == "مدیریت انیمه‌ها":
        return await start_ongoing_manage(update, context)

    if text == "بازگشت به منوی اصلی":
        context.user_data.clear()
        await update.message.reply_text(
            "✅ به منوی اصلی بازگشتید.",
            reply_markup=main_menu_for(update.effective_user.id),
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "لطفاً یکی از گزینه‌های منو را انتخاب کن.",
        reply_markup=ONGOING_MENU_MARKUP,
    )
    return ONGOING_MENU
