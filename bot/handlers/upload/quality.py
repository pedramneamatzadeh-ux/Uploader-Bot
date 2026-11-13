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
    MSG_IDS_HINT,
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
    UPLOAD_CANCEL_INLINE,
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
    normalize_id_list_text,
    normalize_optional_text,
    validate_anime_name,
    validate_channel_input,
    validate_episode_input,
)

from .cancel import cancel_upload
from .common import (
    CANCEL_TEXT,
    MULTISELECT_PROMPT,
    close_question_message,
    delete_answer_message,
    set_question_message,
)
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
        # R23: اول تأیید بگیر (جلوگیری از لمس اشتباهی)
        from .cancel import ask_cancel_confirm

        await query.answer()
        await ask_cancel_confirm(update, context)
        return None  # state همان MULTI_QUALITY می‌ماند

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
        sent = await context.bot.send_message(
            chat_id=query.from_user.id,
            text=(
                f"📐 محدوده پیام‌های «{selected[0]}» را وارد کن. "
                + MSG_IDS_HINT
            ),
            reply_markup=UPLOAD_CANCEL_INLINE,
        )
        register_panel_message(context, sent.message_id)
        set_question_message(context, sent.message_id)
        return MULTI_QUALITY_CHANNEL

    if data == "bluray_toggle":
        # B20: تاگل بلوری برای همهٔ لینک‌های این آپلود
        await query.answer()
        new_value = 0 if context.user_data.get("is_bluray") else 1
        context.user_data["is_bluray"] = new_value
        selected_now = list(context.user_data.get("mq_selected") or [])
        await query.edit_message_text(
            MULTISELECT_PROMPT,
            reply_markup=quality_multiselect_keyboard(
                selected_now, bluray=new_value
            ),
        )
        return MULTI_QUALITY

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
        reply_markup=quality_multiselect_keyboard(
            selected, bluray=context.user_data.get("is_bluray", 0)
        ),
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
        await update.message.reply_text(
            f"❌ {error}\nدوباره وارد کن:",
            reply_markup=UPLOAD_CANCEL_INLINE,
        )
        return MULTI_QUALITY_CHANNEL

    queue: List[str] = list(context.user_data.get("mq_queue") or [])
    if not queue:
        return MULTI_QUALITY_CHANNEL

    quality = queue.pop(0)
    context.user_data["mq_queue"] = queue
    context.user_data.setdefault("qualities", []).append(
        {
            "quality": quality,
            # R22: ذخیرهٔ یکدست متن آیدی‌ها
            "channel_msg_range": normalize_id_list_text(text),
        }
    )

    # R18: پرامپت محدودهٔ پیام بسته می‌شود («✅ ثبت شد: …» بدون دکمه)
    await close_question_message(context, update.message.chat_id, text)

    if queue:
        sent = await update.message.reply_text(
            f"📐 محدوده پیام‌های «{queue[0]}» را وارد کن. "
            + MSG_IDS_HINT,
            reply_markup=UPLOAD_CANCEL_INLINE,
        )
        register_panel_message(context, sent.message_id)
        set_question_message(context, sent.message_id)
        await delete_answer_message(context, update.message)
        return MULTI_QUALITY_CHANNEL

    await show_upload_confirm(update.message, context)
    await delete_answer_message(context, update.message)
    return CONFIRM
