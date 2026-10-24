import asyncio
import logging
from typing import Optional

from telegram import InlineKeyboardMarkup, Update
from telegram.error import RetryAfter, TelegramError
from telegram.ext import ContextTypes

from ..config import config
from ..constants import Msg
from ..database import db
from ..keyboards import ib
from ..utils import (
    get_default_channel_chat_id,
    parse_range,
    schedule_delete,
    track_user,
)
from .membership import get_not_joined_channels, send_join_prompt


logger = logging.getLogger(__name__)


async def deliver_files_for_session(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session_id: str,
) -> bool:
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message

    if not user or not chat or not message:
        return False

    track_user(update)

    upload_data = db.get_upload(session_id)
    if not upload_data:
        return False

    if upload_data.get("status") != "active":
        await message.reply_text(Msg.LINK_INACTIVE)
        return True

    missing = await get_not_joined_channels(user.id, context)
    if missing:
        await send_join_prompt(update, context, session_id, missing)
        return True

    join_msg_id = context.user_data.pop("join_prompt_msg_id", None)
    if join_msg_id:
        try:
            await context.bot.delete_message(
                chat_id=chat.id,
                message_id=join_msg_id,
            )
        except TelegramError:
            pass

    rng = parse_range(upload_data.get("channel_msg_range"))
    if not rng:
        await message.reply_text(Msg.INVALID_RANGE)
        return True

    raw_from = upload_data.get("channel_chat_id")
    from_chat_id: Optional[int] = None

    if raw_from is not None and str(raw_from).strip() != "":
        try:
            from_chat_id = int(raw_from)
        except (TypeError, ValueError):
            from_chat_id = None

    if from_chat_id is None:
        from_chat_id = get_default_channel_chat_id()

    if from_chat_id is None:
        await message.reply_text(Msg.NO_STORAGE_CHANNEL)
        return True

    # P14: پیش‌چک دسترسی به کانال منبع (به‌جای N خطای تکی)
    try:
        await context.bot.get_chat(from_chat_id)
    except TelegramError as err:
        logger.warning(
            "دسترسی به کانال منبع %s ممکن نیست: %s", from_chat_id, err
        )
        await message.reply_text(Msg.CHANNEL_UNREACHABLE)
        return True

    start_id, end_id = rng
    prep_msg = await message.reply_text(Msg.PREPARING)

    sent_count = 0
    failed_ids = []
    sent_message_ids = [prep_msg.message_id]

    for msg_id in range(start_id, end_id + 1):
        # P10: در صورت RetryAfter صبر کن و یک‌بار تلاش مجدد
        for attempt in (1, 2):
            try:
                copied = await context.bot.copy_message(
                    chat_id=chat.id,
                    from_chat_id=from_chat_id,
                    message_id=msg_id,
                )
                sent_count += 1
                sent_message_ids.append(copied.message_id)
                break
            except RetryAfter as error:
                if attempt == 2:
                    logger.error(
                        "RetryAfter برای پیام %s کافی نبود", msg_id
                    )
                    failed_ids.append(msg_id)
                    break
                logger.warning(
                    "RetryAfter %ss برای پیام %s", error.retry_after, msg_id
                )
                await asyncio.sleep(error.retry_after + 0.1)
            except TelegramError as error:
                logger.error("خطا در کپی پیام %s: %s", msg_id, error)
                failed_ids.append(msg_id)
                break

    if sent_count:
        db.record_download(session_id, user.id)

        if upload_data.get("anime_type") == "سینمایی":
            final_text = (
                "✅ ارسال کامل شد!\n"
                f"📥 {sent_count} فایل با کیفیت {upload_data['quality']} ارسال شد.\n"
                "🏷️ نوع: سینمایی\n"
                f"🎬 {upload_data['anime_name']}\n"
                f"🎞️ سینمایی شماره: {upload_data.get('season_num') or 'نامشخص'}"
            )
        else:
            part_line = (
                f"📦 پارت: {upload_data['part_num']}\n"
                if upload_data.get("part_num")
                else ""
            )
            final_text = (
                "✅ ارسال کامل شد!\n"
                f"📥 {sent_count} فایل با کیفیت {upload_data['quality']} ارسال شد.\n"
                f"🎬 {upload_data['anime_name']}\n"
                f"🎞️ فصل: {upload_data.get('season_num') or 'نامشخص'}\n"
                f"{part_line}"
                f"📺 قسمت: {upload_data['episode_range']}"
            )

        report_kb = InlineKeyboardMarkup(
            [
                [
                    ib("🔴 گزارش خرابی فایل‌ها", "danger", callback_data=f"report:{session_id}")
                ]
            ]
        )

        final_msg = await message.reply_text(
            final_text,
            reply_markup=report_kb,
        )

        info_msg = await message.reply_text(
            f"🗑️ این پیام‌ها پس از {config.DELETE_AFTER_SECONDS} ثانیه به طور خودکار حذف خواهند شد."
        )
        sent_message_ids.append(info_msg.message_id)

        schedule_delete(context, chat.id, sent_message_ids)

        # R8e: پیامِ حامل دکمه «🔴 گزارش خرابی فایل‌ها» task حذف
        # *لغوپذیر* جداگانه می‌گیرد — اگر کاربر پیش از حذف دکمه را
        # بزند، task در base.py لغو می‌شود و پیام تا پایان دریافت
        # توضیحات باقی می‌ماند؛ در غیر این صورت همراه فایل‌ها حذف می‌شود.
        keep_task = schedule_delete(
            context,
            chat.id,
            [final_msg.message_id],
        )
        if keep_task is not None:
            context.chat_data.setdefault(
                "report_del_tasks",
                {},
            )[final_msg.message_id] = keep_task

    if failed_ids:
        await message.reply_text(
            "⚠️ بعضی پیام‌ها ارسال نشدند. لطفاً آیدی‌های زیر را بررسی کن:\n"
            + ", ".join(str(mid) for mid in failed_ids)
        )

    return True


async def deliver_post_for_session(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    post_id: str,
) -> bool:
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message

    if not user or not chat or not message:
        return False

    track_user(update)

    post = db.get_post(post_id)
    if not post:
        return False

    if post.get("status") != "active":
        await message.reply_text(Msg.LINK_INACTIVE)
        return True

    missing = await get_not_joined_channels(user.id, context)
    if missing:
        await send_join_prompt(update, context, post_id, missing)
        return True

    join_msg_id = context.user_data.pop("join_prompt_msg_id", None)
    if join_msg_id:
        try:
            await context.bot.delete_message(
                chat_id=chat.id,
                message_id=join_msg_id,
            )
        except TelegramError:
            pass

    messages = db.get_post_messages(post_id)
    if not messages:
        await message.reply_text("❌ این پست خالی است.")
        return True

    # P14: پیش‌چک دسترسی به چت منبع پست
    try:
        await context.bot.get_chat(messages[0]["chat_id"])
    except TelegramError as err:
        logger.warning(
            "دسترسی به چت منبع پست %s ممکن نیست: %s", post_id, err
        )
        await message.reply_text(Msg.CHANNEL_UNREACHABLE)
        return True

    prep_msg = await message.reply_text(Msg.PREPARING)
    sent_message_ids = [prep_msg.message_id]
    sent_count = 0

    for post_msg in messages:
        # P10: در صورت RetryAfter صبر کن و یک‌بار تلاش مجدد
        for attempt in (1, 2):
            try:
                copied = await context.bot.copy_message(
                    chat_id=chat.id,
                    from_chat_id=post_msg["chat_id"],
                    message_id=post_msg["message_id"],
                )
                sent_count += 1
                sent_message_ids.append(copied.message_id)
                break
            except RetryAfter as err:
                if attempt == 2:
                    logger.error(
                        "RetryAfter برای پیام پست %s کافی نبود",
                        post_msg["message_id"],
                    )
                    break
                logger.warning(
                    "RetryAfter %ss برای پیام پست %s",
                    err.retry_after,
                    post_msg["message_id"],
                )
                await asyncio.sleep(err.retry_after + 0.1)
            except TelegramError as err:
                logger.error(
                    "خطا در کپی پیام پست %s msg=%s: %s",
                    post_id,
                    post_msg["message_id"],
                    err,
                )
                break

    if sent_count:
        # B4: ثبت آمار تحویل پست
        db.record_post_delivery(post_id, user.id)
        final_msg = await message.reply_text(
            f"✅ پست «{post['post_name']}» ارسال شد.\n"
            f"📨 تعداد پیام‌ها: {sent_count}"
        )
        sent_message_ids.append(final_msg.message_id)

        info_msg = await message.reply_text(
            f"🗑️ این پیام‌ها پس از {config.DELETE_AFTER_SECONDS} ثانیه به طور خودکار حذف خواهند شد."
        )
        sent_message_ids.append(info_msg.message_id)

        schedule_delete(context, chat.id, sent_message_ids)
    else:
        await message.reply_text("⚠️ هیچ پیامی از این پست ارسال نشد.")

    return True


async def deliver_summary_for_session(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session_id: str,
) -> bool:
    """خلاصه داستان فصل را با لینک `sm<id>` برای کاربر می‌فرستد.

    مثل لینک‌های آپلود: چک عضویت کانال‌های اجباری (با دکمه recheck)،
    ارسال عکس (در صورت وجود) + متن کامل، و حذف خودکار پیام‌ها پس از
    DELETE_AFTER_SECONDS. شماره رکورد با upsert ثابت می‌ماند، پس لینک
    با ویرایش متن/عکس از بین نمی‌رود؛ فقط با حذف خلاصه لینک می‌میرد.
    """
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message

    if not user or not chat or not message:
        return False

    if not session_id.startswith("sm"):
        return False

    try:
        summary_id = int(session_id[2:])
    except ValueError:
        return False

    summary = db.get_season_summary_by_id(summary_id)
    if not summary:
        return False

    track_user(update)

    missing = await get_not_joined_channels(user.id, context)
    if missing:
        await send_join_prompt(update, context, session_id, missing)
        return True

    join_msg_id = context.user_data.pop("join_prompt_msg_id", None)
    if join_msg_id:
        try:
            await context.bot.delete_message(
                chat_id=chat.id,
                message_id=join_msg_id,
            )
        except TelegramError:
            pass

    # قالب ارسال (به جای متن خام): عنوان + برچسب + متن
    anime_name = summary.get("anime_name") or ""
    season_num = summary.get("season_num") or ""
    # R12: نام ظاهری مؤثر در سطح فصل (خلاصه‌ها پارت ندارند)
    display = db.get_display_for(anime_name, season_num)
    if db.is_cinema_name(anime_name):
        title = f"Movie: {display} {season_num}".rstrip()
    else:
        title = f"Anime: {display} S{season_num}"
    body = summary.get("summary_text") or ""
    formatted = f"{title}\n\n🧧 خلاصه داستان"
    if body:
        formatted += f"\n\n{body}"

    photo = summary.get("photo_file_id")
    sent_message_ids: list = []

    if photo:
        caption = formatted if len(formatted) <= 1000 else None
        photo_msg = await message.reply_photo(photo=photo, caption=caption)
        sent_message_ids.append(photo_msg.message_id)
        if caption is None:
            text_msg = await message.reply_text(formatted)
            sent_message_ids.append(text_msg.message_id)
    else:
        text_msg = await message.reply_text(formatted)
        sent_message_ids.append(text_msg.message_id)

    if sent_message_ids:
        info_msg = await message.reply_text(
            f"🗑️ این پیام‌ها پس از {config.DELETE_AFTER_SECONDS} ثانیه "
            "به طور خودکار حذف خواهند شد."
        )
        sent_message_ids.append(info_msg.message_id)
        schedule_delete(context, chat.id, sent_message_ids)

    return True
