"""سطح ۱: لیست اسامی + جستجو + صفحه‌بندی + مرتب‌سازی."""

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

from .common import SORT_LABELS, _manage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# سطح ۱: اسامی انیمه‌ها (لیست اصلی + جستجو + صفحه‌بندی + مرتب‌سازی)
# ---------------------------------------------------------------------------
async def show_link_list(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    page: int = 0,
) -> None:
    manage = _manage(context)
    mode = manage.get("mode", "list")
    term = manage.get("search_term")
    sort = manage.get("sort", "new")  # B3: پیش‌فرض = جدیدترین

    use_search = bool(mode == "search" and term)
    active_term = term if use_search else None

    items = db.list_anime_names(active_term, sort, page)
    total = db.count_anime_names(active_term)
    pages = total_pages(total, config.PAGE_SIZE)

    manage["l1"] = items
    manage["level"] = 1
    for key in (
        "name",
        "display_name",
        "names",
        "season",
        "part",
        "episode",
        "is_cinema",
        "l2",
        "l3",
        "l4",
    ):
        manage.pop(key, None)

    if use_search:
        title = f"🔍 نتایج جستجو برای '{term}':\n\n"
    else:
        title = "📋 انیمه‌ها:\n\n"

    keyboard = []

    if not items:
        text = title + "انیمه‌ای یافت نشد. 😕"
        if pages > 1:
            nav = build_pagination_row(
                page,
                pages,
                f"page:{page - 1}",
                "refresh_list",
                f"page:{page + 1}",
            )
            if nav:
                keyboard.append(nav)
    else:
        lines = []
        for idx, item in enumerate(items, start=1):
            icon = "🎬 " if item.get("cinema") else ""
            lines.append(
                f"{idx}. {icon}{item['display_name']} "
                f"({item['links']} لینک)"
            )

        text = title + "\n".join(lines)
        text += f"\n\n📄 صفحه {page + 1} از {pages} ({total} انیمه)"

        for idx, item in enumerate(items):
            icon = "🎬 " if item.get("cinema") else ""
            short = item["display_name"]
            if len(short) > 28:
                short = short[:25] + "..."
            keyboard.append(
                [
                    ib(
                        f"{idx + 1}. {icon}{short}",
                        callback_data=f"m1:{idx}",
                        style="primary",
                    )
                ]
            )

        keyboard.append(
            [
                ib(
                    f"🔃 مرتب: {SORT_LABELS.get(sort, 'الفبایی')}",
                    callback_data="mg_sort",
                )
            ]
        )

        nav = build_pagination_row(
            page,
            pages,
            f"page:{page - 1}",
            "refresh_list",
            f"page:{page + 1}",
        )
        if nav:
            keyboard.append(nav)

    action_row = [
        ib("🔍 جستجو", callback_data="search_links"),
    ]
    if use_search:
        action_row.append(
            ib(
                "✖️ حذف نتایج",
                callback_data="search_clear",
            )
        )
    action_row.append(
        ib("➕ ایجاد لینک", callback_data="create_new"),
    )
    keyboard.append(action_row)
    keyboard.append(
        [ib("🏠 بازگشت", callback_data="back_to_main")]
    )

    markup = InlineKeyboardMarkup(keyboard)
    msg_id = manage.get("list_message_id")
    new_id = await safe_edit_or_send(context, chat_id, text, markup, msg_id)
    manage["list_message_id"] = new_id
    context.user_data["manage"] = manage
