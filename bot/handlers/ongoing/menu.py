"""ورودی بخش درحال پخش (B5: مستقیم به مدیریت انیمه‌ها)."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from ...decorators import admin_only

from .manage import start_ongoing_manage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ورودی بخش درحال پخش — منوی میانی حذف شد (تصمیم کاربر، B5)
# ---------------------------------------------------------------------------
@admin_only
async def start_ongoing(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    context.user_data.clear()
    # مستقیم به لیست مدیریت انیمه‌های درحال پخش
    return await start_ongoing_manage(update, context)
