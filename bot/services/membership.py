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


async def get_not_joined_channels(
    user_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> List[Union[int, str]]:
    not_joined: List[Union[int, str]] = []

    for channel in config.REQUIRED_CHANNELS:
        try:
            member = await context.bot.get_chat_member(
                chat_id=channel,
                user_id=user_id,
            )
            if not is_member_status(member):
                not_joined.append(channel)
        except TelegramError as err:
            logger.warning(
                "Membership check failed user=%s ch=%s err=%s",
                user_id,
                channel,
                err,
            )
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
                    ib(f"عضویت در {channel_display_name(channel)}", url=join_url)
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
                        ib(f"عضویت در {title}", url=f"https://t.me/{chat.username}")
                    ]
                )
            elif getattr(chat, "invite_link", None):
                keyboard.append(
                    [
                        ib(f"عضویت در {title}", url=chat.invite_link)
                    ]
                )
            else:
                try:
                    invite = await context.bot.create_chat_invite_link(channel)
                    keyboard.append(
                        [
                            ib(f"عضویت در {title}", url=invite.invite_link)
                        ]
                    )
                except TelegramError:
                    text_lines.append(f"- {title}")
        except TelegramError:
            text_lines.append(f"- {channel_display_name(channel)}")

    keyboard.append(
        [
            ib("✅ عضو شدم، بررسی مجدد", callback_data=f"recheck:{session_id}")
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
