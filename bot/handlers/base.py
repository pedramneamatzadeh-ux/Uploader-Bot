import logging
import re
import sqlite3

from telegram import InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes, ConversationHandler

from ..config import config
from ..constants import WAIT_REPORT_TEXT, Msg
from ..database import db
from ..keyboards import ib, main_menu_for
from ..services.delivery import (
    deliver_files_for_session,
    deliver_post_for_session,
    deliver_summary_for_session,
)
from ..services.panels import close_panels_for
from ..utils import track_user


logger = logging.getLogger(__name__)


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return

    # P16 — /start همیشه منوی تمیز می‌دهد: همه‌ی پنل‌های باز بسته می‌شوند.
    if update.effective_chat:
        close_panels_for(context, update.effective_chat.id, user.id)

    track_user(update)

    if context.args:
        session_id = context.args[0].strip()

        if await deliver_files_for_session(update, context, session_id):
            return

        if await deliver_post_for_session(update, context, session_id):
            return

        if await deliver_summary_for_session(update, context, session_id):
            return

        await message.reply_text(Msg.INVALID_LINK)
        return

    if user.id in config.ADMIN_IDS or user.id == config.OWNER_ID:
        await message.reply_text(
            Msg.ADMIN_WELCOME,
            reply_markup=main_menu_for(user.id),
        )
    else:
        await message.reply_text(Msg.USER_WELCOME)


async def recheck_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    if not query:
        return

    await query.answer()
    match = re.match(r"^recheck:(.+)$", query.data or "")
    if not match:
        return

    session_id = match.group(1).strip()

    if await deliver_files_for_session(update, context, session_id):
        return

    if await deliver_post_for_session(update, context, session_id):
        return

    await deliver_summary_for_session(update, context, session_id)


def _report_choice_keyboard() -> InlineKeyboardMarkup:
    """R8c: دو گزینه — ثبت بدون توضیح / لغو گزارش."""
    return InlineKeyboardMarkup(
        [
            [
                ib("⏭️ ثبت بدون توضیح", callback_data="report_skip"),
                ib("❌ لغو گزارش", callback_data="report_cancel"),
            ]
        ]
    )


async def _edit_report_message(
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> bool:
    """ویرایش پیام «توضیحات»؛ False یعنی پیام در دسترس نبود."""
    pending = context.user_data.pop("pending_report_msg", None)
    if not pending:
        return False

    chat_id, message_id = pending
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
        )
        return True
    except TelegramError:
        return False


async def start_report(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """R8c ورودی: دکمه «🔴 گزارش خرابی فایل‌ها» → دریافت توضیحات."""
    query = update.callback_query
    if not query or not query.from_user:
        return ConversationHandler.END

    await query.answer()
    match = re.match(r"^report:(.+)$", query.data or "")
    if not match:
        return ConversationHandler.END

    session_id = match.group(1).strip()
    if not db.get_upload(session_id):
        await query.edit_message_text(Msg.REPORT_INVALID_LINK)
        return ConversationHandler.END

    # R8e: لغو حذفِ پیامِ حامل دکمه گزارش — پیام تا پایان
    # دریافت توضیحات باقی می‌ماند.
    pending_tasks = context.chat_data.get("report_del_tasks") or {}
    if query.message:
        task = pending_tasks.pop(query.message.message_id, None)
        if task is not None:
            task.cancel()

    context.user_data["pending_report_session"] = session_id
    if query.message:
        context.user_data["pending_report_msg"] = (
            query.message.chat_id,
            query.message.message_id,
        )

    await query.edit_message_text(
        Msg.REPORT_ASK,
        reply_markup=_report_choice_keyboard(),
    )
    return WAIT_REPORT_TEXT


async def receive_report_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """R8c: متن توضیحات کاربر همراه گزارش ذخیره می‌شود (report_text)."""
    session_id = context.user_data.pop("pending_report_session", None)
    if not session_id or not update.effective_user or not update.message:
        return ConversationHandler.END

    text = (update.message.text or "").strip()
    try:
        db.save_report(session_id, update.effective_user.id, text or None)
    except sqlite3.Error:
        logger.exception("ثبت گزارش ناموفق session=%s", session_id)
        await update.message.reply_text(Msg.SAVE_ERROR)
        return ConversationHandler.END

    if not await _edit_report_message(context, Msg.REPORT_SAVED):
        await update.message.reply_text(Msg.REPORT_SAVED)
    return ConversationHandler.END


async def report_skip(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """R8c: ثبت گزارش بدون توضیحات (دکمه «⏭️ ثبت بدون توضیح»)."""
    query = update.callback_query
    if not query or not query.from_user:
        return ConversationHandler.END

    await query.answer()
    session_id = context.user_data.pop("pending_report_session", None)
    if not session_id:
        return ConversationHandler.END

    try:
        db.save_report(session_id, query.from_user.id, None)
    except sqlite3.Error:
        logger.exception("ثبت گزارش ناموفق session=%s", session_id)
        await query.edit_message_text(Msg.SAVE_ERROR)
        return ConversationHandler.END

    context.user_data.pop("pending_report_msg", None)
    await query.edit_message_text(Msg.REPORT_SAVED)
    return ConversationHandler.END


async def report_cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """R8c: لغو کامل گزارش — چیزی ثبت نمی‌شود."""
    query = update.callback_query
    if not query:
        return ConversationHandler.END

    await query.answer()
    context.user_data.pop("pending_report_session", None)
    context.user_data.pop("pending_report_msg", None)
    await query.edit_message_text(Msg.REPORT_CANCELLED)
    return ConversationHandler.END
