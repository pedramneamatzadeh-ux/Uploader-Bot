"""متون پنل، هلپرها و لغو گفتگوی تنظیمات."""

import logging
import re
from typing import Optional

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes, ConversationHandler

from ...config import config
from ...constants import (
    BOT_VERSION,
    BOT_VERSION_DATE,
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

logger = logging.getLogger(__name__)

_MAX_DURATION_SECONDS = 2592000

_CANCEL_TEXTS = ("لغو", "بازگشت به منوی اصلی")


# سقف مدت حذف: 30 روز
# ============================================================================
# نماها (متن + کیبورد هر صفحه)
# ============================================================================
def _human_duration(seconds) -> str:
    if seconds is None:
        return "تنظیم نشده"
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return "نامشخص"

    if seconds >= 86400 and seconds % 86400 == 0:
        return f"{seconds} ثانیه ({seconds // 86400} روز)"
    if seconds >= 3600 and seconds % 3600 == 0:
        return f"{seconds} ثانیه ({seconds // 3600} ساعت)"
    if seconds >= 60 and seconds % 60 == 0:
        return f"{seconds} ثانیه ({seconds // 60} دقیقه)"
    return f"{seconds} ثانیه"


def _panel_text() -> str:
    owner_id = config.OWNER_ID
    admins = [
        item for item in (config.ADMIN_IDS or []) if item != owner_id
    ]
    channels = config.REQUIRED_CHANNELS or []
    databases = db.get_custom_databases()

    return "\n".join(
        [
            Msg.SETTINGS_TITLE,
            "",
            f"👨‍💼 ادمین‌ها: {len(admins)} نفر (به‌علاوه مالک 👑)",
            f"📢 کانال‌های اجباری: {len(channels)}",
            f"⏱ حذف فایل‌های آپلود: "
            f"{_human_duration(config.delete_seconds('files'))}",
            f"⏱ حذف پست‌ها: "
            f"{_human_duration(config.delete_seconds('posts'))}",
            f"⏱ حذف خلاصه داستان: "
            f"{_human_duration(config.delete_seconds('summary'))}",
            f"⏱ حذف پنل لینک فصل: "
            f"{_human_duration(config.delete_seconds('panel'))}",
            "🖼️ کانال‌های عکس خلاصه: "
            + (
                f"{len(_photo_channels())} کانال"
                if _photo_channels()
                else "کانال فایل‌ها"
            ),
            f"🗄️ دیتابیس‌های سفارشی: {len(databases)}",
            f"🧩 نسخه: {BOT_VERSION} ({BOT_VERSION_DATE})",
        ]
    )


def _user_names() -> dict:
    """R23: نگاشت user_id → نام نمایشی برای دو ستون پنل ادمین‌ها."""
    names = {}
    try:
        for row in db.get_all_users():
            display = " ".join(
                part
                for part in (
                    row.get("first_name") or "",
                    row.get("last_name") or "",
                )
                if part
            ).strip()
            if not display:
                display = row.get("username") or ""
            if display:
                names[int(row["user_id"])] = display
    except Exception:  # نگاشت نام‌ها هرگز نباید پنل را بشکند
        logger.debug("خواندن نام کاربران ناموفق بود", exc_info=True)
    return names


def _admin_names() -> dict:
    names = _user_names()
    owner = config.OWNER_ID
    if owner in names:
        names[owner] = f"{names[owner]} 👑"
    return names


def _channel_titles() -> dict:
    """R23: عنوان کانال‌ها که هنگام افزودن ذخیره شده است (id → title)."""
    try:
        stored = db.get_setting("required_channel_titles", {}) or {}
    except Exception:
        logger.debug("خواندن عنوان کانال‌ها ناموفق بود", exc_info=True)
        return {}
    if not isinstance(stored, dict):
        return {}
    return {str(key): value for key, value in stored.items()}


async def ensure_channel_titles(context) -> dict:
    """R23b: عنوان کانال‌هایی که قبلاً اضافه شده‌اند ولی عنوانشان ذخیره
    نشده را یک‌بار با get_chat می‌گیرد و ذخیره می‌کند.

    اگر ربات به کانال دسترسی نداشت، همان مقدار قبلی (بدون عنوان) می‌ماند.
    هرگز استثنا نمی‌دهد.
    """
    try:
        titles = dict(_channel_titles())
    except Exception:
        return {}

    changed = False
    for channel in (config.REQUIRED_CHANNELS or []):
        key = str(channel)
        if key in titles and titles[key]:
            continue
        if not key.lstrip("-").isdigit():
            continue  # یوزرنیم: خودش نام است
        try:
            chat = await context.bot.get_chat(int(key))
        except Exception:
            logger.debug(
                "گرفتن عنوان کانال %s ناموفق بود", key, exc_info=True
            )
            continue
        title = getattr(chat, "title", None) or getattr(chat, "username", None)
        if title:
            titles[key] = title
            changed = True

    if changed:
        try:
            db.set_setting("required_channel_titles", titles)
        except Exception:
            logger.debug("ذخیرهٔ عنوان کانال‌ها ناموفق بود", exc_info=True)
    return titles


def _admins_text() -> str:
    # R23: دو ستون — راست اسم اکانت، چپ آیدی عددی
    owner_id = config.OWNER_ID
    names = _user_names()
    lines = ["👨‍💼 ادمین‌ها", ""]

    if owner_id is not None:
        owner_name = names.get(owner_id) or "—"
        lines.append(f"👑 {owner_name} — {owner_id} (مالک، ثابت)")

    others = [
        item for item in (config.ADMIN_IDS or []) if item != owner_id
    ]
    if others:
        lines.extend(
            f"👤 {names.get(int(item)) or '—'} — {item}"
            for item in others
        )
    else:
        lines.append("— ادمین دیگری ثبت نشده است")

    return "\n".join(lines)


def _channels_text() -> str:
    # R23: دو ستون — راست اسم کانال، چپ آیدی عددی
    channels = config.REQUIRED_CHANNELS or []
    titles = _channel_titles()
    lines = ["📢 کانال‌های اجباری عضویت", ""]

    if not channels:
        lines.append("— کانالی ثبت نشده است")
    else:
        for channel in channels:
            key = str(channel)
            if key.lstrip("-").isdigit():
                name = titles.get(key) or "—"
                lines.append(f"📢 {name} — {key}")
            else:
                lines.append(f"📢 {key} — (یوزرنیم)")
    return "\n".join(lines)


# R27: سه هدف زمانی مستقل
DURATION_KINDS = {
    "files": "📁 فایل‌های آپلود",
    "posts": "📝 پست‌های کانال",
    "summary": "🧧 خلاصه داستان",
    "panel": "📋 پنل لینک فصل (کیفیت/قسمت)",
}

# R28: کلید settings هر هدف
DURATION_SETTING_ATTRS = {
    "files": "DELETE_AFTER_SECONDS",
    "posts": "DELETE_AFTER_SECONDS_POSTS",
    "summary": "DELETE_AFTER_SECONDS_SUMMARY",
    "panel": "DELETE_AFTER_SECONDS_PANEL",
}


def _duration_text(kind: str = "files") -> str:
    value = config.delete_seconds(kind)
    lines = [
        "⏱ مدت حذف خودکار پیام‌ها",
        "",
        f"هدف: {DURATION_KINDS.get(kind, DURATION_KINDS['files'])}",
        f"فعلی: {_human_duration(value)}",
    ]

    if kind != "files":
        base = config.delete_seconds("files")
        attr = DURATION_SETTING_ATTRS.get(kind, "DELETE_AFTER_SECONDS_POSTS")
        if getattr(config, attr, None) is None:
            lines.append(
                f"(تنظیم نشده ⇒ از «فایل‌های آپلود» استفاده می‌شود: "
                f"{_human_duration(base)})"
            )

    return "\n".join(lines)


def _photo_channels() -> list:
    """R34: لیست کانال‌های عکس خلاصه (خالی ⇒ کانال فایل‌ها)."""
    chats = list(getattr(config, "SUMMARY_PHOTO_CHATS", None) or [])
    if not chats and getattr(config, "SUMMARY_PHOTO_CHAT", None):
        chats = [config.SUMMARY_PHOTO_CHAT]
    return chats


def _photo_channel_titles() -> dict:
    """R34: عنوان ذخیره‌شدهٔ کانال‌های عکس (id → title)."""
    try:
        stored = db.get_setting("summary_photo_chat_titles", {}) or {}
    except Exception:
        logger.debug("خواندن عنوان کانال‌های عکس ناموفق بود", exc_info=True)
        return {}
    if not isinstance(stored, dict):
        return {}
    return {str(key): value for key, value in stored.items()}


def _summary_photo_chat_text() -> str:
    """R34: متن پنل «کانال‌های عکس خلاصه» (چند کانال، مثل ادمین‌ها)."""
    chats = _photo_channels()
    titles = _photo_channel_titles()
    lines = ["🖼️ کانال‌های عکس خلاصه داستان", ""]

    if not chats:
        lines.append(
            "❌ کانالی ثبت نشده ⇒ عکس‌ها از 📁 کانال فایل‌ها "
            "(DATABASES[0]) کپی می‌شوند."
        )
    else:
        for chat in chats:
            title = titles.get(str(chat))
            if title:
                lines.append(f"🖼️ {title} — <code>{chat}</code>")
            else:
                lines.append(f"🖼️ <code>{chat}</code>")

    lines += [
        "",
        "عکس خلاصه‌ها با «کپی از کانال» ارسال می‌شوند؛ پس حتی اگر "
        "توکن ربات عوض شود، تا وقتی ربات عضو این کانال باشد عکس‌ها "
        "کار می‌کنند.",
        "🔸 آیدی عددی (مثل <code>-1001234567890</code>) یا @username "
        "را بفرست، یا یک پیام از آن کانال را فوروارد کن. چند کانال "
        "هم می‌توانی اضافه کنی.",
    ]
    return "\n".join(lines)


def _save_photo_channels(chats: list) -> None:
    """R34: ذخیرهٔ فهرست کانال‌های عکس خلاصه (هم settings و هم config)."""
    clean = []
    for chat in chats:
        try:
            value = int(chat)
        except (TypeError, ValueError):
            continue
        if value not in clean:
            clean.append(value)
    config.SUMMARY_PHOTO_CHATS = clean
    config.SUMMARY_PHOTO_CHAT = clean[0] if clean else None
    db.set_setting("summary_photo_chats", clean)


async def ensure_summary_photo_titles(context) -> dict:
    """R34: عنوان کانال‌های عکس را (در صورت نبود) از تلگرام می‌گیرد."""
    titles = dict(_photo_channel_titles())
    changed = False
    for chat in _photo_channels():
        key = str(chat)
        if titles.get(key):
            continue
        try:
            info = await context.bot.get_chat(int(chat))
        except Exception:
            logger.debug("گرفتن عنوان کانال عکس %s ناموفق بود", key,
                         exc_info=True)
            continue
        title = getattr(info, "title", None) or getattr(info, "username", None)
        if title:
            titles[key] = title
            changed = True
    if changed:
        try:
            db.set_setting("summary_photo_chat_titles", titles)
        except Exception:
            logger.debug("ذخیرهٔ عنوان کانال‌های عکس ناموفق بود",
                         exc_info=True)
    return titles


def _photo_channel_label(chat) -> str:
    """R34: برچسب کوتاه یک کانال عکس برای دکمه‌ها/متن‌ها."""
    title = _photo_channel_titles().get(str(chat))
    if title:
        return title
    text = str(chat)
    return f"کانال {text}" if not text.lstrip("-").isdigit() else text


def _dbs_text() -> str:
    databases = db.get_custom_databases()
    lines = ["🗄️ دیتابیس‌های سفارشی", ""]

    if not databases:
        lines.append("— دیتابیس سفارشی ثبت نشده است")
    else:
        lines.extend(
            f"❌ {row['name']} — {row['chat_id']}" for row in databases
        )

    return "\n".join(lines)


# ============================================================================
# ابزارهای داخلی
# ============================================================================
async def _safe_edit(query, text: str, reply_markup) -> None:
    """ویرایش پیام callback؛ در صورت شکست (پیام قدیمی) پیام تازه می‌فرستد."""
    try:
        await query.edit_message_text(text, reply_markup=reply_markup)
        return
    except TelegramError as err:
        if "not modified" in str(err).lower():
            return
        logger.debug("ویرایش پیام پنل ناموفق: %s", err)

    if not query.message:
        return
    try:
        await query.message.reply_text(text, reply_markup=reply_markup)
    except TelegramError:
        logger.debug("ارسال پیام پنل ناموفق", exc_info=True)


async def _edit_by_id(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id,
    message_id,
    text: str,
    reply_markup=None,
) -> None:
    if chat_id is None or message_id is None:
        return
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
        )
    except TelegramError as err:
        if "not modified" not in str(err).lower():
            logger.debug("ویرایش پیام ورودی ناموفق: %s", err)


def _store_prompt(
    context: ContextTypes.DEFAULT_TYPE,
    query,
) -> None:
    if query.message:
        context.user_data["st_msg"] = query.message.message_id
        context.user_data["st_chat"] = query.message.chat_id


async def _show_prompt(
    context: ContextTypes.DEFAULT_TYPE,
    query,
    prompt_text: str,
) -> None:
    _store_prompt(context, query)
    await _safe_edit(query, prompt_text, settings_input_keyboard())


async def _retry_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    error_text: str,
    prompt_text: str,
) -> None:
    """نمایش خطا روی همان پیام ورودی (بدون از دست رفتن فلو)."""
    full = f"{error_text}\n\n{prompt_text}"
    chat_id = context.user_data.get("st_chat")
    message_id = context.user_data.get("st_msg")
    markup = settings_input_keyboard()

    if chat_id is not None and message_id is not None:
        await _edit_by_id(context, chat_id, message_id, full, markup)
        return

    if update.message:
        await update.message.reply_text(full, reply_markup=markup)


async def _show_section(
    context: ContextTypes.DEFAULT_TYPE,
    query,
    text: str,
    reply_markup,
) -> int:
    """به‌روزرسانی پیام جاری با یک صفحه section و ماندن در PANEL."""
    if query and query.message:
        _store_prompt(context, query)
        await _safe_edit(query, text, reply_markup)
    return SETTINGS_PANEL


def _forwarded_user_id(message) -> Optional[int]:
    origin = getattr(message, "forward_origin", None)
    if origin is not None:
        user = getattr(origin, "sender_user", None)
        if user is not None:
            return user.id
    if getattr(message, "forward_from", None) is not None:
        return message.forward_from.id
    return None


def _resolve_chat_target(message):
    """شناسه عددی / @username مقصد را از فوروارد یا متن استخراج می‌کند."""
    origin = getattr(message, "forward_origin", None)
    if origin is not None:
        chat = getattr(origin, "chat", None)
        if chat is not None:
            return chat.id

    if getattr(message, "forward_from_chat", None) is not None:
        return message.forward_from_chat.id

    text = normalize_digits((message.text or "").strip())
    if text.startswith("@") and len(text) > 1:
        return text
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return None


async def _precheck_chat(context: ContextTypes.DEFAULT_TYPE, target):
    """پیش‌چک P14: کانال قابل دسترس باشد و ربات در آن ادمین باشد.

    خروجی: (chat_id یا None, متن خطا یا None)
    """
    try:
        chat = await context.bot.get_chat(target)
    except TelegramError:
        return None, Msg.CHANNEL_CHECK_FAILED

    if chat.type not in ("channel", "supergroup", "group"):
        return None, Msg.CHANNEL_INVALID

    try:
        member = await context.bot.get_chat_member(chat.id, context.bot.id)
    except TelegramError:
        return None, Msg.CHANNEL_CHECK_FAILED

    if member.status not in ("administrator", "creator"):
        return None, Msg.CHANNEL_BOT_NOT_ADMIN

    return chat.id, None


async def _handle_text_cancel(update: Update, context):
    """لغو با متن ساده داخل stateهای ورودی (الگوی بقیه گفتگوها)."""
    if not update.message:
        return None
    text = (update.message.text or "").strip()
    if text in _CANCEL_TEXTS:
        return await cancel_settings(update, context)
    return None


@owner_only
async def cancel_settings(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    context.user_data.pop("st_new_db", None)

    chat_id = context.user_data.pop("st_chat", None)
    message_id = context.user_data.pop("st_msg", None)
    if chat_id is not None and message_id is not None:
        await _edit_by_id(
            context, chat_id, message_id, Msg.SETTINGS_CLOSED
        )

    if update.message:
        await update.message.reply_text(
            Msg.MAIN_MENU_PROMPT,
            reply_markup=main_menu_for(update.effective_user.id),
        )
    return ConversationHandler.END
