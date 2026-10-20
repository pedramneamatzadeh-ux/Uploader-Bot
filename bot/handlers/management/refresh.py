"""رفرش صفحه فعلی متناسب با سطح."""

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

from .episodes import show_episode_list
from .groups import show_group_list
from .list_l1 import show_link_list
from .qualities import show_quality_list

logger = logging.getLogger(__name__)


async def _refresh_current(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    manage: dict,
) -> int:
    """صفحه فعلی (لیست/فصل/قسمت/کیفیت) را رفرش و state آن را برمی‌گرداند."""
    level = manage.get("level", 1)
    if level == 4:
        await show_quality_list(chat_id, context)
        return MANAGE_QUALITIES
    if level == 3:
        await show_episode_list(chat_id, context)
        return MANAGE_EPISODES
    if level == 2:
        await show_group_list(chat_id, context)
        return MANAGE_GROUPS
    await show_link_list(chat_id, context, manage.get("page", 0))
    return MANAGE_LIST
