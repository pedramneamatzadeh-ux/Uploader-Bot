import asyncio
import logging

from telegram import InlineKeyboardMarkup, Update
from telegram.error import RetryAfter, TelegramError
from telegram.ext import ContextTypes, ConversationHandler

from ..constants import BROADCAST_CONFIRM, BROADCAST_INPUT
from ..database import db
from ..decorators import admin_only
from ..keyboards import BROADCAST_CANCEL_MENU, ib, main_menu_for
from ..utils import go_to_main_menu, register_panel_message


logger = logging.getLogger(__name__)


@admin_only
async def start_broadcast(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    context.user_data["broadcast_mode"] = True
    sent = await update.message.reply_text(
        "📢 پیام خود را برای ارسال به تمام کاربران وارد کنید:\n\n"
        "می‌توانید متن، عکس، ویدیو، فایل، استیکر و ... بفرستید.\n"
        "برای لغو دکمه «لغو» را بزنید.",
        reply_markup=BROADCAST_CANCEL_MENU,
    )
    register_panel_message(context, sent.message_id)
    return BROADCAST_INPUT


@admin_only
async def receive_broadcast_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    text = (update.message.text or "").strip()

    if text == "لغو":
        context.user_data.pop("broadcast_mode", None)
        await update.message.reply_text(
            "❌ ارسال پیام همگانی لغو شد.",
            reply_markup=main_menu_for(update.effective_user.id),
        )
        return ConversationHandler.END

    context.user_data["broadcast_msg"] = {
        "chat_id": update.message.chat_id,
        "message_id": update.message.message_id,
    }

    user_count = db.count_users()
    if user_count == 0:
        await update.message.reply_text(
            "❌ هیچ کاربری در دیتابیس وجود ندارد.",
            reply_markup=main_menu_for(update.effective_user.id),
        )
        context.user_data.pop("broadcast_mode", None)
        context.user_data.pop("broadcast_msg", None)
        return ConversationHandler.END

    keyboard = [
        [
            ib("✅ تایید و ارسال", callback_data="bc_confirm"),
            ib("❌ لغو", callback_data="bc_cancel"),
        ]
    ]
    sent = await update.message.reply_text(
        "🔎 پیام بالا برای ارسال همگانی آماده است.\n\n"
        f"👥 تعداد گیرندگان: {user_count} کاربر\n\n"
        "آیا از ارسال این پیام مطمئن هستی؟",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    register_panel_message(context, sent.message_id)
    return BROADCAST_CONFIRM


@admin_only
async def confirm_broadcast(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    if query.data == "bc_cancel":
        context.user_data.pop("broadcast_mode", None)
        context.user_data.pop("broadcast_msg", None)
        await query.edit_message_text("❌ ارسال پیام همگانی لغو شد.")
        await go_to_main_menu(context, chat_id)
        return ConversationHandler.END

    broadcast = context.user_data.get("broadcast_msg")
    if not broadcast:
        await query.edit_message_text("❌ پیام برای ارسال پیدا نشد.")
        await go_to_main_menu(context, chat_id)
        return ConversationHandler.END

    user_ids = db.get_all_user_ids()
    await query.edit_message_text(
        f"📤 در حال ارسال پیام به {len(user_ids)} کاربر..."
    )

    success = 0
    failed = 0

    for uid in user_ids:
        # P10: در صورت محدودیت نرخ (RetryAfter) صبر کن و یک‌بار تلاش مجدد
        for attempt in (1, 2):
            try:
                await context.bot.copy_message(
                    chat_id=uid,
                    from_chat_id=broadcast["chat_id"],
                    message_id=broadcast["message_id"],
                )
                success += 1
                break
            except RetryAfter as err:
                if attempt == 2:
                    logger.warning("RetryAfter برای کاربر %s کافی نبود", uid)
                    failed += 1
                    break
                logger.warning(
                    "RetryAfter %ss برای کاربر %s", err.retry_after, uid
                )
                await asyncio.sleep(err.retry_after + 0.1)
            except TelegramError as err:
                logger.warning("Broadcast failed for user %s: %s", uid, err)
                failed += 1
                break
        if (success + failed) % 30 == 0:
            await asyncio.sleep(1)

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "✅ ارسال پیام همگانی تمام شد!\n\n"
            f"📨 موفق: {success}\n"
            f"❌ ناموفق: {failed}\n"
            f"👥 کل: {len(user_ids)}"
        ),
    )

    context.user_data.pop("broadcast_mode", None)
    context.user_data.pop("broadcast_msg", None)
    await go_to_main_menu(context, chat_id)
    return ConversationHandler.END


async def cancel_broadcast(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    context.user_data.pop("broadcast_mode", None)
    context.user_data.pop("broadcast_msg", None)
    await update.message.reply_text(
        "❌ ارسال پیام همگانی لغو شد.",
        reply_markup=main_menu_for(update.effective_user.id),
    )
    return ConversationHandler.END
