import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple, Union
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from .config import config
from .constants import Msg
from .database import db
from .keyboards import ONGOING_MENU_MARKUP, main_menu_for


logger = logging.getLogger(__name__)


# تبدیل ارقام فارسی/عربی به انگلیسی (مرحله ۳ — R1)
_DIGIT_TRANSLATION = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)


def normalize_digits(text: Optional[str]) -> str:
    """ارقام فارسی/عربی متن را به ارقام انگلیسی تبدیل می‌کند."""
    return (text or "").translate(_DIGIT_TRANSLATION)


def validate_anime_name(text: Optional[str]) -> Tuple[bool, str]:
    """نام انیمه باید انگلیسی باشد (حروف فارسی/عربی و ارقام فارسی ممنوع)."""
    clean_text = (text or "").strip()

    if not clean_text:
        return False, "نام انیمه نمی‌تواند خالی باشد."

    if re.search(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]", clean_text):
        return (
            False,
            "نام انیمه باید انگلیسی باشد؛ حروف فارسی/عربی و ارقام "
            "فارسی مجاز نیستند. مثال صحیح: Frieren",
        )

    if not re.search(r"[A-Za-z]", clean_text):
        return (
            False,
            "نام انیمه باید حداقل یک حرف انگلیسی داشته باشد.",
        )

    return True, ""


def build_channel_join_url(
    identifier: Union[int, str],
) -> Optional[str]:
    if (
        isinstance(identifier, str)
        and identifier.startswith("@")
        and len(identifier) > 1
    ):
        return f"https://t.me/{identifier[1:]}"

    return None


def channel_display_name(identifier: Union[int, str]) -> str:
    if isinstance(identifier, str) and identifier.startswith("@"):
        return identifier

    return f"کانال ({identifier})"


def is_member_status(chat_member: Any) -> bool:
    try:
        if chat_member.status in (
            "member",
            "administrator",
            "creator",
        ):
            return True

        if getattr(chat_member, "is_member", False):
            return True
    except Exception:
        pass

    return False


def parse_range(rng: Optional[str]) -> Optional[Tuple[int, int]]:
    if not rng:
        return None

    clean_range = normalize_digits(rng.strip())

    if clean_range.isdigit():
        value = int(clean_range)
        if value <= 0:
            return None
        return value, value

    if "-" not in clean_range:
        return None

    part_a, part_b = (
        part.strip() for part in clean_range.split("-", 1)
    )

    if not (part_a.isdigit() and part_b.isdigit()):
        return None

    start, end = int(part_a), int(part_b)

    if start <= 0 or end <= 0 or end < start:
        return None

    return start, end


def validate_episode_input(text: Optional[str]) -> Tuple[bool, str]:
    clean_text = normalize_digits((text or "").strip())

    if not clean_text:
        return False, "قسمت نمی‌تواند خالی باشد."

    if "-" in clean_text:
        parts = clean_text.split("-")
        if len(parts) != 2 or not (
            parts[0].strip().isdigit() and parts[1].strip().isdigit()
        ):
            return (
                False,
                "فرمت محدوده نامعتبر است. مثال صحیح: 1-12",
            )

        start, end = int(parts[0]), int(parts[1])
        if start <= 0 or end <= 0 or end < start:
            return False, "محدوده قسمت نامعتبر است."

    elif not clean_text.isdigit():
        return (
            False,
            "فرمت قسمت نامعتبر است. فقط عدد یا محدوده عددی وارد کن.",
        )

    return True, ""


def validate_channel_input(text: Optional[str]) -> Tuple[bool, str]:
    if parse_range(text or "") is None:
        return (
            False,
            "فرمت نامعتبر است. مثال صحیح: 100-110 یا 100",
        )

    return True, ""


def normalize_optional_text(text: Optional[str]) -> str:
    clean_text = (text or "").strip()

    if clean_text in ("-", "ندارد", "ندارد ➖", "هیچ", "خالی"):
        return ""

    return clean_text


def get_default_channel_chat_id() -> Optional[int]:
    if config.DATABASES:
        return config.DATABASES[0]["chat_id"]

    return None


def get_database_name(chat_id: Any) -> str:
    if chat_id is None or chat_id == "":
        if config.DATABASES:
            return config.DATABASES[0]["name"]
        return "نامشخص"

    try:
        cid = int(chat_id)
    except (TypeError, ValueError):
        return "نامشخص"

    for database in config.DATABASES:
        if database["chat_id"] == cid:
            return database["name"]

    return f"ناشناس ({cid})"


# ---------------------------------------------------------------------------
# نمایش تاریخ/ساعت به وقت تهران (مرحله ۵ — R6)
# ذخیره‌سازی UTC می‌ماند؛ فقط هنگام نمایش تبدیل انجام می‌شود.
# ---------------------------------------------------------------------------

_TEHRAN_TZ = ZoneInfo("Asia/Tehran")


def _gregorian_to_jalali(gy: int, gm: int, gd: int) -> Tuple[int, int, int]:
    """تبدیل تاریخ میلادی به شمسی (الگوریتم استاندارد، بدون dependency)."""
    g_d_m = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)

    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621

    gy2 = gy + 1 if gm > 2 else gy
    days = (
        365 * gy
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
        - 80
        + gd
        + g_d_m[gm - 1]
    )
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461

    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365

    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30

    return jy, jm, jd


def fmt_tehran(value: Any) -> str:
    """مقدار UTC (ذخیره‌سازی SQLite) را تاریخ شمسی + ساعت تهران می‌کند.

    خروجی مثال: «1405/07/11 — 15:30» (ارقام انگلیسی).
    - None یا رشته خالی ⇒ «نامشخص»
    - رشته نامعتبر ⇒ همان مقدار خام برمی‌گردد (بدون crash)
    """
    if value is None:
        return "نامشخص"

    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return "نامشخص"
        normalized = text.replace("T", " ").split(".")[0].strip()
        try:
            dt = datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return text

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    local = dt.astimezone(_TEHRAN_TZ)
    jy, jm, jd = _gregorian_to_jalali(
        local.year, local.month, local.day
    )
    return (
        f"{jy:04d}/{jm:02d}/{jd:02d} — "
        f"{local.hour:02d}:{local.minute:02d}"
    )


async def _delete_messages_after_delay(
    bot: Any,
    chat_id: int,
    message_ids: List[int],
    delay: int,
) -> None:
    await asyncio.sleep(max(0, delay))

    for msg_id in dict.fromkeys(message_ids):
        try:
            await bot.delete_message(
                chat_id=chat_id,
                message_id=msg_id,
            )
        except TelegramError as err:
            logger.warning(
                "Delete failed chat=%s msg=%s err=%s",
                chat_id,
                msg_id,
                err,
            )


def schedule_delete(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_ids: List[int],
) -> None:
    if not message_ids:
        return

    context.application.create_task(
        _delete_messages_after_delay(
            bot=context.bot,
            chat_id=chat_id,
            message_ids=message_ids,
            delay=config.DELETE_AFTER_SECONDS,
        ),
    )


def track_user(update: Update) -> None:
    user = update.effective_user
    if user:
        db.save_or_update_user(
            user.id,
            user.username,
            user.first_name,
            user.last_name,
        )


async def get_bot_username(
    context: ContextTypes.DEFAULT_TYPE,
) -> str:
    return context.bot.username or (await context.bot.get_me()).username


async def build_download_link(
    context: ContextTypes.DEFAULT_TYPE,
    session_id: str,
) -> str:
    username = await get_bot_username(context)
    return f"https://t.me/{username}?start={session_id}"


async def safe_edit_or_send(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    message_id: Optional[int] = None,
    parse_mode: Optional[str] = None,
) -> int:
    if message_id is not None:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            return message_id
        except Exception:
            pass

    sent = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
    )

    return sent.message_id


def total_pages(count: int, page_size: int) -> int:
    return max((count - 1) // page_size + 1, 1)


async def go_to_main_menu(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
) -> None:
    await context.bot.send_message(
        chat_id=chat_id,
        text=Msg.MAIN_MENU_PROMPT,
        reply_markup=main_menu_for(chat_id),
    )


async def go_to_ongoing_menu(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
) -> None:
    await context.bot.send_message(
        chat_id=chat_id,
        text="📺 بخش انیمه‌های درحال پخش:",
        reply_markup=ONGOING_MENU_MARKUP,
    )
