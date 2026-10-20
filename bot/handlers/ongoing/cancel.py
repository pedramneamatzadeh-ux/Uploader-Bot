"""لغو گفتگوی درحال پخش."""

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

logger = logging.getLogger(__name__)


async def handle_ongoing_text_cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> Optional[int]:
    if text == "بازگشت به منوی اصلی":
        context.user_data.clear()
        await update.message.reply_text(
            "✅ به منوی اصلی بازگشتید.",
            reply_markup=main_menu_for(update.effective_user.id),
        )
        return ConversationHandler.END

    if text == "لغو":
        context.user_data.pop("ongoing_upload", None)
        context.user_data.pop("ongoing_new", None)
        context.user_data.pop("ongoing_edit", None)
        await update.message.reply_text(
            "❌ عملیات لغو شد.",
            reply_markup=ONGOING_MENU_MARKUP,
        )
        return ONGOING_MENU

    return None


async def cancel_ongoing(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "❌ عملیات لغو شد.",
        reply_markup=ONGOING_MENU_MARKUP,
    )
    return ONGOING_MENU
