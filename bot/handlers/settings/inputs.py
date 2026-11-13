"""گیرنده‌های متنی بخش‌ها."""

import logging
import re
from typing import Optional

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes, ConversationHandler

from ...config import config
from ...constants import (
    SETTINGS_ADMIN,
    SETTINGS_CHANNEL,
    SETTINGS_DB_CHAT,
    SETTINGS_DB_NAME,
    SETTINGS_DURATION,
    SETTINGS_PANEL,
    Msg,
)
from ...database import db
from ...decorators import owner_only
from ...keyboards import (
    main_menu_for,
    settings_admins_keyboard,
    settings_channels_keyboard,
    settings_confirm_keyboard,
    settings_databases_keyboard,
    settings_duration_keyboard,
    settings_input_keyboard,
    settings_panel_keyboard,
)
from ...utils import go_to_main_menu, normalize_digits

from .common import (
    _MAX_DURATION_SECONDS,
    _admin_names,
    _admins_text,
    _channel_titles,
    _channels_text,
    _dbs_text,
    _duration_text,
    _edit_by_id,
    _forwarded_user_id,
    _handle_text_cancel,
    _panel_text,
    _precheck_chat,
    _resolve_chat_target,
    _retry_input,
)

logger = logging.getLogger(__name__)


# ============================================================================
# stateهای ورودی متنی
# ============================================================================
@owner_only
async def receive_admin_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    cancel_state = await _handle_text_cancel(update, context)
    if cancel_state is not None:
        return cancel_state

    message = update.message
    target = _forwarded_user_id(message)
    if target is None:
        text = normalize_digits((message.text or "").strip())
        if re.fullmatch(r"\d+", text):
            target = int(text)

    if target is None or target <= 0:
        await _retry_input(
            update, context, Msg.ADMIN_ID_INVALID, Msg.ADD_ADMIN_PROMPT
        )
        return SETTINGS_ADMIN

    if config.OWNER_ID is not None and target == config.OWNER_ID:
        await _retry_input(
            update, context, Msg.ADMIN_IS_OWNER, Msg.ADD_ADMIN_PROMPT
        )
        return SETTINGS_ADMIN

    ids = list(config.ADMIN_IDS or [])
    if target in ids:
        await _retry_input(
            update, context, Msg.ADMIN_ALREADY, Msg.ADD_ADMIN_PROMPT
        )
        return SETTINGS_ADMIN

    ids.append(target)
    db.set_setting("admin_ids", ids)

    text = f"{Msg.ADMIN_ADDED} ({target})\n\n{_admins_text()}"
    await _edit_by_id(
        context,
        context.user_data.get("st_chat"),
        context.user_data.get("st_msg"),
        text,
        settings_admins_keyboard(
            list(config.ADMIN_IDS or []),
            config.OWNER_ID,
            names=_admin_names(),
        ),
    )
    return SETTINGS_PANEL


@owner_only
async def receive_channel_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    cancel_state = await _handle_text_cancel(update, context)
    if cancel_state is not None:
        return cancel_state

    message = update.message
    target = _resolve_chat_target(message)
    if target is None:
        await _retry_input(
            update, context, Msg.CHANNEL_INVALID, Msg.ADD_CHANNEL_PROMPT
        )
        return SETTINGS_CHANNEL

    chat_id, error = await _precheck_chat(context, target)
    if error is not None:
        await _retry_input(
            update, context, error, Msg.ADD_CHANNEL_PROMPT
        )
        return SETTINGS_CHANNEL

    channels = list(config.REQUIRED_CHANNELS or [])
    if str(chat_id) in [str(item) for item in channels]:
        await _retry_input(
            update, context, Msg.CHANNEL_ALREADY, Msg.ADD_CHANNEL_PROMPT
        )
        return SETTINGS_CHANNEL

    channels.append(chat_id)
    db.set_setting("required_channels", channels)

    # R23: عنوان کانال برای نمایش دو ستونی (ستون اسم) ذخیره می‌شود
    try:
        chat_obj = await context.bot.get_chat(chat_id)
        title = (
            getattr(chat_obj, "title", None)
            or getattr(chat_obj, "username", None)
            or ""
        )
        if title:
            titles = dict(_channel_titles())
            titles[str(chat_id)] = title
            db.set_setting("required_channel_titles", titles)
    except TelegramError:
        logger.debug("ذخیرهٔ عنوان کانال ناموفق بود", exc_info=True)

    text = f"{Msg.CHANNEL_ADDED}\n\n{_channels_text()}"
    await _edit_by_id(
        context,
        context.user_data.get("st_chat"),
        context.user_data.get("st_msg"),
        text,
        settings_channels_keyboard(
            list(config.REQUIRED_CHANNELS or []),
            names=_channel_titles(),
        ),
    )
    return SETTINGS_PANEL


@owner_only
async def receive_duration_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    cancel_state = await _handle_text_cancel(update, context)
    if cancel_state is not None:
        return cancel_state

    text = normalize_digits((update.message.text or "").strip())
    if not re.fullmatch(r"\d+", text):
        await _retry_input(
            update, context,
            Msg.DURATION_INVALID,
            Msg.ADD_DURATION_PROMPT,
        )
        return SETTINGS_DURATION

    value = int(text)
    if value < 1 or value > _MAX_DURATION_SECONDS:
        await _retry_input(
            update, context,
            Msg.DURATION_INVALID,
            Msg.ADD_DURATION_PROMPT,
        )
        return SETTINGS_DURATION

    db.set_setting("delete_after_seconds", value)

    full = f"{Msg.DURATION_SET}\n\n{_duration_text()}"
    await _edit_by_id(
        context,
        context.user_data.get("st_chat"),
        context.user_data.get("st_msg"),
        full,
        settings_duration_keyboard(),
    )
    return SETTINGS_PANEL


@owner_only
async def receive_db_name_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    cancel_state = await _handle_text_cancel(update, context)
    if cancel_state is not None:
        return cancel_state

    text = (update.message.text or "").strip()
    if not 1 <= len(text) <= 60:
        await _retry_input(
            update, context, Msg.DB_NAME_INVALID, Msg.ADD_DB_NAME_PROMPT
        )
        return SETTINGS_DB_NAME

    names = [row["name"] for row in db.get_custom_databases()]
    if text in names:
        await _retry_input(
            update, context,
            Msg.DB_NAME_DUPLICATE,
            Msg.ADD_DB_NAME_PROMPT,
        )
        return SETTINGS_DB_NAME

    context.user_data["st_new_db"] = text
    await _edit_by_id(
        context,
        context.user_data.get("st_chat"),
        context.user_data.get("st_msg"),
        Msg.ADD_DB_CHAT_PROMPT,
        settings_input_keyboard(),
    )
    return SETTINGS_DB_CHAT


@owner_only
async def receive_db_chat_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    cancel_state = await _handle_text_cancel(update, context)
    if cancel_state is not None:
        return cancel_state

    name = context.user_data.get("st_new_db")
    if not name:
        await _edit_by_id(
            context,
            context.user_data.get("st_chat"),
            context.user_data.get("st_msg"),
            _panel_text(),
            settings_panel_keyboard(),
        )
        return SETTINGS_PANEL

    message = update.message
    target = _resolve_chat_target(message)
    if target is None:
        await _retry_input(
            update, context, Msg.DB_CHAT_INVALID, Msg.ADD_DB_CHAT_PROMPT
        )
        return SETTINGS_DB_CHAT

    chat_id, error = await _precheck_chat(context, target)
    if error is not None:
        await _retry_input(
            update, context, error, Msg.ADD_DB_CHAT_PROMPT
        )
        return SETTINGS_DB_CHAT

    try:
        db.save_custom_database(
            name, chat_id, created_by=update.effective_user.id
        )
    except Exception:
        logger.exception("ذخیره دیتابیس سفارشی ناموفق: %s", name)
        await _retry_input(
            update, context, Msg.SAVE_ERROR, Msg.ADD_DB_NAME_PROMPT
        )
        return SETTINGS_DB_NAME

    context.user_data.pop("st_new_db", None)

    text = f"{Msg.DB_ADDED} «{name}»\n\n{_dbs_text()}"
    await _edit_by_id(
        context,
        context.user_data.get("st_chat"),
        context.user_data.get("st_msg"),
        text,
        settings_databases_keyboard(db.get_custom_databases()),
    )
    return SETTINGS_PANEL
