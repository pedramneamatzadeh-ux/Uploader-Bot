import logging
import re
import sqlite3
from typing import Optional

from telegram import InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes, ConversationHandler

from ..config import config
from ..constants import WAIT_REPORT_DETAIL, WAIT_REPORT_TEXT, Msg
from ..database import db
from ..keyboards import ib, main_menu_for
from ..services.delivery import (
    deliver_files_for_session,
    deliver_post_for_session,
    deliver_summary_for_session,
)
from ..services.group_panel import close_user_panel, deliver_group_panel
from ..services.panels import close_panels_for
from ..utils import build_download_link, fmt_tehran, track_user


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
    # R38: پنل لینک فصل فقط با «❌ انصراف» (یا همین /start) بسته می‌شود
    await close_user_panel(context, answer_text=Msg.GROUP_PANEL_CLOSED)

    track_user(update)

    if context.args:
        session_id = context.args[0].strip()

        # R26: لینک فصل/پارت (کد با پیشوند s_) ⇒ پنل کیفیت‌ها/قسمت‌ها
        if session_id.startswith("s_"):
            if await deliver_group_panel(update, context, session_id):
                return

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

    # R36: «بررسی مجدد» باید همهٔ انواع لینک را پوشش بدهد (قبلاً برای
    # لینک فصل `s_...` هیچ کاری نمی‌کرد و پیام عضویت دست‌نخورده می‌ماند).
    if session_id.startswith("s_"):
        if await deliver_group_panel(update, context, session_id):
            return

    if await deliver_files_for_session(update, context, session_id):
        return

    if await deliver_post_for_session(update, context, session_id):
        return

    if await deliver_summary_for_session(update, context, session_id):
        return

    await context.bot.send_message(
        query.message.chat_id if query.message else update.effective_user.id,
        Msg.INVALID_LINK,
    )


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


def _report_details_text(report: dict) -> str:
    """R37: جزئیات خوانا برای پیام گزارش.

    بازهٔ پیام‌های کانال عمداً نمایش داده نمی‌شود (اطلاعات داخلی) و
    لینک دانلود جداگانه به پیام اضافه می‌شود.
    """
    name = db.get_display_for(
        report.get("anime_name") or "",
        report.get("season_num") or "",
        report.get("part_num") or "",
    ) or (report.get("anime_name") or "")
    lines = [f"🎬 «{name}»"]
    season = (report.get("season_num") or "").strip()
    part = (report.get("part_num") or "").strip()
    if season:
        if (report.get("anime_type") or "") == "سینمایی":
            lines.append(f"📽 سینمایی شماره {season}")
        else:
            line = f"📚 فصل {season}"
            if part:
                line += f" | پارت {part}"
            lines.append(line)
    episode = (report.get("episode_range") or "").strip()
    if episode and (report.get("anime_type") or "") != "سینمایی":
        lines.append(f"📺 قسمت: {episode}")
    lines.append(f"🎞 کیفیت: {report.get('quality') or '—'}")
    return "\n".join(lines)


def _report_detail_keyboard(report_id: int) -> InlineKeyboardMarkup:
    """R37: دو دکمهٔ شیشه‌ای برای گزارش‌دهنده.

    • «✍️ دقیقاً مشکل چیه؟» ⇒ توضیح می‌نویسد و ثبت می‌کند
    • «❌ انصراف» ⇒ گزارش خودکار «حل‌شده» می‌شود و بسته می‌شود
    """
    return InlineKeyboardMarkup(
        [
            [
                ib(
                    "✍️ دقیقاً مشکل چیه؟",
                    style="primary",
                    callback_data=f"report_more_write:{report_id}",
                )
            ],
            [
                ib(
                    "❌ انصراف",
                    style="danger",
                    callback_data=f"report_more_cancel:{report_id}",
                )
            ],
        ]
    )


def _report_ask_keyboard(report_id: int) -> InlineKeyboardMarkup:
    """R37: در حالت نوشتن توضیح — «✅ ثبت توضیح» + «❌ انصراف»."""
    return InlineKeyboardMarkup(
        [
            [
                ib(
                    "✅ ثبت توضیح",
                    style="success",
                    callback_data=f"report_more_save:{report_id}",
                )
            ],
            [
                ib(
                    "❌ انصراف",
                    style="danger",
                    callback_data=f"report_more_cancel:{report_id}",
                )
            ],
        ]
    )


async def request_more_report_info(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """R37: ادمین در آمار «🔎 دقیقاً مشکل چیه؟» را می‌زند.

    به **گزارش‌دهنده** پیام + لینک دانلود + دو دکمهٔ شیشه‌ای می‌فرستد.
    این handler فقط برای ادمین/مالک اجرا می‌شود.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    caller = query.from_user
    if not caller or (
        caller.id != config.OWNER_ID
        and caller.id not in (config.ADMIN_IDS or [])
    ):
        await query.answer(Msg.ADMIN_ONLY, show_alert=True)
        return

    match = re.match(r"^report_more:(\d+)$", query.data)
    if not match:
        await query.answer()
        return

    report_id = int(match.group(1))
    report = db.get_report_by_id(report_id)
    if not report:
        await query.answer(Msg.REPORT_NOT_FOUND, show_alert=True)
        return
    if report.get("status") == "resolved":
        await query.answer(
            Msg.REPORT_MORE_INFO_TOAST_RESOLVED, show_alert=True
        )
        return

    notice = Msg.REPORT_MORE_INFO_NOTICE.format(
        details=_report_details_text(report)
    )
    try:
        link = await build_download_link(context, report["session_id"])
    except TelegramError:
        link = ""
        logger.warning("ساخت لینک گزارش #%s ناموفق بود", report_id)

    sent = False
    try:
        await context.bot.send_message(
            report["user_id"],
            notice,
            reply_markup=_report_detail_keyboard(report_id),
        )
        sent = True
    except TelegramError:
        logger.warning(
            "ارسال درخواست توضیح #%s به کاربر %s ناموفق بود",
            report_id,
            report["user_id"],
        )

    # لینک دانلود جدا؛ اگر «تک‌کلیک‌کپی» لازم بود یک پیام مستقل
    if sent and link:
        try:
            # R38: لینک **معمولی** (بدون mono) — درخواست کاربر
            await context.bot.send_message(
                report["user_id"],
                f"{Msg.REPORT_LINK_TEXT}\n{link}",
            )
        except TelegramError:
            pass

    await query.answer(
        Msg.REPORT_MORE_INFO_TOAST_OK
        if sent
        else Msg.REPORT_MORE_INFO_TOAST_FAIL,
        show_alert=not sent,
    )


async def report_detail_prompt(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """R37: گزارش‌دهنده «✍️ دقیقاً مشکل چیه؟» را می‌زند ⇒ حالت نوشتن."""
    query = update.callback_query
    if not query or not query.data:
        return ConversationHandler.END

    match = re.match(r"^report_more_write:(\d+)$", query.data)
    if not match:
        await query.answer()
        return ConversationHandler.END

    report_id = int(match.group(1))
    report = db.get_report_by_id(report_id)
    if not report:
        await query.answer(Msg.REPORT_NOT_FOUND, show_alert=True)
        return ConversationHandler.END

    if report.get("status") == "resolved":
        await query.answer(
            Msg.REPORT_MORE_INFO_TOAST_RESOLVED, show_alert=True
        )
        return ConversationHandler.END

    caller = query.from_user
    if not caller or caller.id != report["user_id"]:
        await query.answer(Msg.REPORT_NOT_YOURS, show_alert=True)
        return ConversationHandler.END

    await query.answer()
    context.user_data["report_detail_id"] = report_id
    if query.message:
        context.user_data["report_detail_msg"] = (
            query.message.chat_id,
            query.message.message_id,
        )

    prompt = f"{Msg.REPORT_DETAIL_ASK}\n\n{_report_details_text(report)}"
    edited = False
    try:
        await query.edit_message_text(
            prompt, reply_markup=_report_ask_keyboard(report_id)
        )
        edited = True
    except TelegramError as err:
        logger.info("ویرایش پیام توضیح گزارش ممکن نشد: %s", err)

    if not edited:
        try:
            await context.bot.send_message(
                report["user_id"],
                prompt,
                reply_markup=_report_ask_keyboard(report_id),
            )
        except TelegramError:
            await query.answer(
                Msg.REPORT_MORE_INFO_TOAST_FAIL, show_alert=True
            )
            return ConversationHandler.END
    return WAIT_REPORT_DETAIL


def _close_and_reopen(
    report_id: int,
    text: str,
    user_id: int,
) -> Optional[int]:
    """R37: بستن گزارش قبلی + ثبت بازهٔ تازهٔ همان فایل.

    خروجی: آیدی گزارش جدید (یا None اگر ناموفق بود).
    """
    report = db.get_report_by_id(report_id)
    if not report:
        return None

    db.update_report_status(report_id, "resolved")

    try:
        new_id = db.save_report(
            report["session_id"], user_id, (text or "").strip() or None
        )
    except Exception:      # noqa: BLE001 — نباید مکالمه را بشکند
        logger.exception("ثبت گزارش بازهٔ تازه ناموفق (base=%s)", report_id)
        return None
    return new_id


async def report_more_save(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """R37: دکمهٔ «✅ ثبت توضیح» — متن نوشته‌شده را ثبت می‌کند.

    گزارش قبلی **بسته (حل‌شده)** و یک گزارش تازه با همان فایل و همان
    توضیح باز می‌شود؛ فقط گزارش تازه با دکمه‌های «دقیقاً مشکل چیه؟» و
    «انصراف» دوباره در دسترس است.
    """
    query = update.callback_query
    if not query or not query.data:
        return ConversationHandler.END

    match = re.match(r"^report_more_save:(\d+)$", query.data)
    if not match:
        await query.answer()
        return WAIT_REPORT_DETAIL

    report_id = int(match.group(1))
    user_id = query.from_user.id if query.from_user else None
    draft = (context.user_data.get("report_detail_draft") or "").strip()
    if not draft:
        await query.answer(Msg.REPORT_DETAIL_EMPTY, show_alert=True)
        return WAIT_REPORT_DETAIL

    new_id = _close_and_reopen(report_id, draft, user_id)
    context.user_data.pop("report_detail_id", None)
    context.user_data.pop("report_detail_draft", None)

    # R38: شمارهٔ گزارشِ **بسته‌شده** و گزارش تازه صریح نوشته می‌شود
    # (قبلاً فقط شمارهٔ گزارش تازه دیده می‌شد و کاربر فکر می‌کرد همان
    # گزارش قبلی بسته شده).
    if new_id:
        text_out = Msg.REPORT_CLOSED_AND_REOPENED.format(
            old=report_id, new=new_id
        )
        toast = f"#{report_id} بسته شد؛ #{new_id} باز شد."
    else:
        text_out = Msg.REPORT_DETAIL_SAVED_SAME
        toast = Msg.REPORT_DETAIL_SAVED_SHORT

    try:
        await query.answer(toast)
    except TelegramError:
        pass

    try:
        await query.edit_message_text(text_out)
    except TelegramError:
        try:
            await context.bot.send_message(user_id, text_out)
        except TelegramError:
            pass

    await _notify_admins_report(
        context,
        new_id or report_id,
        draft,
        followup=True,
        closed_id=report_id if new_id else None,
    )
    return ConversationHandler.END


async def report_more_cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """R37: «❌ انصراف» — گزارش خودکار حل‌شده می‌شود و بسته می‌گردد."""
    query = update.callback_query
    if not query or not query.data:
        return ConversationHandler.END

    match = re.match(r"^report_more_cancel:(\d+)$", query.data)
    if not match:
        await query.answer()
        return ConversationHandler.END

    report_id = int(match.group(1))
    report = db.get_report_by_id(report_id)
    if not report:
        await query.answer(Msg.REPORT_NOT_FOUND, show_alert=True)
        return ConversationHandler.END

    caller = query.from_user
    if not caller or caller.id != report["user_id"]:
        await query.answer(Msg.REPORT_NOT_YOURS, show_alert=True)
        return ConversationHandler.END

    db.update_report_status(report_id, "resolved")
    context.user_data.pop("report_detail_id", None)
    context.user_data.pop("report_detail_draft", None)

    text = (
        "✅ گزارش شما بسته شد و به‌صورت «حل‌شده» علامت خورد.\n"
        "اگر بعداً مشکلی دیدی می‌توانی از همان لینک دوباره گزارش بدهی."
    )
    ok = False
    try:
        await query.edit_message_text(text)
        ok = True
    except TelegramError:
        pass
    if not ok:
        try:
            await context.bot.send_message(report["user_id"], text)
        except TelegramError:
            logger.debug("پیام بستن گزارش #%s نرسید", report_id)

    await query.answer("✅ گزارش بسته شد.")
    await _notify_admins_report(
        context, report_id, context.user_data.get("report_detail_draft"), cancelled=True
    )
    return ConversationHandler.END


async def _notify_admins_report(
    context: ContextTypes.DEFAULT_TYPE,
    report_id: int,
    text,
    followup: bool = False,
    cancelled: bool = False,
    closed_id: Optional[int] = None,
) -> None:
    """R37: اطلاع مالک/ادمین‌ها از توضیح تازه یا بسته‌شدن گزارش."""
    report = db.get_report_by_id(report_id)
    if not report:
        return
    if cancelled:
        note = f"❌ گزارش #{report_id} توسط گزارش‌دهنده بسته شد."
    elif followup:
        if closed_id:
            head = (
                f"📝 گزارش #{closed_id} بسته شد و گزارش #{report_id} "
                "با توضیح تازه باز شد."
            )
        else:
            head = f"📝 توضیح تازه برای گزارش #{report_id} ثبت شد."
        note = (
            f"{head}\n\n"
            f"{_report_details_text(report)}\n\n"
            f"— توضیح کاربر:\n{(text or '').strip()}"
        )
    else:
        return

    for admin_id in dict.fromkeys(
        [config.OWNER_ID] + list(config.ADMIN_IDS or [])
    ):
        if not admin_id:
            continue
        try:
            await context.bot.send_message(admin_id, note)
        except TelegramError:
            logger.debug("اطلاع گزارش به %s نرسید", admin_id)


async def receive_report_detail(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """R37: متن توضیح را **ذخیره نمی‌کند** — نگه می‌دارد تا «ثبت» بزند."""
    if not context.user_data.get("report_detail_id"):
        return ConversationHandler.END

    message = update.message
    if not message:
        return ConversationHandler.END

    text = (message.text or "").strip()[:1000]
    if not text:
        await message.reply_text(Msg.REPORT_DETAIL_EMPTY)
        return WAIT_REPORT_DETAIL

    context.user_data["report_detail_draft"] = text
    await message.reply_text(
        f"{Msg.REPORT_DETAIL_DRAFT_SAVED}\n\n"
        "برای ثبت نهایی دکمهٔ «✅ ثبت توضیح» را بزن.",
    )
    return WAIT_REPORT_DETAIL


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


async def cancel_report_detail(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """R35: خروج از حالت «توضیح دقیق‌تر» (دستور/لغو)."""
    context.user_data.pop("report_detail_id", None)
    context.user_data.pop("report_detail_msg", None)
    message = update.message
    if message:
        await message.reply_text(Msg.REPORT_CANCELLED)
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
