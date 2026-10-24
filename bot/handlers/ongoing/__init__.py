"""زیرماژول‌های ongoing — صادرات برای application.py."""

import logging
import sqlite3
import uuid
from typing import Any, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from ...config import config
from ...constants import (
    ONGOING_CREATE_NAME,
    ONGOING_CREATE_PART,
    ONGOING_CREATE_SEASON,
    ONGOING_DETAIL,
    ONGOING_EDIT,
    ONGOING_FIELD_MAP,
    ONGOING_LIST,
    ONGOING_UPLOAD_CONFIRM,
    ONGOING_UPLOAD_DB_SELECT,
    ONGOING_UPLOAD_EPISODE,
    ONGOING_UPLOAD_MODE,
    ONGOING_UPLOAD_MULTI_ASK,
    ONGOING_UPLOAD_MULTI_QUALITY,
    ONGOING_UPLOAD_MULTI_RANGE,
    ONGOING_UPLOAD_SELECT,
    ONGOING_UPLOAD_SINGLE_QUALITY,
    ONGOING_UPLOAD_SINGLE_RANGE,
    Msg,
)
from ...database import db
from ...decorators import admin_only
from ...keyboards import (
    ONGOING_CANCEL_MENU,
    ONGOING_PART_MENU,
    build_pagination_row,
    main_menu_for,
    quality_keyboard,
)
from ...utils import (
    build_download_link,
    fmt_tehran,
    get_default_channel_chat_id,
    go_to_ongoing_list,
    normalize_optional_text,
    safe_edit_or_send,
    total_pages,
    validate_channel_input,
    validate_episode_input,
)

from .cancel import cancel_ongoing
from .upload import confirm_ongoing_upload
from .inputs import handle_ongoing_edit_input
from .manage import handle_ongoing_manage_callback
from .upload import handle_ongoing_upload_mode_callback
from .upload import handle_ongoing_upload_select_callback
from .upload import ongoing_multi_ask_more_callback
from .upload import ongoing_multi_quality_callback
from .upload import ongoing_single_quality_callback
from .inputs import receive_ongoing_create_name
from .inputs import receive_ongoing_create_part
from .inputs import receive_ongoing_create_season
from .upload import receive_ongoing_multi_range
from .upload import receive_ongoing_single_range
from .upload import receive_ongoing_upload_episode
from .upload import select_ongoing_database
from .menu import start_ongoing

__all__ = [
    "cancel_ongoing",
    "confirm_ongoing_upload",
    "handle_ongoing_edit_input",
    "handle_ongoing_manage_callback",
    "handle_ongoing_upload_mode_callback",
    "handle_ongoing_upload_select_callback",
    "ongoing_multi_ask_more_callback",
    "ongoing_multi_quality_callback",
    "ongoing_single_quality_callback",
    "receive_ongoing_create_name",
    "receive_ongoing_create_part",
    "receive_ongoing_create_season",
    "receive_ongoing_multi_range",
    "receive_ongoing_single_range",
    "receive_ongoing_upload_episode",
    "select_ongoing_database",
    "start_ongoing",
]
