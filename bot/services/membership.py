import asyncio
import logging
from typing import List, Union

from telegram import InlineKeyboardMarkup, Update

from ..keyboards import ib
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..config import config
from ..utils import (
    build_channel_join_url,
    channel_display_name,
    is_member_status,
)


logger = logging.getLogger(__name__)


MAX_MEMBER_ATTEMPTS = 3
MEMBER_RETRY_DELAY = 1.5   # ثانیه — هم برای تلاش دوباره، هم بعد از خطا


def _is_not_member_error(err: TelegramError) -> bool:
    """R36: خطاهایی که یعنی «کاربر عضو نیست» (نه خطای شبکه/دسترسی)."""
    text = str(err).lower()
    return (
        "user not found" in text
        or "participant" in text
        or "not a member" in text
        or "kicked" in text
        or "user_id_invalid" in text
    )


async def _check_channel(
    user_id: int,
    channel,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    """R36: بررسی عضویت یک کانال — با تلاش دوباره و تمایز خطاها.

    قبلاً هر خطای گذرا (timeout/Too Many Requests) «عضو نیست» حساب
    می‌شد و کاربری که عضو بود، پیام «عضو شوید» می‌دید.
    """
    for attempt in range(MAX_MEMBER_ATTEMPTS):
        try:
            member = await context.bot.get_chat_member(
                chat_id=channel,
                user_id=user_id,
            )
        except TelegramError as err:
            if _is_not_member_error(err):
                logger.info(
                    "عضویت user=%s ch=%s: %s", user_id, channel, err
                )
                return False
            logger.warning(
                "Membership check retry user=%s ch=%s err=%s",
                user_id,
                channel,
                err,
            )
            if attempt == MAX_MEMBER_ATTEMPTS - 1:
                # خطای غیرقطعی ⇒ کاربر را بیرون نگه ندار (به نفع کاربر)
                return True
            await asyncio.sleep(MEMBER_RETRY_DELAY)
            continue

        if is_member_status(member):
            return True

        # Some channels report "restricted/left" right after joining;
        # یک‌بار دیگر با فاصله چک می‌کنیم.
        if attempt == MAX_MEMBER_ATTEMPTS - 1:
            return False
        await asyncio.sleep(MEMBER_RETRY_DELAY)

    return False


async def get_not_joined_channels(
    user_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> List[Union[int, str]]:
    not_joined: List[Union[int, str]] = []

    for channel in config.REQUIRED_CHANNELS:
        if not await _check_channel(user_id, channel, context):
            not_joined.append(channel)

    return not_joined


async def send_join_prompt(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session_id: str,
    missing: List[Union[int, str]],
) -> None:
    text_lines = [
        "⚠️ برای دسترسی به فایل‌ها، ابتدا باید در کانال(های) زیر عضو شوید:"
    ]
    keyboard = []

    for channel in missing:
        join_url = build_channel_join_url(channel)

        if join_url:
            keyboard.append(
                [
                    # R36: کانال‌ها آبی، دکمه‌های تأیید سبز
                    ib(
                        f"عضویت در {channel_display_name(channel)}",
                        url=join_url,
                        style="primary",
                    )
                ]
            )
            continue

        try:
            chat = await context.bot.get_chat(channel)
            title = getattr(
                chat, "title", None) or channel_display_name(channel)

            if getattr(chat, "username", None):
                keyboard.append(
                    [
                        ib(
                            f"عضویت در {title}",
                            url=f"https://t.me/{chat.username}",
                            style="primary",
                        )
                    ]
                )
            elif getattr(chat, "invite_link", None):
                keyboard.append(
                    [
                        ib(
                            f"عضویت در {title}",
                            url=chat.invite_link,
                            style="primary",
                        )
                    ]
                )
            else:
                try:
                    invite = await context.bot.create_chat_invite_link(channel)
                    keyboard.append(
                        [
                            ib(
                                f"عضویت در {title}",
                                url=invite.invite_link,
                                style="primary",
                            )
                        ]
                    )
                except TelegramError:
                    text_lines.append(f"- {title}")
        except TelegramError:
            text_lines.append(f"- {channel_display_name(channel)}")

    keyboard.append(
        [
            ib(
                "✅ عضو شدم، بررسی مجدد",
                callback_data=f"recheck:{session_id}",
                style="success",
            )
        ]
    )

    text = "\n".join(text_lines) + "\n\nبعد از عضویت، روی «بررسی مجدد» بزنید."
    markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text,
                reply_markup=markup,
            )
            return
        except TelegramError:
            pass

    if update.effective_message:
        sent = await update.effective_message.reply_text(
            text,
            reply_markup=markup,
        )
        context.user_data["join_prompt_msg_id"] = sent.message_id
