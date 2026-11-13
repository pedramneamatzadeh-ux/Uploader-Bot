"""پرسش‌ها و هلپرهای مشترک فلوی آپلود."""

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
    OTHER_SEASONS,
    ALL_QUALITIES,
    EPISODE_IDS_HINT,
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
)
from ...utils import (
    PANEL_MSG_KEY,
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

logger = logging.getLogger(__name__)

CANCEL_TEXT = "لغو آپلود"

PAGE1_TEXT = (
    "📤 فرآیند آپلود شروع شد!\n\n"
    "از کدام دیتابیس می‌خواهی استفاده کنی؟"
)

PAGE2_TEXT = (
    "🗃️ دیتابیس‌های سفارشی:\n\n"
    "یکی را برای آپلود انتخاب کن:"
)

MULTISELECT_PROMPT = (
    "📹 کیفیت‌ها را انتخاب کن (ضربه = سلکت/آنسلت؛ چندتایی مجاز) "
    "و سپس «ثبت انتخاب‌ها» را بزن:"
)

_SEASON_TEXT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .:_/()-]*$")

EPISODE_QUESTION_TEXT = (
    "قسمت یا محدودهٔ قسمت‌ها را وارد کن. " + EPISODE_IDS_HINT
)


# ============================================================================
# R18: بستن پیام سؤال پس از جواب تایپی — سؤال به «✅ ثبت شد: <جواب>»
# (بدون هیچ دکمهٔ اینلاین) ویرایش می‌شود و پیام جواب کاربر پاک می‌شود.
# سؤال‌های دکمه‌ای خودشان در لحظهٔ فشار ادیت می‌شوند (دست‌نخورده).
# ============================================================================
QUESTION_MID_KEY = "_question_mid"


def set_question_message(context: Any, message_id) -> None:
    """message_id سؤال تایپیِ فعلی را برای بستن هنگام جواب ثبت می‌کند."""
    if not message_id:
        return
    try:
        context.user_data[QUESTION_MID_KEY] = message_id
    except (AttributeError, TypeError):
        pass


def clear_question_message(context: Any) -> None:
    """سؤال تایپیِ در انتظاری وجود ندارد (مثلاً جواب دکمه‌ای داده شده)."""
    try:
        context.user_data.pop(QUESTION_MID_KEY, None)
    except (AttributeError, TypeError):
        pass


async def close_question_message(
    context: Any,
    chat_id,
    answer_display: str,
) -> None:
    """سؤال ثبت‌شده را به «✅ ثبت شد: <جواب>» بدون دکمه ویرایش می‌کند.

    mid از فهرست پنل‌های بازِ R15 هم خارج می‌شود تا panel_gate بعداً آن
    را به «پنل بسته شد» تغییر ندهد. خطای ویرایش (پیام حذف‌شده/قدیمی)
    هرگز جلوی ادامهٔ فلؤ را نمی‌گیرد.
    """
    try:
        mid = context.user_data.pop(QUESTION_MID_KEY, None)
    except (AttributeError, TypeError):
        mid = None
    if not mid:
        return
    try:
        lst = context.chat_data.get(PANEL_MSG_KEY)
        if lst and mid in lst:
            lst.remove(mid)
    except (AttributeError, TypeError):
        pass
    edit = getattr(getattr(context, "bot", None), "edit_message_text", None)
    if edit is None:
        return
    try:
        await edit(
            chat_id=chat_id,
            message_id=mid,
            text=f"✅ ثبت شد: {answer_display}",
            reply_markup=None,
        )
    except TelegramError:
        pass


async def delete_answer_message(context: Any, message: Any) -> None:
    """پیام جواب تایپی کاربر را پاک می‌کند (R18). هرگز استثنا نمی‌دهد.

    باید بعد از ارسال پیام بعدی صدا زده شود — reply به پیامِ
    حذف‌شده در Bot API خطا می‌دهد.
    """
    if not message:
        return
    dm = getattr(getattr(context, "bot", None), "delete_message", None)
    if dm is None:
        return
    try:
        await dm(chat_id=message.chat_id, message_id=message.message_id)
    except TelegramError:
        pass


# پذیرش متن انگلیسی برای «سایر» در سؤال فصل (OVA/ONA/…)
# R23: متن در ثابت مشترک — دکمهٔ «◀️ بازگشت» زیرصفحهٔ «سایر» هم از آن
# استفاده می‌کند.
SEASON_QUESTION_TEXT = (
    "فصل چند هست؟ (یکی از دکمه‌ها را بزن یا عدد/متن تایپ کن)"
)


async def _send_season_question(target: Any, context: Any = None) -> None:
    sent = await target.reply_text(
        SEASON_QUESTION_TEXT,
        reply_markup=season_keyboard(),
    )
    if context is not None:
        register_panel_message(context, sent.message_id)
        set_question_message(context, sent.message_id)


def is_other_season(season) -> bool:
    """R17: فصل از نوع «سایر» است (OVA/ONA/Special — بدون حساسیت حروف)."""
    return (season or "").strip().lower() in {
        s.lower() for s in OTHER_SEASONS
    }


def _part_question_text(season_display: str, is_other: bool = False) -> str:
    # R17: برای سایر‌فصل‌ها به‌جای پارت، «شماره» پرسیده می‌شود
    question = "شماره چند هست؟" if is_other else "پارت چند هست؟"
    return f"✅ فصل: {season_display}\n\n{question}"


# R19: متن سؤال «سینمایی چندم» — مشترک بین هر دو مسیر (هویت و next_ep)
MOVIE_QUESTION_TEXT = (
    "سینمایی چندم هست؟\n"
    "(یکی از دکمه‌ها را بزن یا عدد تایپ کن — اگر شماره ندارد "
    "«➖ شماره ندارد» را بزن)"
)


async def _send_movie_question(target: Any, context: Any = None) -> None:
    sent = await target.reply_text(
        MOVIE_QUESTION_TEXT,
        reply_markup=movie_keyboard(),
    )
    if context is not None:
        register_panel_message(context, sent.message_id)
        set_question_message(context, sent.message_id)


async def _ask_anime_name_for(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    if query:
        sent = await context.bot.send_message(
            chat_id=query.from_user.id,
            text="اسم انیمه را وارد کن: (فقط حروف انگلیسی)",
            reply_markup=UPLOAD_CANCEL_INLINE,
        )
        register_panel_message(context, sent.message_id)
        set_question_message(context, sent.message_id)
