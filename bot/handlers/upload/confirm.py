"""صفحه تأیید و ثبت نهایی."""

import logging
import re
import sqlite3
import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler
from typing import Any, List

from ...config import config
from ...constants import (
    ALL_QUALITIES,
    ANIME_NAME,
    ANIME_TYPE,
    CONFIRM,
    CUSTOM_AIRING,
    DB_SELECT,
    EPISODE_RANGE,
    MANAGE_EPISODES,
    MOVIE_NUM,
    MULTI_QUALITY,
    MULTI_QUALITY_CHANNEL,
    PART_NUM,
    SEASON_NUM,
    Msg,
)
from ...database import db
from ...decorators import admin_only
from ...keyboards import (
    ib,
    CANCEL_MENU,
    airing_status_keyboard,
    db_select_page1_keyboard,
    db_select_page2_keyboard,
    main_menu_for,
    movie_keyboard,
    part_keyboard,
    quality_multiselect_keyboard,
    season_keyboard,
)
from ...utils import (
    build_download_link,
    get_default_channel_chat_id,
    go_to_main_menu,
    register_panel_message,
    normalize_digits,
    normalize_optional_text,
    validate_anime_name,
    validate_channel_input,
    validate_episode_input,
)

from .common import EPISODE_QUESTION_TEXT

logger = logging.getLogger(__name__)


# ============================================================================
# صفحه تأیید + ذخیره + «آپلود قسمت بعدی» / «پایان»
# ============================================================================
async def show_upload_confirm(
    message: Any,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    base = context.user_data
    is_cinema = base.get("anime_type") == "سینمایی"

    lines = ["📋 خلاصه آپلود:"]

    if base.get("db_name"):
        lines.append(f"🗄️ دیتابیس: {base['db_name']}")
    if base.get("airing_status"):
        lines.append(f"⏳ وضعیت پخش: {base['airing_status']}")

    if is_cinema:
        lines.append("🏷️ نوع: سینمایی")
        lines.append(f"🎬 انیمه: {base.get('anime_name', '')}")
        lines.append(
            f"🎞️ سینمایی شماره: {base.get('season_num') or 'نامشخص'}"
        )
    else:
        if base.get("anime_type"):
            lines.append(f"🏷️ نوع: {base['anime_type']}")
        lines.append(f"🎬 انیمه: {base.get('anime_name', '')}")
        lines.append(f"🎞️ فصل: {base.get('season_num') or 'نامشخص'}")
        lines.append(f"📦 پارت: {base.get('part_num') or 'ندارد'}")
        lines.append(
            f"📺 قسمت‌ها: {base.get('episode_range') or 'نامشخص'}"
        )

    lines.append(
        f"🖨 بلوری: {'✅ بله' if base.get('is_bluray') else '❌ خیر'}"
    )
    lines.append("")
    lines.append("کیفیت‌ها:")
    for idx, item in enumerate(base.get("qualities") or [], 1):
        lines.append(
            f"{idx}. {item['quality']} → محدوده {item['channel_msg_range']}"
        )

    lines.append("\nآیا اطلاعات صحیح است؟")

    keyboard = [
        [
            ib("✅ تأیید", callback_data="confirm_save"),
            ib("❌ انصراف", callback_data="cancel_confirm"),
        ]
    ]

    sent = await message.reply_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    register_panel_message(context, sent.message_id)


@admin_only
async def confirm_upload(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    if not query or not query.data:
        return CONFIRM

    data = query.data

    # R9: در حالت مدیریت (افزودن قسمت از صفحه فصل)، «پایان»/«انصراف»
    # به صفحه قسمت‌های همان فصل برمی‌گردد — نه منوی اصلی.
    # (باید قبل از شاخه‌های اصلی up_done/cancel_confirm باشد)
    if data in ("up_done", "cancel_confirm") and context.user_data.get(
        "manage"
    ):
        await query.answer()
        if data == "up_done":
            await query.edit_message_text(Msg.UPLOAD_SAVED)
        else:
            await query.edit_message_text(Msg.UPLOAD_CANCELLED_INLINE)
        manage_state = context.user_data.get("manage")
        chat_id = (
            query.message.chat_id if query.message else query.from_user.id
        )
        context.user_data.clear()
        context.user_data["manage"] = manage_state
        # import تنبل — بدون ایجاد حلقه ماژولی بین پکیج‌ها
        from ..management.episodes import show_episode_list

        await show_episode_list(chat_id, context)
        return MANAGE_EPISODES

    if data == "cancel_confirm":
        await query.answer()
        await query.edit_message_text(Msg.UPLOAD_CANCELLED_INLINE)
        await go_to_main_menu(context, query.from_user.id)
        context.user_data.clear()
        return ConversationHandler.END

    if data == "up_done":
        await query.answer()
        await query.edit_message_text(Msg.UPLOAD_SAVED)
        await go_to_main_menu(context, query.from_user.id)
        context.user_data.clear()
        return ConversationHandler.END

    if data == "next_ep":
        # فیلدهای ثابت (دیتابیس/نوع/نام/فصل/پارت/وضعیت) می‌مانند؛
        # قسمت و کیفیت‌ها دوباره پرسیده می‌شوند.
        await query.answer()
        for key in (
            "episode_range",
            "qualities",
            "mq_selected",
            "mq_queue",
        ):
            context.user_data.pop(key, None)

        if context.user_data.get("anime_type") == "سینمایی":
            await query.edit_message_text(
                "سینمایی چندم هست؟ (فقط عدد وارد کن)\nمثال: 1"
            )
            return MOVIE_NUM

        await query.edit_message_text(EPISODE_QUESTION_TEXT)
        return EPISODE_RANGE

    # confirm_save
    await query.answer()
    base = context.user_data
    qualities = base.get("qualities") or []

    if not qualities:
        if query.message:
            await query.message.reply_text(
                "❌ لیست کیفیت‌ها خالی است؛ دوباره تلاش کن.",
            )
        return CONFIRM

    channel_chat_id = base.get("channel_chat_id")
    if channel_chat_id is None:
        channel_chat_id = get_default_channel_chat_id()

    links_text = ""
    for item in qualities:
        session_id = str(uuid.uuid4())
        entry = {
            "anime_name": base["anime_name"],
            "season_num": base.get("season_num"),
            "part_num": base.get("part_num"),
            "episode_range": base.get("episode_range"),
            "quality": item["quality"],
            "channel_msg_range": item["channel_msg_range"],
            "anime_type": base.get("anime_type", ""),
            "channel_chat_id": channel_chat_id,
            "airing_status": base.get("airing_status"),
            "is_bluray": 1 if base.get("is_bluray") else 0,
        }

        try:
            db.save_upload(session_id, entry, query.from_user.id)
        except sqlite3.Error as err:
            logger.exception("ذخیره ناموفق: %s", err)
            if query.message:
                await query.message.reply_text(Msg.SAVE_ERROR)
            context.user_data.clear()
            return ConversationHandler.END

        link = await build_download_link(context, session_id)
        links_text += f"🔗 {item['quality']}: <code>{link}</code>\n"

    keyboard = [
        [
            ib(
                "➕ آپلود قسمت بعدی با همین اطلاعات",
                callback_data="next_ep",
            )
        ],
        [
            ib(
                "🏠 پایان",
                callback_data="up_done",
            )
        ],
    ]

    await query.edit_message_text(
        "✅ آپلود با موفقیت ثبت شد!\n\n" + links_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return CONFIRM
