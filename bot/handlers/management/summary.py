"""خلاصه داستان فصل (R10) — متن اجباری + عکس اختیاری؛ فقط در ربات ذخیره می‌شود."""

import html
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ...constants import (
    MANAGE_SUMMARY_PHOTO,
    MANAGE_SUMMARY_TEXT,
)
from ...database import db
from ...decorators import admin_only
from ...keyboards import ib
from ...utils import (
    build_download_link,
    fmt_tehran,
    safe_edit_or_send,
)
from .common import _level_state, _manage
from .refresh import _refresh_current

logger = logging.getLogger(__name__)

# محدودیت طول متن (پنل باید در ۴۰۹۶ نویسه تلگرام جا شود)
MAX_SUMMARY_LEN = 3700


def _summary_ref(manage: dict) -> tuple:
    """(نام فیزیکی، شماره فصل، برچسب نمایشی) از state مدیریت."""
    name = manage.get("name") or ""
    season = manage.get("season") or ""
    display = manage.get("display_name") or name
    if manage.get("is_cinema"):
        label = f"🎬 {display} — Movie {season or '؟'}"
    else:
        label = f"🎬 {display} — فصل {season or '؟'}"
    return name, season, label


async def _show_panel(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    manage: dict,
) -> int:
    """صفحه خلاصه (یا پرامپت اگر ثبت نشده) — روی همان پیام لیست ویرایش می‌شود."""
    name, season, label = _summary_ref(manage)
    summary = db.get_season_summary(name, season)
    origin = _level_state(manage)

    if not summary:
        text = (
            f"📝 خلاصه داستان — {html.escape(label)}\n\n"
            "هنوز خلاصه‌ای ثبت نشده است.\n"
            "متن خلاصه داستان این فصل را بفرست."
        )
        keyboard = [
            [ib("◀️ بازگشت", callback_data="mg_back")]
        ]
        new_state = MANAGE_SUMMARY_TEXT
    else:
        # لینک اشتراک‌گذاری مثل لینک‌های آپلود — sm<id>؛ آیدی با upsert ثابت می‌ماند
        try:
            share_link = await build_download_link(
                context, f"sm{summary.get('id')}"
            )
        except Exception:
            logger.exception("خطا در ساخت لینک خلاصه %s", name)
            share_link = ""
        lines = [
            f"📝 خلاصه داستان — {html.escape(label)}",
            "",
            html.escape(summary.get("summary_text") or ""),
            "",
            "🖼️ عکس: "
            + ("✅ دارد" if summary.get("photo_file_id") else "❌ ندارد"),
            f"📅 به‌روزرسانی: {fmt_tehran(summary.get('updated_at'))}",
        ]
        if share_link:
            # B2: لینک mono (code) ⇒ با یک ضربه کپی می‌شود
            lines += [
                "",
                "🔗 لینک اشتراک‌گذاری:",
                f"<code>{share_link}</code>",
            ]
        text = "\n".join(lines)
        keyboard = [
            [
                ib(
                    "✏️ ویرایش متن", callback_data="mg_sum_edit"
                ),
                ib(
                    "🖼️ تغییر عکس", callback_data="mg_sum_photo"
                ),
            ]
        ]
        if summary.get("photo_file_id"):
            keyboard.append(
                [
                    ib(
                        "👁️ نمایش عکس", callback_data="mg_sum_show"
                    ),
                    ib(
                        "🗑 حذف عکس", callback_data="mg_sum_del_photo"
                    ),
                ]
            )
        keyboard.append(
            [
                ib(
                    "🗑️ حذف خلاصه", callback_data="mg_sum_del"
                )
            ]
        )
        keyboard.append(
            [ib("◀️ بازگشت", callback_data="mg_back")]
        )
        new_state = origin

    markup = InlineKeyboardMarkup(keyboard)
    msg_id = manage.get("list_message_id")
    new_id = await safe_edit_or_send(
        context, chat_id, text, markup, msg_id, parse_mode="HTML"
    )
    manage["list_message_id"] = new_id
    manage.pop("summary_wait", None)
    context.user_data["manage"] = manage
    return new_state


async def handle_summary_callback(
    context: ContextTypes.DEFAULT_TYPE,
    manage: dict,
    query,
    data: str,
) -> int:
    """شاخه‌های callback خلاصه داستان (از dispatch فراخوانی می‌شود)."""
    chat_id = query.message.chat_id if query.message else query.from_user.id
    name, season, label = _summary_ref(manage)
    origin = _level_state(manage)

    if data == "mg_sum":
        return await _show_panel(chat_id, context, manage)

    if data == "mg_sum_edit":
        manage["summary_wait"] = "text"
        context.user_data["manage"] = manage
        await query.edit_message_text(
            f"✏️ متن جدید خلاصه داستان را بفرست:\n\n{label}\n\n"
            f"حداکثر {MAX_SUMMARY_LEN} نویسه.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        ib(
                            "🔙 بازگشت به خلاصه",
                            callback_data="mg_sum",
                        )
                    ]
                ]
            ),
        )
        return MANAGE_SUMMARY_TEXT

    if data == "mg_sum_photo":
        manage["summary_wait"] = "photo"
        context.user_data["manage"] = manage
        await query.edit_message_text(
            f"🖼️ عکس خلاصه (پوستر فصل) را بفرست:\n\n{label}\n\n"
            "عکس جایگزین عکس قبلی می‌شود.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        ib(
                            "🔙 بازگشت به خلاصه",
                            callback_data="mg_sum",
                        )
                    ]
                ]
            ),
        )
        return MANAGE_SUMMARY_PHOTO

    if data == "mg_sum_show":
        summary = db.get_season_summary(name, season)
        file_id = summary.get("photo_file_id") if summary else None
        if not file_id:
            await query.answer(
                "❌ عکسی ثبت نشده است.", show_alert=True
            )
            return origin
        body = summary.get("summary_text") or ""
        caption = None
        if body:
            caption = body[:1000]
            if len(body) > 1000:
                caption += "…"
        try:
            await context.bot.send_photo(
                chat_id=chat_id, photo=file_id, caption=caption
            )
        except Exception:
            logger.warning("ارسال عکس خلاصه ناموفق بود", exc_info=True)
            await query.answer(
                "❌ عکس قابل ارسال نیست؛ دوباره آپلود کن.",
                show_alert=True,
            )
            return origin
        await query.answer()
        return origin

    if data == "mg_sum_del_photo":
        summary = db.get_season_summary(name, season)
        if not summary or not summary.get("photo_file_id"):
            await query.answer(
                "❌ عکسی ثبت نشده است.", show_alert=True
            )
            return await _show_panel(chat_id, context, manage)
        db.set_season_summary(
            name,
            season,
            summary.get("summary_text") or "",
            photo_file_id=None,
            created_by=summary.get("created_by"),
        )
        await query.answer("🖼️ عکس حذف شد؛ متن خلاصه باقی است.")
        return await _show_panel(chat_id, context, manage)

    if data == "mg_sum_del":
        await query.edit_message_text(
            f"🗑️ خلاصه داستان این فصل حذف شود؟\n\n{label}",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        ib(
                            "✅ بله، حذف کن",
                            callback_data="mg_sum_del_yes",
                        ),
                        ib(
                            "❌ خیر",
                            callback_data="mg_sum",
                        ),
                    ]
                ]
            ),
        )
        return origin

    if data == "mg_sum_del_yes":
        if db.delete_season_summary(name, season):
            await query.answer("✅ خلاصه داستان حذف شد.")
        else:
            await query.answer("❌ رکوردی برای حذف نبود.")
        return await _refresh_current(chat_id, context, manage)

    return origin


@admin_only
async def handle_summary_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """گیرنده متن خلاصه (state انتظار متن) + راهنمای عکس در state عکس."""
    manage = _manage(context)
    text = update.message.text.strip()
    chat_id = update.message.chat_id

    if manage.get("summary_wait") == "photo":
        await update.message.reply_text(
            "🖼️ لطفاً یک عکس بفرست "
            "(یا با دکمه «🔙 بازگشت به خلاصه» برگرد)."
        )
        return MANAGE_SUMMARY_PHOTO

    name, _season, _label = _summary_ref(manage)
    if not name:
        await update.message.reply_text("❌ فصلی انتخاب نشده است.")
        return _level_state(manage)

    if len(text) > MAX_SUMMARY_LEN:
        await update.message.reply_text(
            f"❌ متن خیلی طولانی است (حداکثر {MAX_SUMMARY_LEN} نویسه).\n"
            "کوتاه‌ترش کن و دوباره بفرست."
        )
        return MANAGE_SUMMARY_TEXT

    current = db.get_season_summary(name, _season)
    db.set_season_summary(
        name,
        _season,
        text,
        photo_file_id=(current or {}).get("photo_file_id"),
        created_by=update.effective_user.id,
    )
    manage.pop("summary_wait", None)
    context.user_data["manage"] = manage
    # لینک اشتراک‌گذاری مثل لینک‌های آپلود (برای ارسال خلاصه به کاربران)
    saved = db.get_season_summary(name, _season)
    reply = "✅ خلاصه داستان ذخیره شد."
    if saved and saved.get("id"):
        try:
            share_link = await build_download_link(
                context, f"sm{saved['id']}"
            )
            # B2: لینک mono (code) ⇒ با یک ضربه کپی می‌شود
            reply += (
                "\n🔗 لینک اشتراک‌گذاری:"
                f"\n<code>{share_link}</code>"
            )
        except Exception:
            logger.exception("خطا در ساخت لینک خلاصه %s", name)
    await update.message.reply_text(reply, parse_mode="HTML")
    return await _show_panel(chat_id, context, manage)


@admin_only
async def handle_summary_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """گیرنده عکس خلاصه (state انتظار عکس)."""
    manage = _manage(context)
    chat_id = update.message.chat_id

    if not update.message.photo:
        await update.message.reply_text(
            "❌ پیام عکس نبود؛ دوباره تلاش کن."
        )
        return MANAGE_SUMMARY_PHOTO

    name, _season, _label = _summary_ref(manage)
    current = db.get_season_summary(name, _season)
    if not current:
        await update.message.reply_text(
            "❌ اول متن خلاصه را ثبت کن، بعد عکس را بفرست."
        )
        return await _show_panel(chat_id, context, manage)

    file_id = update.message.photo[-1].file_id
    db.set_season_summary(
        name,
        _season,
        current.get("summary_text") or "",
        photo_file_id=file_id,
        created_by=current.get("created_by") or update.effective_user.id,
    )
    manage.pop("summary_wait", None)
    context.user_data["manage"] = manage
    await update.message.reply_text("✅ عکس خلاصه ذخیره شد.")
    return await _show_panel(chat_id, context, manage)
