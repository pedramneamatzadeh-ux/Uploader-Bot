"""باز کردن پنل + dispatcher چهار بخش."""

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
from ...utils import go_to_main_menu, normalize_digits, register_panel_message

from .common import _MAX_DURATION_SECONDS, _admins_text, _channels_text, _dbs_text, _duration_text, _panel_text, _safe_edit, _show_prompt, _show_section, _store_prompt

logger = logging.getLogger(__name__)


# ============================================================================
# نقطه ورود + router اصلی
# ============================================================================
@owner_only
async def open_settings(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    context.user_data.pop("st_msg", None)
    context.user_data.pop("st_chat", None)
    context.user_data.pop("st_new_db", None)

    sent = await update.message.reply_text(
        _panel_text(),
        reply_markup=settings_panel_keyboard(),
    )
    register_panel_message(context, sent.message_id)
    return SETTINGS_PANEL


@owner_only
async def settings_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    try:
        return await _dispatch_settings(context, query)
    finally:
        # پاسخ callback فقط یک بار؛ شاخه‌های alert خودشان زده‌اند
        try:
            await query.answer()
        except Exception:
            logger.debug(
                "answerCallbackQuery ناموفق بود", exc_info=True
            )


async def _dispatch_settings(context, query) -> int:
    data = (query.data or "").strip()
    if not data.startswith("st:"):
        return SETTINGS_PANEL
    action = data[3:]

    # --- بازگشت به پنل / بستن ---
    if action in ("panel", "refresh"):
        _store_prompt(context, query)
        await _safe_edit(
            query, _panel_text(), settings_panel_keyboard()
        )
        return SETTINGS_PANEL

    if action == "cancel":
        context.user_data.pop("st_new_db", None)
        _store_prompt(context, query)
        await _safe_edit(
            query, _panel_text(), settings_panel_keyboard()
        )
        return SETTINGS_PANEL

    if action == "back":
        context.user_data.pop("st_msg", None)
        context.user_data.pop("st_chat", None)
        context.user_data.pop("st_new_db", None)
        await _safe_edit(query, "✅ به منوی اصلی بازگشتید.", None)
        if query.message:
            await go_to_main_menu(context, query.message.chat_id)
        return ConversationHandler.END

    # --- زیرمنوها ---
    if action == "admins":
        return await _show_section(
            context, query,
            _admins_text(),
            settings_admins_keyboard(
                list(config.ADMIN_IDS or []), config.OWNER_ID
            ),
        )

    if action == "channels":
        return await _show_section(
            context, query,
            _channels_text(),
            settings_channels_keyboard(
                list(config.REQUIRED_CHANNELS or [])
            ),
        )

    if action == "duration":
        return await _show_section(
            context, query,
            _duration_text(),
            settings_duration_keyboard(),
        )

    if action == "dbs":
        return await _show_section(
            context, query,
            _dbs_text(),
            settings_databases_keyboard(db.get_custom_databases()),
        )

    # --- افزودن ادمین ---
    if action == "adm_add":
        await _show_prompt(context, query, Msg.ADD_ADMIN_PROMPT)
        return SETTINGS_ADMIN

    # --- تأیید/حذف ادمین ---
    if action.startswith("adm_del_yes:"):
        raw = action.split(":", 1)[1]
        ids = list(config.ADMIN_IDS or [])
        if raw.isdigit() and int(raw) in ids:
            ids = [item for item in ids if item != int(raw)]
            db.set_setting("admin_ids", ids)
            text = f"{Msg.ADMIN_REMOVED}\n\n{_admins_text()}"
        else:
            text = f"{Msg.ADMIN_ID_INVALID}\n\n{_admins_text()}"
        return await _show_section(
            context, query,
            text,
            settings_admins_keyboard(
                list(config.ADMIN_IDS or []), config.OWNER_ID
            ),
        )

    if action.startswith("adm_del:"):
        raw = action.split(":", 1)[1]
        if not raw.isdigit():
            await query.answer(Msg.ADMIN_ID_INVALID, show_alert=True)
            return SETTINGS_PANEL
        await _safe_edit(
            query,
            f"❓ مطمئنی می‌خواهی ادمین {raw} حذف شود؟",
            settings_confirm_keyboard(
                f"st:adm_del_yes:{raw}", "st:admins"
            ),
        )
        return SETTINGS_PANEL

    # --- افزودن کانال ---
    if action == "ch_add":
        await _show_prompt(context, query, Msg.ADD_CHANNEL_PROMPT)
        return SETTINGS_CHANNEL

    # --- تأیید/حذف کانال ---
    if action.startswith("ch_del_yes:"):
        raw = action.split(":", 1)[1]
        channels = list(config.REQUIRED_CHANNELS or [])
        if raw.isdigit() and int(raw) < len(channels):
            removed = channels.pop(int(raw))
            db.set_setting("required_channels", channels)
            text = f"{Msg.CHANNEL_REMOVED} ({removed})\n\n{_channels_text()}"
        else:
            text = f"{Msg.CHANNEL_INVALID}\n\n{_channels_text()}"
        return await _show_section(
            context, query,
            text,
            settings_channels_keyboard(
                list(config.REQUIRED_CHANNELS or [])
            ),
        )

    if action.startswith("ch_del:"):
        raw = action.split(":", 1)[1]
        channels = list(config.REQUIRED_CHANNELS or [])
        if not raw.isdigit() or int(raw) >= len(channels):
            await query.answer(Msg.CHANNEL_INVALID, show_alert=True)
            return SETTINGS_PANEL
        label = channels[int(raw)]
        await _safe_edit(
            query,
            f"❓ مطمئنی می‌خواهی کانال {label} حذف شود؟",
            settings_confirm_keyboard(
                f"st:ch_del_yes:{raw}", "st:channels"
            ),
        )
        return SETTINGS_PANEL

    # --- مدت حذف ---
    if action.startswith("dur:"):
        raw = action.split(":", 1)[1]
        if (
            not raw.isdigit()
            or int(raw) < 1
            or int(raw) > _MAX_DURATION_SECONDS
        ):
            await query.answer(Msg.DURATION_INVALID, show_alert=True)
            return SETTINGS_PANEL
        db.set_setting("delete_after_seconds", int(raw))
        text = f"{Msg.DURATION_SET}\n\n{_duration_text()}"
        return await _show_section(
            context, query,
            text,
            settings_duration_keyboard(),
        )

    if action == "dur_custom":
        await _show_prompt(context, query, Msg.ADD_DURATION_PROMPT)
        return SETTINGS_DURATION

    # --- دیتابیس‌های سفارشی ---
    if action == "db_add":
        context.user_data.pop("st_new_db", None)
        await _show_prompt(context, query, Msg.ADD_DB_NAME_PROMPT)
        return SETTINGS_DB_NAME

    if action.startswith("db_del_yes:"):
        raw = action.split(":", 1)[1]
        target = None
        if raw.isdigit():
            target = next(
                (
                    row
                    for row in db.get_custom_databases()
                    if row["id"] == int(raw)
                ),
                None,
            )
        if target and db.delete_custom_database(target["id"]):
            text = f"{Msg.DB_REMOVED}\n\n{_dbs_text()}"
        else:
            text = f"{Msg.CHANNEL_CHECK_FAILED}\n\n{_dbs_text()}"
        return await _show_section(
            context, query,
            text,
            settings_databases_keyboard(db.get_custom_databases()),
        )

    if action.startswith("db_del:"):
        raw = action.split(":", 1)[1]
        row = None
        if raw.isdigit():
            row = next(
                (
                    item
                    for item in db.get_custom_databases()
                    if item["id"] == int(raw)
                ),
                None,
            )
        if not row:
            await query.answer(
                Msg.CHANNEL_CHECK_FAILED, show_alert=True
            )
            return SETTINGS_PANEL
        await _safe_edit(
            query,
            (
                f"❓ دیتابیس «{row['name']}» از لیست حذف شود؟\n\n"
                "فقط از لیست انتخاب حذف می‌شود؛ "
                "فایل‌های موجود در کانال پاک نمی‌شوند."
            ),
            settings_confirm_keyboard(
                f"st:db_del_yes:{raw}", "st:dbs"
            ),
        )
        return SETTINGS_PANEL

    # --- ناشناخته ---
    await query.answer(Msg.INVALID_COMMAND, show_alert=True)
    return SETTINGS_PANEL
