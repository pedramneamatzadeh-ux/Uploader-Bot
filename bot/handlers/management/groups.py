"""سطح ۲: گروه‌های فصل/پارت/فیلم."""

import logging
import sqlite3
import uuid
from collections import Counter

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from ...config import config
from ...constants import (
    ALL_QUALITIES,
    MANAGE_DETAIL,
    MANAGE_EDIT,
    MANAGE_EPISODES,
    MANAGE_GROUPS,
    MANAGE_LIST,
    MANAGE_QUALITIES,
    MANAGE_SEARCH,
    UPLOAD_FIELD_MAP,
    Msg,
)
from ...database import db
from ...decorators import admin_only
from ...keyboards import (
    ib,
    build_add_quality_keyboard,
    build_pagination_row,
    build_quality_edit_keyboard,
    main_menu_for,
)
from ...utils import (
    build_download_link,
    fmt_tehran,
    get_database_name,
    go_to_main_menu,
    normalize_optional_text,
    parse_range,
    safe_edit_or_send,
    total_pages,
    validate_anime_name,
    validate_channel_input,
    validate_episode_input,
)

from .common import _group_label, _manage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# سطح ۲: گروه‌های فصل/پارت (سینمایی: شماره فیلم)
# ---------------------------------------------------------------------------
async def show_group_list(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    manage = _manage(context)
    display = manage.get("display_name") or manage.get("name") or ""
    groups = manage.get("l2") or []

    manage["level"] = 2
    for key in ("season", "part", "episode", "l3", "l4"):
        manage.pop(key, None)

    # عنوان از محتوای گروه‌ها ساخته می‌شود (نام مخلوط: هم فصل هم فیلم)
    has_series = any(not group.get("is_cinema") for group in groups)
    has_movie = any(group.get("is_cinema") for group in groups)
    if has_series and has_movie:
        title = f"🎬 {display} — فصل‌ها / فیلم‌ها:\n\n"
    elif has_movie:
        title = f"🎞️ {display} — فیلم‌ها:\n\n"
    else:
        title = f"🎬 {display} — فصل‌ها / پارت‌ها:\n\n"

    keyboard = []

    if not groups:
        text = title + "چیزی یافت نشد. 😕"
    else:
        lines = []
        for idx, group in enumerate(groups):
            label = _group_label(
                group.get("season_num") or "",
                group.get("part_num") or "",
                bool(group.get("is_cinema")),
            )
            lines.append(
                f"{idx + 1}. {label} ({group.get('links', 0)} لینک)"
            )

            short = label if len(label) <= 40 else label[:37] + "..."
            keyboard.append(
                [
                    ib(
                        short,
                        callback_data=f"m2:{idx}",
                        style="primary",
                    )
                ]
            )

        text = title + "\n".join(lines)

    keyboard.append(
        [
            ib("◀️ بازگشت", callback_data="mg_back"),
            ib(
                "🏠 منوی اصلی", callback_data="back_to_main"
            ),
        ]
    )

    markup = InlineKeyboardMarkup(keyboard)
    msg_id = manage.get("list_message_id")
    new_id = await safe_edit_or_send(context, chat_id, text, markup, msg_id)
    manage["list_message_id"] = new_id
    context.user_data["manage"] = manage
