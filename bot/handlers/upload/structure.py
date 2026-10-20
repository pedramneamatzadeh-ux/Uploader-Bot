"""شماره فیلم/فصل/پارت/بازه قسمت."""

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
from .common import CANCEL_TEXT, EPISODE_QUESTION_TEXT, MULTISELECT_PROMPT, _SEASON_TEXT_PATTERN, _part_question_text

logger = logging.getLogger(__name__)


# ============================================================================
# شماره فیلم سینمایی
# ============================================================================
@admin_only
async def movie_num_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    if not query or not query.data:
        return MOVIE_NUM

    await query.answer()
    num = query.data.split(":", 1)[1]
    if not num.isdigit():
        return MOVIE_NUM

    context.user_data["season_num"] = num
    context.user_data["part_num"] = ""
    context.user_data["episode_range"] = "1"

    await query.edit_message_text(
        f"✅ سینمایی شماره: {num}",
    )
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text=MULTISELECT_PROMPT,
        reply_markup=quality_multiselect_keyboard([]),
    )
    return MULTI_QUALITY


@admin_only
async def receive_movie_num(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    if not update.message or not update.message.text:
        return MOVIE_NUM

    text = update.message.text.strip()
    if text == CANCEL_TEXT:
        return await cancel_upload(update, context)

    text = normalize_digits(text)
    if not text.isdigit() or int(text) <= 0:
        await update.message.reply_text(
            "❌ فقط عدد وارد کن. مثال: 1",
            reply_markup=CANCEL_MENU,
        )
        return MOVIE_NUM

    context.user_data["season_num"] = text
    context.user_data["part_num"] = ""
    context.user_data["episode_range"] = "1"

    await update.message.reply_text(
        MULTISELECT_PROMPT,
        reply_markup=quality_multiselect_keyboard([]),
    )
    return MULTI_QUALITY


# ============================================================================
# فصل (دکمه ۱ تا ۴ + «سایر»)
# ============================================================================
@admin_only
async def season_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    if not query or not query.data:
        return SEASON_NUM

    await query.answer()

    if query.data == "sn:other":
        await query.edit_message_text(
            "📝 نوع فصل را تایپ کن (مثلاً OVA یا ONA یا Special):"
        )
        return SEASON_NUM

    num = query.data.split(":", 1)[1]
    context.user_data["season_num"] = num

    await query.edit_message_text(
        _part_question_text(num),
        reply_markup=part_keyboard(),
    )
    return PART_NUM


@admin_only
async def receive_season_num(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    if not update.message or not update.message.text:
        return SEASON_NUM

    text = update.message.text.strip()
    if text == CANCEL_TEXT:
        return await cancel_upload(update, context)

    text = normalize_digits(text)

    if not text:
        await update.message.reply_text(
            "❌ فصل نمی‌تواند خالی باشد:",
            reply_markup=season_keyboard(),
        )
        return SEASON_NUM

    if text.isdigit():
        if int(text) <= 0:
            await update.message.reply_text(
                "❌ فصل باید عددی بزرگ‌تر از صفر باشد:",
                reply_markup=season_keyboard(),
            )
            return SEASON_NUM
    elif not _SEASON_TEXT_PATTERN.match(text):
        await update.message.reply_text(
            "❌ فقط عدد (مثلاً 2) یا متن انگلیسی (مثلاً OVA) وارد کن:",
            reply_markup=season_keyboard(),
        )
        return SEASON_NUM

    context.user_data["season_num"] = text

    await update.message.reply_text(
        _part_question_text(text),
        reply_markup=part_keyboard(),
    )
    return PART_NUM


# ============================================================================
# پارت (دکمه ۱ تا ۴ + «پارت ندارد»)
# ============================================================================
@admin_only
async def part_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    if not query or not query.data:
        return PART_NUM

    await query.answer()

    if query.data == "pn:none":
        context.user_data["part_num"] = ""
        display = "ندارد"
    else:
        num = query.data.split(":", 1)[1]
        context.user_data["part_num"] = num
        display = num

    await query.edit_message_text(
        f"✅ پارت: {display}\n\n{EPISODE_QUESTION_TEXT}"
    )
    return EPISODE_RANGE


@admin_only
async def receive_part_num(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    if not update.message or not update.message.text:
        return PART_NUM

    text = update.message.text.strip()
    if text == CANCEL_TEXT:
        return await cancel_upload(update, context)

    text = normalize_digits(text)
    cleaned = normalize_optional_text(text)

    if cleaned == "":
        context.user_data["part_num"] = ""
        display = "ندارد"
    elif cleaned.isdigit() and int(cleaned) > 0:
        context.user_data["part_num"] = cleaned
        display = cleaned
    else:
        await update.message.reply_text(
            "❌ فقط عدد (مثلاً 1) یا «ندارد» وارد کن:",
            reply_markup=CANCEL_MENU,
        )
        return PART_NUM

    await update.message.reply_text(
        f"✅ پارت: {display}\n\n{EPISODE_QUESTION_TEXT}",
        reply_markup=CANCEL_MENU,
    )
    return EPISODE_RANGE


# ============================================================================
# محدوده قسمت‌ها (نرمال‌سازی ارقام فارسی → انگلیسی)
# ============================================================================
@admin_only
async def receive_episode_range(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    if not update.message or not update.message.text:
        return EPISODE_RANGE

    text = update.message.text.strip()
    if text == CANCEL_TEXT:
        return await cancel_upload(update, context)

    text = normalize_digits(text)
    valid, error = validate_episode_input(text)
    if not valid:
        await update.message.reply_text(
            f"❌ {error}\nدوباره وارد کن:",
            reply_markup=CANCEL_MENU,
        )
        return EPISODE_RANGE

    context.user_data["episode_range"] = text

    await update.message.reply_text(
        MULTISELECT_PROMPT,
        reply_markup=quality_multiselect_keyboard([]),
    )
    return MULTI_QUALITY
