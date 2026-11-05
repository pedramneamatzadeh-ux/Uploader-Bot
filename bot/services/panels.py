"""P16 — انحصار پنل‌ها.

با فشار هر دکمه‌ی پنل در منوی اصلی، اول state همه‌ی پنل‌های بازِ
همان (chat, user) پاک می‌شود تا پنل جدید تمیز باز شود و
هندلرهای catch-all پنل قبلی (مدیریت/آمار) دکمه‌های پنل جدید را
نبلعند (باگ «❌ گزینه نامعتبر»).

نکته‌ی فنی: state مکالمه‌ها در PTB 22.x داخل دیکت داخلی
``handler._conversations`` با کلید ``(chat_id, user_id)`` نگه
داشته می‌شود (per_chat + per_user پیش‌فرض، per_message=False).
چون این یک API داخلی است، در requirements.txt نسخه به
``python-telegram-bot>=22.7,<23`` پین شده است.
"""

import logging
import re
from typing import Dict, Optional

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from ..constants import SETTINGS_BUTTON
from ..constants import Msg
from ..utils import PANEL_MSG_KEY

logger = logging.getLogger(__name__)

# متن دقیق دکمه‌های پنلِ منوی اصلی.
# «💾 بک‌آپ» عمداً نیست: اکشن یک‌باره است، پنل نیست.
PANEL_BUTTONS = (
    "آپلود",
    "مدیریت فایل‌ها",
    "آمار",
    "انیمه‌های درحال پخش",
    "📢 پیام همگانی",
    "📝 پست‌ها",
    SETTINGS_BUTTON,
)

PANEL_BUTTONS_PATTERN = (
    "^(" + "|".join(re.escape(t) for t in PANEL_BUTTONS) + ")$"
)

# کلید نگاشت پنل‌ها در bot_data
BOT_DATA_KEY = "panel_convs"


def register_panels(
    application,
    mapping: Dict[str, ConversationHandler],
) -> None:
    """نگاشت «نام پنل → ConversationHandler» را در bot_data ثبت می‌کند.

    در build_application صدا زده می‌شود تا gate بتواند بعداً
    state پنل‌ها را پاک کند.
    """
    application.bot_data[BOT_DATA_KEY] = dict(mapping)


def close_panels_for(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    keep: Optional[str] = None,
) -> int:
    """state همه‌ی پنل‌های بازِ (chat, user) را پاک می‌کند.

    تعداد پنل‌های بسته‌شده را برمی‌گرداند. اگر ``keep`` داده شود
    آن پنل دست‌نخورده می‌ماند.
    """
    mapping = {}
    try:
        bot_data = context.application.bot_data
    except AttributeError:
        bot_data = None
    if bot_data:
        mapping = bot_data.get(BOT_DATA_KEY) or {}

    key = (chat_id, user_id)
    closed = 0
    for name, handler in mapping.items():
        if keep is not None and name == keep:
            continue
        convs = getattr(handler, "_conversations", None)
        if not isinstance(convs, dict):
            # سازگاری دفاعی با نسخه‌های آینده‌ی PTB
            continue
        if key in convs:
            del convs[key]
            closed += 1

    if closed:
        logger.info(
            "P16: %d پنل برای chat=%s user=%s بسته شد.",
            closed,
            chat_id,
            user_id,
        )
    return closed


async def panel_gate(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """هندلر group=-1: قبل از باز شدن هر پنل، پنل‌های باز بسته می‌شوند.

    چون groupها مستقل پردازش می‌شوند، این هندلر قبل از
    ConversationHandlerهای group 0 اجرا می‌شود؛ هیچ پیامی هم
    ارسال نمی‌کند — فقط state پاک می‌شود و ورودی پنل مقصد در
    group 0 به‌صورت عادی پنل جدید را باز می‌کند.
    """
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return

    # R15: پنل قبلی باید واقعاً بسته شود — پیام(های) ثبت‌شده‌اش به
    # «🚫 پنل بسته شد.» ویرایش می‌شوند و همهٔ دکمه‌ها حذف می‌شوند.
    # خطای ویرایش (پیام حذف‌شده/خیلی قدیمی) هرگز جلوی پنل جدید را
    # نمی‌گیرد.
    try:
        tracked = context.chat_data.pop(PANEL_MSG_KEY, None) or []
    except (AttributeError, TypeError):
        tracked = []
    for mid in tracked:
        try:
            await context.bot.edit_message_text(
                chat_id=chat.id,
                message_id=mid,
                text=Msg.PANEL_CLOSED,
                reply_markup=None,
            )
        except Exception:
            pass

    close_panels_for(context, chat.id, user.id)


async def stale_callback_answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """آخرین هندلر group 0: پاسخ به callbackهای بی‌صاحب.

    دکمه‌های inline پنل‌های بسته‌شده روی صفحه می‌مانند؛ با فشار
    آن‌ها هیچ هندلری match نمی‌شد و spinner بی‌پاسخ می‌ماند.
    این هندلر فقط همان‌ها را می‌گیرد (چون آخر group 0 است) و
    toast «پنل بسته شده» می‌دهد.
    """
    query = update.callback_query
    if not query:
        return
    try:
        await query.answer("🚫 این پنل بسته شده است.")
    except Exception:  # pragma: no cover
        logger.debug("پاسخ به callback بی‌صاحب ناموفق بود.", exc_info=True)
