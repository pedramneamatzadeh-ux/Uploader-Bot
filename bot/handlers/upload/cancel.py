"""لغو فلوی آپلود."""

import logging
import re
import sqlite3
import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
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


# ============================================================================
# R23: تأیید لغو — دکمه‌های «لغو» فلؤ آپلود اول می‌پرسند
# (جلوگیری از لمس اشتباهی). «نه» فقط پیام تأیید را می‌بندد و state
# گفتگو دست‌نخورده می‌ماند.
# ============================================================================
CANCEL_CONFIRM_TEXT = "❗️ مطمئنی می‌خواهی آپلود را لغو کنی؟"


async def ask_cancel_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """پیام تأیید جداگانه می‌فرستد؛ پرامپت قبلی دست‌نخورده می‌ماند."""
    from ...keyboards import CANCEL_CONFIRM_INLINE

    query = update.callback_query
    chat_id = (
        query.message.chat_id if query and query.message
        else getattr(update.effective_user, "id", None)
    )
    if chat_id is None:
        return
    try:
        sent = await context.bot.send_message(
            chat_id=chat_id,
            text=CANCEL_CONFIRM_TEXT,
            reply_markup=CANCEL_CONFIRM_INLINE,
        )
        context.user_data["cancel_confirm_mid"] = getattr(
            sent, "message_id", None
        )
    except TelegramError:
        logger.debug("ارسال پیام تأیید لغو ناموفق بود", exc_info=True)


async def confirm_cancel_yes(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """تأیید لغو: پیام تأیید به «لغو شد» تبدیل و منوی اصلی برمی‌گردد."""
    query = update.callback_query
    await query.answer()
    try:
        await query.edit_message_text(Msg.UPLOAD_CANCELLED_INLINE)
    except TelegramError:
        pass
    context.user_data.pop("cancel_confirm_mid", None)
    if query.from_user:
        await go_to_main_menu(context, query.from_user.id)
    context.user_data.clear()
    return ConversationHandler.END


async def confirm_cancel_no(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """انصراف از لغو: فقط پیام تأیید پاک می‌شود (بازگشت None = state
    همان می‌ماند)."""
    query = update.callback_query
    await query.answer("👍 آپلود ادامه دارد.")
    if query.message:
        try:
            await context.bot.delete_message(
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
            )
        except TelegramError:
            pass
    context.user_data.pop("cancel_confirm_mid", None)
    return None


async def cancel_from_inline(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """R23: دکمه‌های لغوی اینلاین دیگر یک‌ضربه لغو نمی‌کنند — اول
    تأیید می‌گیرند (state گفتگو حفظ می‌شود)."""
    query = update.callback_query
    if query:
        await query.answer()
        await ask_cancel_confirm(update, context)
    return None
