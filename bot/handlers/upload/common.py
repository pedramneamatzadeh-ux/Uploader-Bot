"""پرسش‌ها و هلپرهای مشترک فلوی آپلود."""

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
    "قسمت یا محدودهٔ قسمت‌ها را وارد کن. مثال: 2 یا 1-12"
)


# پذیرش متن انگلیسی برای «سایر» در سؤال فصل (OVA/ONA/…)
async def _send_season_question(target: Any) -> None:
    await target.reply_text(
        "فصل چند هست؟ (یکی از دکمه‌ها را بزن یا عدد/متن تایپ کن)",
        reply_markup=season_keyboard(),
    )


def _part_question_text(season_display: str) -> str:
    return f"✅ فصل: {season_display}\n\nپارت چند هست؟"


async def _send_movie_question(target: Any) -> None:
    await target.reply_text(
        "سینمایی چندم هست؟ (فقط عدد وارد کن)\nمثال: 1",
        reply_markup=movie_keyboard(),
    )


async def _ask_anime_name_for(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    if query:
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text="اسم انیمه را وارد کن: (فقط حروف انگلیسی)",
            reply_markup=CANCEL_MENU,
        )
