"""گیرنده‌های متنی ساخت/ویرایش."""

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
    ONGOING_PART_MENU,
    build_pagination_row,
    main_menu_for,
    quality_keyboard,
)
from ...utils import (
    build_download_link,
    fmt_tehran,
    get_default_channel_chat_id,
    go_to_ongoing_list,
    normalize_optional_text,
    safe_edit_or_send,
    total_pages,
    validate_channel_input,
    validate_episode_input,
)

from .cancel import handle_ongoing_text_cancel
from .views import show_ongoing_anime_detail

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ساخت انیمه جدید
# ---------------------------------------------------------------------------
@admin_only
async def receive_ongoing_create_name(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    text = update.message.text.strip()
    cancel_state = await handle_ongoing_text_cancel(update, context, text)
    if cancel_state is not None:
        return cancel_state

    context.user_data.setdefault("ongoing_new", {})["anime_name"] = text
    await update.message.reply_text(
        "فصل چند هست؟\nاگر ندارد، بنویس: -",
        reply_markup=ONGOING_CANCEL_MENU,
    )
    return ONGOING_CREATE_SEASON


@admin_only
async def receive_ongoing_create_season(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    text = update.message.text.strip()
    cancel_state = await handle_ongoing_text_cancel(update, context, text)
    if cancel_state is not None:
        return cancel_state

    context.user_data.setdefault("ongoing_new", {})[
        "season_num"
    ] = normalize_optional_text(text)
    await update.message.reply_text(
        "پارت چند هست؟",
        reply_markup=ONGOING_PART_MENU,
    )
    return ONGOING_CREATE_PART


@admin_only
async def receive_ongoing_create_part(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    text = update.message.text.strip()
    cancel_state = await handle_ongoing_text_cancel(update, context, text)
    if cancel_state is not None:
        return cancel_state

    data = context.user_data.setdefault("ongoing_new", {})
    data["part_num"] = normalize_optional_text(text)

    try:
        anime_id = db.save_ongoing_anime(data, update.effective_user.id)
    except sqlite3.Error as err:
        logger.exception("خطا در ثبت انیمه درحال پخش: %s", err)
        await update.message.reply_text(
            Msg.SAVE_ERROR,
            reply_markup=main_menu_for(update.effective_user.id),
        )
        return ONGOING_LIST

    context.user_data.pop("ongoing_new", None)
    await update.message.reply_text(
        "✅ انیمه درحال پخش با موفقیت ثبت شد.",
        reply_markup=main_menu_for(update.effective_user.id),
    )

    context.user_data["ongoing_manage"] = {"page": 0}
    await show_ongoing_anime_detail(update.message.chat_id, context, anime_id)
    return ONGOING_DETAIL


@admin_only
async def handle_ongoing_edit_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    text = update.message.text.strip()
    cancel_state = await handle_ongoing_text_cancel(update, context, text)
    if cancel_state is not None:
        return cancel_state

    edit = context.user_data.get("ongoing_edit")
    if not edit:
        await update.message.reply_text("❌ اطلاعات ویرایش نامعتبر است.")
        return ONGOING_LIST

    anime_id = edit["id"]
    field_key = edit["field"]
    db_field = ONGOING_FIELD_MAP.get(field_key)

    if not db_field:
        await update.message.reply_text("❌ فیلد نامعتبر است.")
        return ONGOING_DETAIL

    value = (
        normalize_optional_text(text)
        if field_key in ("season", "part")
        else text
    )

    if db.update_ongoing_anime(anime_id, db_field, value):
        await update.message.reply_text("✅ اطلاعات با موفقیت بروزرسانی شد.")
        context.user_data.pop("ongoing_edit", None)
        await show_ongoing_anime_detail(update.message.chat_id, context, anime_id)
        return ONGOING_DETAIL

    await update.message.reply_text("❌ خطا در ذخیره تغییرات.")
    return ONGOING_EDIT
