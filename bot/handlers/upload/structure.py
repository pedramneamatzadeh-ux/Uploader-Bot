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
    UPLOAD_CANCEL_INLINE,
    airing_status_keyboard,
    db_select_page1_keyboard,
    db_select_page2_keyboard,
    main_menu_for,
    movie_keyboard,
    part_keyboard,
    quality_multiselect_keyboard,
    season_keyboard,
    season_other_keyboard,
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

from .cancel import cancel_upload
from .common import (
    CANCEL_TEXT,
    EPISODE_QUESTION_TEXT,
    MULTISELECT_PROMPT,
    _SEASON_TEXT_PATTERN,
    _part_question_text,
    clear_question_message,
    close_question_message,
    delete_answer_message,
    is_other_season,
    set_question_message,
)

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
    value = query.data.split(":", 1)[1]
    if value == "none":
        # R19: سینمایی بدون شماره — season_num خالی (مثل pn:none در پارت)
        num = ""
        display = "ندارد"
    elif value.isdigit():
        num = value
        display = value
    else:
        return MOVIE_NUM

    context.user_data["season_num"] = num
    context.user_data["part_num"] = ""
    context.user_data["episode_range"] = "1"

    await query.edit_message_text(
        f"✅ سینمایی شماره: {display}",
    )
    # R18: سؤال سینمایی با دکمه جواب داده شد — پیام خودش ادیت شد و
    # سؤال تایپیِ در انتظاری باقی نمانده.
    clear_question_message(context)
    sent = await context.bot.send_message(
        chat_id=query.from_user.id,
        text=MULTISELECT_PROMPT,
        reply_markup=quality_multiselect_keyboard(
            [], bluray=context.user_data.get("is_bluray", 0)
        ),
    )
    register_panel_message(context, sent.message_id)
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
    cleaned = normalize_optional_text(text)

    # R19: «ندارد» (و هم‌معنی‌هایش) ⇒ سینمایی بدون شماره — مثل پارت
    if cleaned == "":
        num = ""
        display = "ندارد"
    elif cleaned.isdigit() and int(cleaned) > 0:
        num = cleaned
        display = cleaned
    else:
        await update.message.reply_text(
            "❌ فقط عدد (مثلاً 1) یا «ندارد» وارد کن:",
            reply_markup=UPLOAD_CANCEL_INLINE,
        )
        return MOVIE_NUM

    context.user_data["season_num"] = num
    context.user_data["part_num"] = ""
    context.user_data["episode_range"] = "1"

    # R18: سؤال «سینمایی چندم» بسته + پیام جواب پاک می‌شود
    await close_question_message(context, update.message.chat_id, display)
    sent = await update.message.reply_text(
        MULTISELECT_PROMPT,
        reply_markup=quality_multiselect_keyboard(
            [], bluray=context.user_data.get("is_bluray", 0)
        ),
    )
    register_panel_message(context, sent.message_id)
    await delete_answer_message(context, update.message)
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
        # R17: زیرصفحهٔ «سایر» — دکمه‌های OVA/ONA/Special + تایپ دستی
        await query.edit_message_text(
            "📝 سایر — یکی از دکمه‌ها را بزن یا تایپ کن "
            "(مثلاً OVA یا ONA یا Special):",
            reply_markup=season_other_keyboard(),
        )
        # R18: همان پیام همچنان سؤال تایپیِ در انتظار است
        set_question_message(context, query.message.message_id)
        return SEASON_NUM

    if query.data.startswith("sn_other:"):
        # R17: انتخاب OVA/ONA/Special ⇒ سؤال بعدی «شماره» است نه «پارت»
        value = query.data.split(":", 1)[1]
        context.user_data["season_num"] = value
        await query.edit_message_text(
            _part_question_text(value, is_other=True),
            reply_markup=part_keyboard(other=True),
        )
        # R18: پیام (ادیت‌شده) اکنون سؤال تایپیِ پارت/شماره است
        set_question_message(context, query.message.message_id)
        return PART_NUM

    num = query.data.split(":", 1)[1]
    context.user_data["season_num"] = num

    await query.edit_message_text(
        _part_question_text(num),
        reply_markup=part_keyboard(),
    )
    # R18: پیام (ادیت‌شده) اکنون سؤال تایپیِ پارت است
    set_question_message(context, query.message.message_id)
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

    # R18: سؤال فصل بسته می‌شود («✅ ثبت شد: …» بدون دکمه)
    await close_question_message(context, update.message.chat_id, text)

    # R17: فصل‌های «سایر» (OVA/ONA/Special) ⇒ «شماره چند هست؟»
    other = is_other_season(text)
    sent = await update.message.reply_text(
        _part_question_text(text, is_other=other),
        reply_markup=part_keyboard(other=other),
    )
    register_panel_message(context, sent.message_id)
    set_question_message(context, sent.message_id)
    await delete_answer_message(context, update.message)
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

    # R17: برچسب «شماره» برای سایر‌فصل‌ها + لغو اینلاین زیر سؤال قسمت
    label = (
        "شماره"
        if is_other_season(context.user_data.get("season_num"))
        else "پارت"
    )
    await query.edit_message_text(
        f"✅ {label}: {display}\n\n{EPISODE_QUESTION_TEXT}",
        reply_markup=UPLOAD_CANCEL_INLINE,
    )
    # R18: پیام (ادیت‌شده) اکنون سؤال تایپیِ محدودهٔ قسمت‌ها است
    set_question_message(context, query.message.message_id)
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
            reply_markup=UPLOAD_CANCEL_INLINE,
        )
        return PART_NUM

    label = (
        "شماره"
        if is_other_season(context.user_data.get("season_num"))
        else "پارت"
    )
    # R18: سؤال پارت/شماره بسته می‌شود («✅ ثبت شد: …» بدون دکمه)
    await close_question_message(context, update.message.chat_id, display)
    sent = await update.message.reply_text(
        f"✅ {label}: {display}\n\n{EPISODE_QUESTION_TEXT}",
        reply_markup=UPLOAD_CANCEL_INLINE,
    )
    register_panel_message(context, sent.message_id)
    set_question_message(context, sent.message_id)
    await delete_answer_message(context, update.message)
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
            reply_markup=UPLOAD_CANCEL_INLINE,
        )
        return EPISODE_RANGE

    context.user_data["episode_range"] = text

    # R18: سؤال محدودهٔ قسمت‌ها بسته + پیام جواب پاک می‌شود
    await close_question_message(context, update.message.chat_id, text)
    sent = await update.message.reply_text(
        MULTISELECT_PROMPT,
        reply_markup=quality_multiselect_keyboard(
            [], bluray=context.user_data.get("is_bluray", 0)
        ),
    )
    register_panel_message(context, sent.message_id)
    await delete_answer_message(context, update.message)
    return MULTI_QUALITY
