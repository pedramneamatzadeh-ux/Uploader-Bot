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
    SETTINGS_SUMMARY_PHOTO_CHAT,
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
    settings_duration_menu_keyboard,
    settings_input_keyboard,
    settings_panel_keyboard,
    settings_summary_photo_keyboard,
)
from ...utils import go_to_main_menu, normalize_digits, register_panel_message

from .common import (
    DURATION_KINDS,
    _MAX_DURATION_SECONDS,
    _admin_names,
    _admins_text,
    _channel_titles,
    _channels_text,
    ensure_channel_titles,
    _dbs_text,
    _duration_text,
    _photo_channel_titles,
    _photo_channels,
    _save_photo_channels,
    _summary_photo_chat_text,
    ensure_summary_photo_titles,
    _panel_text,
    _safe_edit,
    _show_prompt,
    _show_section,
    _store_prompt,
)

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


DURATION_SETTING_KEYS = {
    "files": "delete_after_seconds",
    "posts": "delete_after_seconds_posts",
    "summary": "delete_after_seconds_summary",
    "panel": "delete_after_seconds_panel",
}


def _save_duration(kind: str, seconds: int) -> None:
    """R27: ذخیرهٔ زمان حذف برای هدف انتخابی (فایل/پست/پنل)."""
    db.set_setting(
        DURATION_SETTING_KEYS.get(kind, "delete_after_seconds"), seconds
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
                list(config.ADMIN_IDS or []),
                config.OWNER_ID,
                names=_admin_names(),  # R23: دو ستون آیدی/اسم
            ),
        )

    if action == "channels":
        # R23b: برای کانال‌های قدیمی، عنوان را از تلگرام می‌گیرد
        titles = await ensure_channel_titles(context)
        return await _show_section(
            context, query,
            _channels_text(),
            settings_channels_keyboard(
                list(config.REQUIRED_CHANNELS or []),
                names=titles,  # R23: دو ستون آیدی/اسم
            ),
        )

    if action == "duration":
        # R27: اول هدف (فایل/پست/پنل) انتخاب می‌شود
        return await _show_section(
            context, query,
            "⏱ کدام زمان حذف را می‌خواهی تنظیم کنی؟",
            settings_duration_menu_keyboard(),
        )

    if action == "dbs":
        return await _show_section(
            context, query,
            _dbs_text(),
            settings_databases_keyboard(db.get_custom_databases()),
        )

    # --- R33/R34: کانال‌های عکس خلاصه (چندتایی، مثل ادمین‌ها) ---
    if action == "sumphoto":
        titles = await ensure_summary_photo_titles(context)
        return await _show_section(
            context, query,
            _summary_photo_chat_text(),
            settings_summary_photo_keyboard(_photo_channels(), titles),
        )

    if action == "sumphoto_set":
        await _show_prompt(
            context, query, Msg.ADD_SUMMARY_PHOTO_CHAT_PROMPT
        )
        return SETTINGS_SUMMARY_PHOTO_CHAT

    if action.startswith("sumphoto_del_yes:"):
        raw = action.split(":", 1)[1]
        chats = _photo_channels()
        titles = await ensure_summary_photo_titles(context)
        if raw.isdigit() and int(raw) < len(chats):
            removed = chats.pop(int(raw))
            _save_photo_channels(chats)
            text = (
                f"🗑 کانال {removed} حذف شد.\n\n{_summary_photo_chat_text()}"
            )
        else:
            text = (
                "❌ کانال نامعتبر بود.\n\n" + _summary_photo_chat_text()
            )
        return await _show_section(
            context, query,
            text,
            settings_summary_photo_keyboard(_photo_channels(), titles),
        )

    if action.startswith("sumphoto_del:"):
        raw = action.split(":", 1)[1]
        chats = _photo_channels()
        if not raw.isdigit() or int(raw) >= len(chats):
            await query.answer("❌ کانال نامعتبر.", show_alert=True)
            return SETTINGS_PANEL
        titles = await ensure_summary_photo_titles(context)
        label = titles.get(str(chats[int(raw)])) or str(chats[int(raw)])
        await _safe_edit(
            query,
            f"❓ مطمئنی می‌خواهی کانال {label} از فهرست عکس خلاصه‌ها "
            "حذف شود؟\n\n(خودِ کانال و عکس‌هایش دست‌نخورده می‌مانند؛ "
            "فقط ربات دیگر از آن کپی نمی‌کند.)",
            settings_confirm_keyboard(
                f"st:sumphoto_del_yes:{raw}", "st:sumphoto"
            ),
        )
        return SETTINGS_PANEL

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
                list(config.ADMIN_IDS or []),
                config.OWNER_ID,
                names=_admin_names(),  # R23: دو ستون آیدی/اسم
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
                list(config.REQUIRED_CHANNELS or []),
                names=await ensure_channel_titles(context),
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
    if action.startswith("dur_menu:"):
        kind = action.split(":", 1)[1]
        if kind not in DURATION_KINDS:
            await query.answer(Msg.DURATION_INVALID, show_alert=True)
            return SETTINGS_PANEL
        return await _show_section(
            context, query,
            _duration_text(kind),
            settings_duration_keyboard(kind),
        )

    if action.startswith("dur:"):
        parts = action.split(":")
        if len(parts) != 3:
            await query.answer(Msg.DURATION_INVALID, show_alert=True)
            return SETTINGS_PANEL
        kind, raw = parts[1], parts[2]
        if (
            kind not in DURATION_KINDS
            or not raw.isdigit()
            or int(raw) < 1
            or int(raw) > _MAX_DURATION_SECONDS
        ):
            await query.answer(Msg.DURATION_INVALID, show_alert=True)
            return SETTINGS_PANEL
        _save_duration(kind, int(raw))
        text = f"{Msg.DURATION_SET}\n\n{_duration_text(kind)}"
        return await _show_section(
            context, query,
            text,
            settings_duration_keyboard(kind),
        )

    if action.startswith("dur_custom"):
        parts = action.split(":")
        kind = parts[1] if len(parts) > 1 else "files"
        if kind not in DURATION_KINDS:
            kind = "files"
        context.user_data["st_duration_kind"] = kind
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
