import html
import logging
import sqlite3
import uuid

from telegram import InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes, ConversationHandler

from ..config import config
from ..constants import (
    POST_MANAGE_DETAIL,
    POST_MANAGE_EDIT,
    POST_MANAGE_LIST,
    POST_UPLOAD_MESSAGES,
    POST_UPLOAD_NAME,
    Msg,
)
from ..database import db
from ..decorators import admin_only
from ..keyboards import (
    POST_CANCEL_MENU,
    POST_UPLOAD_CANCEL_MENU,
    build_pagination_row,
    ib,
    main_menu_for,
)
from ..utils import (
    build_download_link,
    fmt_tehran,
    go_to_main_menu,
    safe_edit_or_send,
    total_pages,
)


logger = logging.getLogger(__name__)


@admin_only
async def start_posts(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """B9: ورود مستقیم به مدیریت پست‌ها (مشابه انیمه‌های درحال پخش)."""
    context.user_data.pop("post_upload", None)
    context.user_data["post_manage"] = {"page": 0}
    await show_post_list(update.message.chat_id, context, 0)
    return POST_MANAGE_LIST


@admin_only
async def receive_post_name(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    text = update.message.text.strip()

    if text == "لغو":
        # B9: منوی پست‌ها حذف شده — بازگشت به لیست پست‌ها
        context.user_data.pop("post_upload", None)
        await update.message.reply_text(
            "❌ آپلود پست لغو شد.",
            reply_markup=main_menu_for(update.effective_user.id),
        )
        return POST_MANAGE_LIST

    context.user_data.setdefault("post_upload", {})["name"] = text
    context.user_data["post_upload"]["messages"] = []

    await update.message.reply_text(
        f"✅ نام پست: {text}\n\n"
        "حالا پیام‌های پست را ارسال کن.\n"
        "می‌توانی متن، عکس، ویدیو، فایل، گیف، ویس، استیکر و هر نوع مدیای دیگر بفرستی.\n"
        "هر تعداد پیام که بخواهی ارسال کن.\n\n"
        "وقتی تمام شد، دکمه «✅ تمام شد» را بزن.",
        reply_markup=POST_UPLOAD_CANCEL_MENU,
    )
    return POST_UPLOAD_MESSAGES


@admin_only
async def receive_post_messages(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    text = (update.message.text or "").strip()

    if text == "لغو":
        # B9: منوی پست‌ها حذف شده — بازگشت به لیست پست‌ها
        context.user_data.pop("post_upload", None)
        await update.message.reply_text(
            "❌ آپلود پست لغو شد.",
            reply_markup=main_menu_for(update.effective_user.id),
        )
        return POST_MANAGE_LIST

    if text == "✅ تمام شد":
        post_upload = context.user_data.get("post_upload", {})
        messages = post_upload.get("messages", [])

        if not messages:
            await update.message.reply_text(
                "⚠️ هنوز هیچ پیامی ارسال نکرده‌ای. حداقل یک پیام بفرست.",
                reply_markup=POST_UPLOAD_CANCEL_MENU,
            )
            return POST_UPLOAD_MESSAGES

        post_id = str(uuid.uuid4())
        admin_id = update.effective_user.id

        try:
            db.save_post(post_id, post_upload["name"], admin_id)
            for order, post_msg in enumerate(messages, start=1):
                db.add_post_message(
                    post_id,
                    post_msg["chat_id"],
                    post_msg["message_id"],
                    order,
                )
        except sqlite3.Error as err:
            logger.exception("خطا در ذخیره پست: %s", err)
            await update.message.reply_text(
                Msg.SAVE_ERROR,
                reply_markup=main_menu_for(update.effective_user.id),
            )
            context.user_data.pop("post_upload", None)
            return POST_MANAGE_LIST

        link = await build_download_link(context, post_id)
        await update.message.reply_text(
            f"✅ پست «{post_upload['name']}» با موفقیت ذخیره شد!\n\n"
            f"📨 تعداد پیام‌ها: {len(messages)}\n\n"
            f"🔗 لینک پست:\n<code>{link}</code>",
            parse_mode="HTML",
            reply_markup=main_menu_for(update.effective_user.id),
        )
        context.user_data.pop("post_upload", None)
        # B9: رفرش لیست تا پست جدید دیده شود
        manage = context.user_data.get("post_manage") or {"page": 0}
        await show_post_list(
            update.message.chat_id, context, manage.get("page", 0)
        )
        return POST_MANAGE_LIST

    if getattr(update.message, "service", False):
        # P14: پیام سرویسی (مثل عضویت/خروج) در پست ذخیره نمی‌شود
        await update.message.reply_text(
            "⚠️ پیام سرویسی در پست ذخیره نمی‌شود.",
            reply_markup=POST_UPLOAD_CANCEL_MENU,
        )
        return POST_UPLOAD_MESSAGES

    post_upload = context.user_data.setdefault("post_upload", {"messages": []})
    post_upload.setdefault("messages", []).append(
        {
            "chat_id": update.message.chat_id,
            "message_id": update.message.message_id,
        }
    )
    count = len(post_upload["messages"])
    await update.message.reply_text(
        f"📎 پیام شماره {count} ذخیره شد. ادامه بده یا «✅ تمام شد» را بزن.",
        reply_markup=POST_UPLOAD_CANCEL_MENU,
    )
    return POST_UPLOAD_MESSAGES


async def cancel_posts(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    # B9: /cancel → بازگشت به لیست پست‌ها (پنل باز می‌ماند)
    context.user_data.pop("post_upload", None)
    context.user_data["post_manage"] = {"page": 0}
    await update.message.reply_text(
        "❌ عملیات لغو شد.",
        reply_markup=main_menu_for(update.effective_user.id),
    )
    await show_post_list(update.message.chat_id, context, 0)
    return POST_MANAGE_LIST


async def show_post_list(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    page: int = 0,
) -> None:
    manage = context.user_data.get("post_manage", {})
    items = db.get_all_posts(page)
    total = db.count_all_posts()
    pages = total_pages(total, config.PAGE_SIZE)

    if not items:
        text = "📋 لیست پست‌ها:\n\nهنوز پستی ثبت نشده است."
        keyboard = [
            [ib("📤 آپلود پست جدید", callback_data="pm_upload_new")],
            [ib("🏠 منوی اصلی", callback_data="pm_back_menu")],
        ]
    else:
        lines = ["📋 لیست پست‌ها:\n"]
        keyboard = [
            [ib("📤 آپلود پست جدید", callback_data="pm_upload_new")]
        ]

        delivery_stats = db.get_all_post_delivery_stats()
        for idx, item in enumerate(items, start=1):
            icon = "🟢" if item["status"] == "active" else "🔴"
            # B4: شمار تحویل هر پست در لیست
            d_total = (
                delivery_stats.get(item["post_id"]) or {}
            ).get("total", 0)
            lines.append(
                f"{idx}. {icon} {item['post_name']} — 📥 {d_total}"
            )
            short = item["post_name"]
            if len(short) > 25:
                short = short[:22] + "..."
            keyboard.append(
                [
                    ib(
                        f"{idx}. {short}",
                        callback_data=f"pm_view:{item['post_id']}",
                        style="primary",
                    )
                ]
            )

        lines.append(f"\n📄 صفحه {page + 1} از {pages} ({total} پست)")
        text = "\n".join(lines)

        nav = build_pagination_row(
            page,
            pages,
            f"pm_page:{page - 1}",
            "pm_refresh",
            f"pm_page:{page + 1}",
        )
        if nav:
            keyboard.append(nav)

        keyboard.append(
            [ib("🏠 منوی اصلی", callback_data="pm_back_menu")]
        )

    msg_id = manage.get("list_message_id")
    new_id = await safe_edit_or_send(
        context, chat_id, text, InlineKeyboardMarkup(keyboard), msg_id
    )
    manage["list_message_id"] = new_id
    manage["page"] = page
    context.user_data["post_manage"] = manage


async def show_post_detail(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    post_id: str,
) -> None:
    post = db.get_post(post_id)
    if not post:
        await context.bot.send_message(chat_id, "❌ پست پیدا نشد.")
        return

    messages = db.get_post_messages(post_id)
    status_text = "فعال ✅" if post["status"] == "active" else "غیرفعال 🔴"
    link = await build_download_link(context, post_id)
    # B4: آمار تحویل پست
    deliveries = db.get_post_delivery_stats(post_id)

    text = (
        "📋 جزئیات پست:\n\n"
        f"📝 نام: {html.escape(post['post_name'])}\n"
        f"📨 تعداد پیام‌ها: {len(messages)}\n"
        f"📥 تحویل: {deliveries['total']} بار"
        f" | 👥 {deliveries['users']} کاربر یکتا\n"
        f"📊 وضعیت: {status_text}\n"
        f"👤 ایجاد کننده: {post['admin_id']}\n"
        f"📅 تاریخ ایجاد: {fmt_tehran(post['created_at'])}\n\n"
        f"🔗 لینک:\n<code>{link}</code>"
    )

    toggle_label = "🚫 غیرفعال کن" if post["status"] == "active" else "✅ فعال کن"

    keyboard = [
        [
            ib(toggle_label, callback_data=f"pm_toggle:{post_id}"),
            ib("🗑️ حذف", callback_data=f"pm_delete:{post_id}"),
        ],
        [
            ib("✏️ تغییر نام", callback_data=f"pm_rename:{post_id}"),
            ib(
                "📨 پیش‌نمایش پیام‌ها",
                callback_data=f"pm_preview:{post_id}",
            ),
        ],
        [
            ib("📋 بازگشت به لیست",
                                 callback_data="pm_back_list"),
            ib("🏠 منوی اصلی", callback_data="pm_back_menu"),
        ],
    ]

    manage = context.user_data.get("post_manage", {})
    msg_id = manage.get("detail_message_id")
    new_id = await safe_edit_or_send(
        context,
        chat_id,
        text,
        InlineKeyboardMarkup(keyboard),
        msg_id,
        parse_mode="HTML",
    )
    manage["detail_message_id"] = new_id
    manage["current_post"] = post_id
    context.user_data["post_manage"] = manage


async def preview_post(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    post_id: str,
) -> None:
    """B4: کپی پیام‌های پست (به ترتیب) در چت مدیر برای مرور محتوا.

    بدون admin_only: آرگومان اول chat_id است (نه Update) و تنها
    فراخوان آن (handle_post_manage_callback) خودش admin_only است.
    """
    post = db.get_post(post_id)
    messages = db.get_post_messages(post_id)
    if not post or not messages:
        await context.bot.send_message(
            chat_id, "❌ پیامی برای پیش‌نمایش وجود ندارد."
        )
        return

    await context.bot.send_message(
        chat_id,
        f"📨 پیش‌نمایش پست «{post['post_name']}» — {len(messages)} پیام:",
    )
    failed = 0
    for post_msg in messages:
        try:
            await context.bot.copy_message(
                chat_id=chat_id,
                from_chat_id=post_msg["chat_id"],
                message_id=post_msg["message_id"],
            )
        except TelegramError as err:
            failed += 1
            logger.error(
                "کپی پیام پست %s msg=%s ناموفق: %s",
                post_id,
                post_msg["message_id"],
                err,
            )
    if failed:
        await context.bot.send_message(
            chat_id,
            f"⚠️ {failed} پیام کپی نشد (احتمالاً پیام اصلی پاک شده است).",
        )


@admin_only
async def receive_post_rename(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """B4: دریافت نام جدید پست (state = POST_MANAGE_EDIT)."""
    chat_id = update.message.chat_id
    text = (update.message.text or "").strip()
    manage = context.user_data.get("post_manage", {})
    post_id = manage.get("rename_post_id")

    if not post_id:
        await update.message.reply_text("❌ اطلاعات تغییر نام نامعتبر است.")
        await show_post_list(chat_id, context, manage.get("page", 0))
        return POST_MANAGE_LIST

    if text in ("/cancel", "لغو"):
        manage.pop("rename_post_id", None)
        context.user_data["post_manage"] = manage
        await update.message.reply_text("❌ تغییر نام لغو شد.")
        await show_post_detail(chat_id, context, post_id)
        return POST_MANAGE_DETAIL

    if not text:
        await update.message.reply_text(
            "⚠️ نام نمی‌تواند خالی باشد — دوباره وارد کن."
        )
        return POST_MANAGE_EDIT

    if not db.rename_post(post_id, text):
        await update.message.reply_text("❌ پست پیدا نشد.")
        manage.pop("rename_post_id", None)
        context.user_data["post_manage"] = manage
        await show_post_list(chat_id, context, manage.get("page", 0))
        return POST_MANAGE_LIST

    manage.pop("rename_post_id", None)
    context.user_data["post_manage"] = manage
    await update.message.reply_text(f"✅ نام پست به «{text}» تغییر یافت.")
    await show_post_detail(chat_id, context, post_id)
    return POST_MANAGE_DETAIL


@admin_only
async def handle_post_manage_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id
    message_id = query.message.message_id
    data = query.data
    manage = context.user_data.get("post_manage", {})

    if data == "pm_back_menu":
        # B9: خروج به منوی اصلی (منوی میانی پست‌ها حذف شد)
        await query.edit_message_text("✅ به منوی اصلی بازگشتید.")
        await go_to_main_menu(context, chat_id)
        return ConversationHandler.END

    if data == "pm_upload_new":
        # B9: آپلود پست جدید از داخل لیست
        context.user_data["post_upload"] = {"messages": []}
        await context.bot.send_message(
            chat_id,
            "📝 نام پست را وارد کن:",
            reply_markup=POST_CANCEL_MENU,
        )
        return POST_UPLOAD_NAME

    if data in ("pm_back_list", "pm_refresh"):
        # رفع باگ: پیام فعلی (جزئیات) درجا به لیست تبدیل می‌شود؛
        # ویرایش پیام لیستِ قدیمی با محتوای یکسان «not modified»
        # می‌خورد و برای کاربر نامرئی بود.
        manage["list_message_id"] = message_id
        manage.pop("detail_message_id", None)
        context.user_data["post_manage"] = manage
        await show_post_list(chat_id, context, manage.get("page", 0))
        return POST_MANAGE_LIST

    if data.startswith("pm_page:"):
        page = max(0, int(data.split(":", 1)[1]))
        await show_post_list(chat_id, context, page)
        return POST_MANAGE_LIST

    if data.startswith("pm_view:"):
        post_id = data.split(":", 1)[1]
        # رفع باگ: جزئیات درجا جای پیام لیست باز می‌شود (تک‌پیامی)
        manage["detail_message_id"] = message_id
        context.user_data["post_manage"] = manage
        await show_post_detail(chat_id, context, post_id)
        return POST_MANAGE_DETAIL

    if data.startswith("pm_toggle:"):
        post_id = data.split(":", 1)[1]
        if db.toggle_post_status(post_id):
            await query.answer("✅ وضعیت تغییر کرد.")
        else:
            await query.answer("❌ خطا در تغییر وضعیت.")
        await show_post_detail(chat_id, context, post_id)
        return POST_MANAGE_DETAIL

    if data.startswith("pm_rename:"):
        # B4: تغییر نام پست
        post_id = data.split(":", 1)[1]
        post = db.get_post(post_id)
        if not post:
            await query.answer("❌ پست پیدا نشد.")
            await show_post_list(chat_id, context, manage.get("page", 0))
            return POST_MANAGE_LIST
        manage["rename_post_id"] = post_id
        context.user_data["post_manage"] = manage
        await query.edit_message_text(
            f"✏️ نام فعلی پست: {post['post_name']}\n\n"
            "نام جدید را وارد کن (برای لغو /cancel را تایپ کن):"
        )
        return POST_MANAGE_EDIT

    if data.startswith("pm_preview:"):
        # B4: پیش‌نمایش — پیام‌های پست در همین چت کپی می‌شوند
        post_id = data.split(":", 1)[1]
        await preview_post(chat_id, context, post_id)
        return POST_MANAGE_DETAIL

    if data.startswith("pm_delete:"):
        post_id = data.split(":", 1)[1]
        keyboard = [
            [
                ib(
                    "✅ بله، حذف کن",
                    callback_data=f"pm_confirm_delete:{post_id}",
                ),
                ib(
                    "❌ خیر", callback_data=f"pm_view:{post_id}"),
            ]
        ]
        await query.edit_message_text(
            "⚠️ مطمئنی می‌خواهی این پست را حذف کنی?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return POST_MANAGE_DETAIL

    if data.startswith("pm_confirm_delete:"):
        post_id = data.split(":", 1)[1]
        if db.delete_post(post_id):
            await query.edit_message_text("✅ پست حذف شد.")
            manage.pop("detail_message_id", None)
            context.user_data["post_manage"] = manage
            await show_post_list(chat_id, context, manage.get("page", 0))
            return POST_MANAGE_LIST
        await query.answer("❌ خطا در حذف.")
        return POST_MANAGE_DETAIL

    await query.answer(Msg.INVALID_COMMAND)
    return POST_MANAGE_LIST
