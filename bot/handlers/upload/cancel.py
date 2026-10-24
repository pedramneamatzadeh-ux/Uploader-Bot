"""لغو فلوی آپلود."""

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
    normalize_digits,
    normalize_optional_text,
    validate_anime_name,
    validate_channel_input,
    validate_episode_input,
)

logger = logging.getLogger(__name__)


# ============================================================================
# لغو
# ============================================================================
async def cancel_upload(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    if update.message:
        await update.message.reply_text(
            Msg.UPLOAD_CANCELLED,
            reply_markup=main_menu_for(update.effective_user.id),
        )
    context.user_data.clear()
    return ConversationHandler.END


async def cancel_from_inline(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(Msg.UPLOAD_CANCELLED_INLINE)
        await go_to_main_menu(context, query.from_user.id)
    context.user_data.clear()
    return ConversationHandler.END
