"""انتخاب کیفیت (مالتی‌سلکت) و محدوده پیام."""

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
    ANIME_TYPE_MENU,
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

from .cancel import cancel_upload
from .common import CANCEL_TEXT, MULTISELECT_PROMPT
from .confirm import show_upload_confirm

logger = logging.getLogger(__name__)


# ============================================================================
# کیفیت‌ها: چندانتخابی + ثبت + پرسش محدوده به ترتیب انتخاب
# ============================================================================
@admin_only
async def multiselect_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    if not query or not query.data:
        return MULTI_QUALITY

    data = query.data

    if data == "mqs_cancel":
        await query.answer()
        context.user_data.clear()
        await query.edit_message_text(Msg.UPLOAD_CANCELLED_INLINE)
        await go_to_main_menu(context, query.from_user.id)
        return ConversationHandler.END

    if data == "mqs_go":
        selected: List[str] = list(context.user_data.get("mq_selected") or [])
        if not selected:
            await query.answer(
                "❌ حداقل یک کیفیت را انتخاب کن.",
                show_alert=True,
            )
            return MULTI_QUALITY

        await query.answer()
        context.user_data["mq_queue"] = list(selected)
        context.user_data["qualities"] = []

        await query.edit_message_text(
            f"✅ کیفیت‌های انتخاب‌شده: {', '.join(selected)}"
        )
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text=(
                f"📐 محدوده پیام‌های «{selected[0]}» را وارد کن. "
                "مثال: 100-110 یا 100"
            ),
            reply_markup=CANCEL_MENU,
        )
        return MULTI_QUALITY_CHANNEL

    # mqs:<index>
    await query.answer()
    try:
        idx = int(data.split(":", 1)[1])
    except ValueError:
        return MULTI_QUALITY

    if idx < 0 or idx >= len(ALL_QUALITIES):
        return MULTI_QUALITY

    quality = ALL_QUALITIES[idx]
    selected = list(context.user_data.get("mq_selected") or [])
    if quality in selected:
        selected.remove(quality)
    else:
        selected.append(quality)

    context.user_data["mq_selected"] = selected
    await query.edit_message_text(
        MULTISELECT_PROMPT,
        reply_markup=quality_multiselect_keyboard(selected),
    )
    return MULTI_QUALITY


@admin_only
async def multi_quality_channel_range(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    if not update.message or not update.message.text:
        return MULTI_QUALITY_CHANNEL

    text = update.message.text.strip()
    if text == CANCEL_TEXT:
        return await cancel_upload(update, context)

    text = normalize_digits(text)
    valid, error = validate_channel_input(text)
    if not valid:
        await update.message.reply_text(f"❌ {error}\nدوباره وارد کن:")
        return MULTI_QUALITY_CHANNEL

    queue: List[str] = list(context.user_data.get("mq_queue") or [])
    if not queue:
        return MULTI_QUALITY_CHANNEL

    quality = queue.pop(0)
    context.user_data["mq_queue"] = queue
    context.user_data.setdefault("qualities", []).append(
        {"quality": quality, "channel_msg_range": text}
    )

    if queue:
        await update.message.reply_text(
            f"📐 محدوده پیام‌های «{queue[0]}» را وارد کن. "
            "مثال: 100-110 یا 100",
            reply_markup=CANCEL_MENU,
        )
        return MULTI_QUALITY_CHANNEL

    await show_upload_confirm(update.message, context)
    return CONFIRM
