"""R2 — پنل تنظیمات (فقط مالک ربات).

چهار بخش: ادمین‌ها، کانال‌های اجباری، مدت حذف پیام، دیتابیس‌های سفارشی.
همه تغییرات از طریق set_setting بلافاصله روی config اعمال می‌شوند.
هر handler این ماژول با owner_only محافظت شده است (دفاع در عمق).
"""

import logging
import re
from typing import Optional

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes, ConversationHandler

from ...config import config
from ...constants import (
    SETTINGS_ADMIN,
    SETTINGS_CHANNEL,
    SETTINGS_DB_CHAT,
    SETTINGS_DB_NAME,
    SETTINGS_DURATION,
    SETTINGS_PANEL,
    Msg,
)
from ...database import db
from ...decorators import owner_only
from ...keyboards import (
    main_menu_for,
    settings_admins_keyboard,
    settings_channels_keyboard,
    settings_confirm_keyboard,
    settings_databases_keyboard,
    settings_duration_keyboard,
    settings_input_keyboard,
    settings_panel_keyboard,
)
from ...utils import go_to_main_menu, normalize_digits

from .common import cancel_settings
from .panel import open_settings
from .inputs import receive_admin_input
from .inputs import receive_channel_input
from .inputs import receive_db_chat_input
from .inputs import receive_db_name_input
from .inputs import receive_duration_input
from .panel import settings_callback

__all__ = [
    "cancel_settings",
    "open_settings",
    "receive_admin_input",
    "receive_channel_input",
    "receive_db_chat_input",
    "receive_db_name_input",
    "receive_duration_input",
    "settings_callback",
]
