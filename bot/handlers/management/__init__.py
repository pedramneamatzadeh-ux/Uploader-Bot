"""زیرماژول‌های management — صادرات برای application.py."""

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

from .inputs import cancel_management
from .inputs import handle_edit_input
from .dispatch import handle_management_callback
from .extras import handle_extra_text
from .inputs import handle_search_input
from .inputs import start_management
from .summary import handle_summary_photo, handle_summary_text

__all__ = [
    "cancel_management",
    "handle_edit_input",
    "handle_extra_text",
    "handle_management_callback",
    "handle_search_input",
    "handle_summary_photo",
    "handle_summary_text",
    "start_management",
]
