"""خلاصه داستان فصل (R10) — متن اجباری + عکس اختیاری؛ فقط در ربات ذخیره می‌شود."""

import html
import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ...config import config
from ...constants import (
    MANAGE_SUMMARY_PHOTO,
    MANAGE_SUMMARY_PHOTO_ID,
    MANAGE_SUMMARY_TEXT,
    Msg,
)
from ...database import db
from ...decorators import admin_only
from ...keyboards import ib
from ...services.delivery import send_summary_photo
from ...utils import (
    build_download_link,
    fmt_tehran,
    get_default_channel_chat_id,
    normalize_digits,
    safe_edit_or_send,
)
from .common import _level_state, _manage
from .refresh import _refresh_current

logger = logging.getLogger(__name__)

# محدودیت طول متن (پنل باید در ۴۰۹۶ نویسه تلگرام جا شود)
MAX_SUMMARY_LEN = 3700


def get_summary_photo_chats() -> list:
    """R34: فهرست کانال‌های عکس خلاصه (خالی ⇒ کانال فایل‌ها)."""
    chats = list(getattr(config, "SUMMARY_PHOTO_CHATS", None) or [])
    if not chats and getattr(config, "SUMMARY_PHOTO_CHAT", None):
        chats = [config.SUMMARY_PHOTO_CHAT]
    return chats


def _channel_choice_rows(chats: list) -> list:
    """R34: دکمهٔ هر کانال برای انتخاب هنگام ثبت عکس."""
    try:
        titles = db.get_setting("summary_photo_chat_titles", {}) or {}
    except Exception:
        titles = {}
    if not isinstance(titles, dict):
        titles = {}
    rows = []
    for chat in chats:
        label = titles.get(str(chat)) or str(chat)
        rows.append(
            [
                ib(
                    f"🖼️ {label}",
                    callback_data=f"mg_sum_ch:{int(chat)}",
                    style="primary",
                )
            ]
        )
    return rows


async def _ask_photo_id(context, manage, query, channel):
    """R34: پرامپت گرفتن آیدی/لینک پیام عکس از کانال انتخاب‌شده."""
    manage["summary_wait"] = "photo_id"
    manage["photo_chat"] = int(channel) if channel is not None else None
    context.user_data["manage"] = manage
    if channel is not None:
        where = f"کانال انتخاب‌شده: <code>{int(channel)}</code>"
    else:
        where = (
            "⚠️ کانالی ثبت نشده — فعلاً از 📁 کانال فایل‌ها استفاده "
            "می‌شود. برای کانال‌های دیگر: «⚙️ تنظیمات → 🖼️ کانال‌های "
            "عکس خلاصه»."
        )
    await query.edit_message_text(
        f"🖼️ {Msg.SUMMARY_PHOTO_ID_PROMPT}\n\n{where}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            [
                [ib("🔙 بازگشت به خلاصه", callback_data="mg_sum")]
            ]
        ),
    )
    return MANAGE_SUMMARY_PHOTO_ID


def _has_photo(summary: dict) -> bool:
    """R33: خلاصه عکس دارد؟ (کانالی یا file_id قدیمی)"""
    if not summary:
        return False
    if str(summary.get("photo_chat_id") or "").strip() and summary.get("photo_msg_id"):
        return True
    return bool(summary.get("photo_file_id"))


def _photo_state(summary: dict) -> str:
    """R33: وضعیت خوانا برای پنل خلاصه."""
    if not summary:
        return "❌ ندارد"
    if str(summary.get("photo_chat_id") or "").strip() and summary.get("photo_msg_id"):
        return (
            f"✅ از کانال <code>{summary['photo_chat_id']}</code> "
            f"(پیام {summary['photo_msg_id']})"
        )
    if summary.get("photo_file_id"):
        return "✅ دارد (file_id قدیمی)"
    return "❌ ندارد"


def parse_photo_ref(text: str, default_chat=None):
    """R33: «لینک پیام» یا «شمارهٔ پیام» ⇒ (chat_id, msg_id) یا None.

    پشتیبانی از:
      • https://t.me/<name>/123  و  https://t.me/c/1234567890/123
      • شمارهٔ خالص: 1245  ⇒ کانال پیش‌فرض
    """
    raw = normalize_digits((text or "").strip())
    if not raw:
        return None

    link = re.search(
        r"(?:t\.me|telegram\.me)/(?:c/)?([A-Za-z0-9_\-]+)/(\d+)",
        raw,
    )
    if link:
        target, msg_id = link.group(1), int(link.group(2))
        if target.lstrip("-").isdigit():
            chat = int(f"-100{target}")
        else:
            chat = f"@{target}"
        return chat, msg_id

    if re.fullmatch(r"\d+", raw) and default_chat:
        return int(default_chat), int(raw)

    return None


def _summary_ref(manage: dict) -> tuple:
    """(نام فیزیکی، فصل، پارت، برچسب نمایشی) از state مدیریت.

    B14: خلاصه داستان برای هر پارت جدا ثبت/خوانده می‌شود.
    """
    name = manage.get("name") or ""
    season = manage.get("season") or ""
    part = manage.get("part") or ""
    display = manage.get("display_name") or name
    if manage.get("is_cinema"):
        # R19c: سینماییِ بدون شماره ⇒ بدون «؟» (فقط «Movie»)
        label = (
            f"🎬 {display} — Movie {season}"
            if season
            else f"🎬 {display} — Movie"
        )
    else:
        label = f"🎬 {display} — فصل {season or '؟'}"
        if part:
            label += f" | پارت {part}"
    return name, season, part, label


def _usable_photo_id(photo):
    """R32: فایل‌آیدی امن‌ترین سایز عکس آپلودشده.

    اگر پیام به‌صورت «فایل» (document) فرستاده شده باشد، `photo` خالی
    است؛ در آن حالت None برمی‌گردد تا فایل‌آیدلی ذخیره نشود که بعداً
    با خطای «Wrong file identifier/http url specified» رد شود.
    """
    if not photo:
        return None
    sizes = [
        item
        for item in photo
        if isinstance(getattr(item, "file_id", None), str) and item.file_id
    ]
    if not sizes:
        return None
    return sizes[-1].file_id


async def _show_panel(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    manage: dict,
) -> int:
    """صفحه خلاصه (یا پرامپت اگر ثبت نشده) — روی همان پیام لیست ویرایش می‌شود."""
    name, season, part, label = _summary_ref(manage)
    summary = db.get_season_summary(name, season, part)
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
            "🖼️ عکس: " + _photo_state(summary),
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
        if _has_photo(summary):
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
    name, season, part, label = _summary_ref(manage)
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
        # R34: اگر چند کانال عکس ثبت شده باشد، اول کانال انتخاب می‌شود
        chats = get_summary_photo_chats()
        if len(chats) > 1:
            await query.edit_message_text(
                Msg.SUMMARY_PHOTO_PICK_CHANNEL,
                reply_markup=InlineKeyboardMarkup(
                    _channel_choice_rows(chats)
                    + [[ib("🔙 بازگشت به خلاصه", callback_data="mg_sum")]]
                ),
            )
            return origin
        return await _ask_photo_id(context, manage, query, chats[0] if chats else None)

    if data.startswith("mg_sum_ch:"):
        raw = data.split(":", 1)[1]
        try:
            channel = int(raw)
        except ValueError:
            channel = None
        if channel is None:
            await query.answer(Msg.SUMMARY_PHOTO_CHANNEL_INVALID, show_alert=True)
            return origin
        return await _ask_photo_id(context, manage, query, channel)

    if data == "mg_sum_show":
        summary = db.get_season_summary(name, season, part)
        if not summary or not _has_photo(summary):
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
            await send_summary_photo(
                context.bot,
                chat_id,
                summary,
                html.escape(caption) if caption else None,
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
        summary = db.get_season_summary(name, season, part)
        if not summary or not summary.get("photo_file_id"):
            await query.answer(
                "❌ عکسی ثبت نشده است.", show_alert=True
            )
            return await _show_panel(chat_id, context, manage)
        db.set_summary_photo(summary.get("id"), None, None, None)
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
        if db.delete_season_summary(name, season, part):
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

    name, _season, _part, _label = _summary_ref(manage)
    if not name:
        await update.message.reply_text("❌ فصلی انتخاب نشده است.")
        return _level_state(manage)

    if len(text) > MAX_SUMMARY_LEN:
        await update.message.reply_text(
            f"❌ متن خیلی طولانی است (حداکثر {MAX_SUMMARY_LEN} نویسه).\n"
            "کوتاه‌ترش کن و دوباره بفرست."
        )
        return MANAGE_SUMMARY_TEXT

    current = db.get_season_summary(name, _season, _part)
    db.set_season_summary(
        name,
        _season,
        text,
        photo_file_id=(current or {}).get("photo_file_id"),
        created_by=update.effective_user.id,
        part_num=_part,
    )
    manage.pop("summary_wait", None)
    context.user_data["manage"] = manage
    # لینک اشتراک‌گذاری مثل لینک‌های آپلود (برای ارسال خلاصه به کاربران)
    saved = db.get_season_summary(name, _season, _part)
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

    name, _season, _part, _label = _summary_ref(manage)
    current = db.get_season_summary(name, _season, _part)
    if not current:
        await update.message.reply_text(
            "❌ اول متن خلاصه را ثبت کن، بعد عکس را بفرست."
        )
        return await _show_panel(chat_id, context, manage)

    file_id = _usable_photo_id(update.message.photo)
    if not file_id:
        await update.message.reply_text(
            "❌ این عکس قابل استفاده نیست؛ آن را دوباره (به صورت عکس، "
            "نه فایل) بفرست."
        )
        return MANAGE_SUMMARY_PHOTO
    # R33: عکس کانالی اولویت دارد و file_id قدیمی پاک می‌شود
    db.set_summary_photo(current.get("id"), None, None, file_id)
    manage.pop("summary_wait", None)
    context.user_data["manage"] = manage
    await update.message.reply_text("✅ عکس خلاصه ذخیره شد.")
    return await _show_panel(chat_id, context, manage)


@admin_only
async def handle_summary_photo_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """R33: دریافت «لینک پیام» یا «شمارهٔ پیام» عکس خلاصه در کانال.

    عکس با کپی از کانال ارسال می‌شود؛ بنابراین با عوض‌شدن توکن ربات هم
    تا وقتی ربات عضو آن کانال باشد کار می‌کند.
    """
    manage = _manage(context)
    message = update.message
    chat_id = message.chat_id
    name, _season, _part, _label = _summary_ref(manage)

    current = db.get_season_summary(name, _season, _part)
    if not current:
        await message.reply_text(
            "❌ اول متن خلاصه را ثبت کن، بعد عکس را وصل کن."
        )
        return await _show_panel(chat_id, context, manage)

    default_chat = (
        manage.get("photo_chat")
        or config.SUMMARY_PHOTO_CHAT
        or get_default_channel_chat_id()
    )
    ref = parse_photo_ref(message.text or "", default_chat)
    if ref is None:
        await message.reply_text(Msg.SUMMARY_PHOTO_ID_INVALID)
        return MANAGE_SUMMARY_PHOTO_ID

    photo_chat, photo_msg = ref
    if photo_chat is None:
        await message.reply_text(Msg.SUMMARY_PHOTO_CHANNEL_MISSING)
        return MANAGE_SUMMARY_PHOTO_ID

    # اگر کانال با @username داده شده، به آیدی عددی تبدیل می‌شود
    if isinstance(photo_chat, str):
        try:
            resolved = await context.bot.get_chat(photo_chat)
        except TelegramError as err:
            logger.warning("کانال عکس %s شناسایی نشد: %s", photo_chat, err)
            await message.reply_text(Msg.CHANNEL_CHECK_FAILED)
            return MANAGE_SUMMARY_PHOTO_ID
        photo_chat = resolved.id

    # اعتبارسنجی: همان پیام واقعاً عکس دارد و ربات می‌تواند کپی کند
    try:
        await context.bot.copy_message(
            chat_id=chat_id,
            from_chat_id=photo_chat,
            message_id=photo_msg,
        )
    except TelegramError as err:
        logger.warning(
            "کپی آزمایشی عکس خلاصه %s/%s ناموفق: %s",
            photo_chat,
            photo_msg,
            err,
        )
        await message.reply_text(
            "❌ این پیام قابل کپی نیست (عکس نیست یا ربات دسترسی ندارد).\n"
            "آیدی یا لینک دیگری بفرست."
        )
        return MANAGE_SUMMARY_PHOTO_ID

    db.set_summary_photo(
        current.get("id"), photo_chat, photo_msg, photo_file_id=None
    )
    manage.pop("summary_wait", None)
    manage.pop("photo_chat", None)
    context.user_data["manage"] = manage
    await message.reply_text(Msg.SUMMARY_PHOTO_SET)
    return await _show_panel(chat_id, context, manage)
