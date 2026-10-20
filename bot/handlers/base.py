import logging
import re
import sqlite3

from telegram import Update
from telegram.ext import ContextTypes

from ..config import config
from ..constants import Msg
from ..database import db
from ..keyboards import main_menu_for
from ..services.delivery import (
    deliver_files_for_session,
    deliver_post_for_session,
    deliver_summary_for_session,
)
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


async def handle_report_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    if not query or not query.from_user:
        return

    await query.answer()
    match = re.match(r"^report:(.+)$", query.data or "")
    if not match:
        return

    session_id = match.group(1).strip()

    try:
        db.save_report(session_id, query.from_user.id)
    except sqlite3.Error:
        logger.exception("ثبت گزارش ناموفق session=%s", session_id)
        await query.edit_message_text(
            "❌ این لینک دیگر معتبر نیست؛ امکان ثبت گزارش وجود ندارد."
        )
        return

    await query.edit_message_text(Msg.REPORT_SAVED)
