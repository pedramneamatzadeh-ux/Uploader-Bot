import asyncio
import logging
from typing import Optional

from telegram import InlineKeyboardMarkup, Update
from telegram.error import BadRequest, RetryAfter, TelegramError
from telegram.ext import ContextTypes

from ..constants import Msg
from ..database import db
from ..keyboards import ib
from ..utils import (
    deletion_notice_text,
    get_default_channel_chat_id,
    parse_id_list,
    schedule_delete,
    track_user,
)
from .membership import get_not_joined_channels, send_join_prompt


logger = logging.getLogger(__name__)


def build_final_text(upload_data: dict, sent_count: int) -> str:
    """R28: پیامِ پایانیِ تحویل فایل — یک منبع برای لینک عادی و لینک فصل.

    هر دو مسیر (لینک کیفیت قدیمی و پنل لینک فصل) باید **دقیقاً** همین
    متن را بفرستند تا تجربهٔ کاربر یکسان باشد.
    """
    # B20: نسخه بلوری — کاربر هم در پیام تحویل می‌بیند
    bluray_line = "🖨 نسخه بلوری ✅\n" if upload_data.get("is_bluray") else ""

    if upload_data.get("anime_type") == "سینمایی":
        # R19: سینمایی بدون شماره ⇒ خط شماره حذف (مثل پارت سریالی)
        movie_num_line = (
            f"\n🎞️ سینمایی شماره: {upload_data['season_num']}"
            if upload_data.get("season_num")
            else ""
        )
        return (
            "✅ ارسال کامل شد!\n"
            f"📥 {sent_count} فایل با کیفیت {upload_data['quality']} ارسال شد.\n"
            "🏷️ نوع: سینمایی\n"
            f"{bluray_line}"
            f"🎬 {upload_data['anime_name']}"
            f"{movie_num_line}"
        )

    part_line = (
        f"📦 پارت: {upload_data['part_num']}\n"
        if upload_data.get("part_num")
        else ""
    )
    return (
        "✅ ارسال کامل شد!\n"
        f"📥 {sent_count} فایل با کیفیت {upload_data['quality']} ارسال شد.\n"
        f"{bluray_line}"
        f"🎬 {upload_data['anime_name']}\n"
        f"🎞️ فصل: {upload_data.get('season_num') or 'نامشخص'}\n"
        f"{part_line}"
        f"📺 قسمت: {upload_data['episode_range']}"
    )


def report_keyboard(session_id: str) -> InlineKeyboardMarkup:
    """R28: دکمهٔ «🔴 گزارش خرابی فایل‌ها» برای پیام پایانی تحویل."""
    return InlineKeyboardMarkup(
        [
            [
                ib(
                    "🔴 گزارش خرابی فایل‌ها",
                    "danger",
                    callback_data=f"report:{session_id}",
                )
            ]
        ]
    )


def keep_report_button(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    kind: str = "files",
    start_at=None,
) -> None:
    """R28: زمان‌بندیِ *لغوپذیر* حذفِ پیامِ حامل دکمهٔ گزارش (R8e).

    اگر کاربر پیش از حذف دکمه را بزند، task در base.py لغو می‌شود و پیام
    تا پایان دریافت توضیحات می‌ماند؛ در غیر این صورت با بقیهٔ فایل‌ها
    پاک می‌شود.
    """
    keep_task = schedule_delete(
        context, chat_id, [message_id], kind=kind, start_at=start_at
    )
    if keep_task is not None:
        context.chat_data.setdefault("report_del_tasks", {})[
            message_id
        ] = keep_task


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

    # R22: فهرست آیدی‌ها با ترتیب تایپ کاربر و بدون تکرار
    msg_ids = parse_id_list(upload_data.get("channel_msg_range"))
    if not msg_ids:
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

    prep_msg = await message.reply_text(Msg.PREPARING)

    sent_count = 0
    failed_ids = []
    sent_message_ids = [prep_msg.message_id]

    for msg_id in msg_ids:
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

        final_text = build_final_text(upload_data, sent_count)

        final_msg = await message.reply_text(
            final_text,
            reply_markup=report_keyboard(session_id),
        )

        info_msg = await message.reply_text(deletion_notice_text("files"))
        sent_message_ids.append(info_msg.message_id)

        schedule_delete(context, chat.id, sent_message_ids, kind="files")

        # R8e/R28: پیامِ حامل دکمه «🔴 گزارش خرابی فایل‌ها» task حذف
        # *لغوپذیر* جداگانه می‌گیرد (جزئیات در keep_report_button).
        keep_report_button(context, chat.id, final_msg.message_id, kind="files")

    if failed_ids:
        # R22: با فهرست‌های بلند، پیام از سقف تلگرام رد نشود
        shown = failed_ids[:50]
        rest = len(failed_ids) - len(shown)
        header = (
            "⚠️ بعضی پیام‌ها ارسال نشدند. لطفاً آیدی‌های زیر را بررسی کن:\n"
        )
        if rest > 0:
            header = (
                f"⚠️ {len(failed_ids)} پیام ارسال نشد. ۵۰ آیدی اول:\n"
            )
        await message.reply_text(
            header + ", ".join(str(mid) for mid in shown)
            + (f"\n… و {rest} آیدی دیگر" if rest > 0 else "")
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

        info_msg = await message.reply_text(deletion_notice_text("posts"))
        sent_message_ids.append(info_msg.message_id)

        schedule_delete(context, chat.id, sent_message_ids, kind="posts")
    else:
        await message.reply_text("⚠️ هیچ پیامی از این پست ارسال نشد.")

    return True


async def send_summary_photo(bot, chat_id: int, summary: dict, caption=None):
    """R33: ارسال عکس خلاصه — اولویت با عکسِ کانال، بعد file_id قدیمی.

    عکس کانالی با `copy_message` کپی می‌شود؛ پس با عوض‌شدن توکن ربات هم
    کار می‌کند (فقط عضویت ربات در آن کانال لازم است).
    خروجی: پیام ارسال‌شده یا None.
    """
    from_chat = summary.get("photo_chat_id")
    msg_id = summary.get("photo_msg_id")
    if str(from_chat or "").strip() != "" and msg_id:
        try:
            return await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=int(from_chat),
                message_id=int(msg_id),
                caption=caption,
                parse_mode="HTML" if caption else None,
            )
        except (BadRequest, TelegramError) as err:
            logger.warning(
                "کپی عکس خلاصه از کانال %s/msg=%s ناموفق بود: %s",
                from_chat,
                msg_id,
                err,
            )

    file_id = summary.get("photo_file_id")
    if file_id:
        return await bot.send_photo(
            chat_id=chat_id, photo=file_id, caption=caption
        )

    return None


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

    sent_message_ids: list = []

    # R32/R33: عکس از کانال (اولویت) یا file_id قدیمی؛ اگر ارسال نشد
    # (آیدی خراب/دسترسی نداشتن) کل لینک نمی‌شکند و متن می‌رود.
    has_photo = bool(
        (str(summary.get("photo_chat_id") or "").strip() and summary.get("photo_msg_id"))
        or summary.get("photo_file_id")
    )
    photo_sent = False
    if has_photo:
        caption = formatted if len(formatted) <= 1000 else None
        try:
            photo_msg = None
            channel_photo = (
                str(summary.get("photo_chat_id") or "").strip()
                and summary.get("photo_msg_id")
            )
            if channel_photo:
                photo_msg = await send_summary_photo(
                    context.bot, chat.id, summary, caption
                )
            elif summary.get("photo_file_id"):
                # سازگاری: file_id قدیمی ⇒ همان reply_photo قبلی
                photo_msg = await message.reply_photo(
                    photo=summary["photo_file_id"], caption=caption
                )
        except BadRequest as err:
            logger.warning(
                "عکس خلاصه (id=%s) ارسال نشد — فقط متن می‌رود: %s",
                summary_id,
                err,
            )
        except TelegramError as err:
            logger.warning("ارسال عکس خلاصه ناموفق بود: %s", err)
        else:
            if photo_msg is not None:
                photo_sent = True
                sent_message_ids.append(photo_msg.message_id)
                if caption is None:
                    text_msg = await message.reply_text(formatted)
                    sent_message_ids.append(text_msg.message_id)

    if not photo_sent:
        text_msg = await message.reply_text(formatted)
        sent_message_ids.append(text_msg.message_id)

    if sent_message_ids:
        # R28: خلاصه داستان تایمر مستقل خودش را دارد (جدا از پست‌ها)
        info_msg = await message.reply_text(deletion_notice_text("summary"))
        sent_message_ids.append(info_msg.message_id)
        schedule_delete(context, chat.id, sent_message_ids, kind="summary")

    return True
