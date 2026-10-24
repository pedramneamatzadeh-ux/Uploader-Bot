"""زیرماژول‌های upload — صادرات برای application.py."""

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
    normalize_digits,
    normalize_optional_text,
    validate_anime_name,
    validate_channel_input,
    validate_episode_input,
)

from .cancel import cancel_from_inline
from .cancel import cancel_upload
from .confirm import confirm_upload
from .structure import movie_num_callback
from .quality import multi_quality_channel_range
from .quality import multiselect_callback
from .structure import part_callback
from .identity import receive_airing_status
from .identity import receive_anime_name
from .identity import receive_anime_type
from .identity import receive_anime_type_callback
from .structure import receive_episode_range
from .structure import receive_movie_num
from .structure import receive_part_num
from .structure import receive_season_num
from .structure import season_callback
from .start import select_database
from .start import start_upload

__all__ = [
    "cancel_from_inline",
    "cancel_upload",
    "confirm_upload",
    "movie_num_callback",
    "multi_quality_channel_range",
    "multiselect_callback",
    "part_callback",
    "receive_airing_status",
    "receive_anime_name",
    "receive_anime_type",
    "receive_anime_type_callback",
    "receive_episode_range",
    "receive_movie_num",
    "receive_part_num",
    "receive_season_num",
    "season_callback",
    "select_database",
    "start_upload",
]
