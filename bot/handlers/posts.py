import logging
import sqlite3
import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from ..config import config
from ..constants import (
    POST_MANAGE_DETAIL,
    POST_MANAGE_LIST,
    POST_MENU,
    POST_UPLOAD_MESSAGES,
    POST_UPLOAD_NAME,
    Msg,
)
from ..database import db
from ..decorators import admin_only
from ..keyboards import (
    POST_CANCEL_MENU,
    POST_MENU_MARKUP,
    POST_UPLOAD_CANCEL_MENU,
    build_pagination_row,
    main_menu_for,
)
from ..utils import build_download_link, fmt_tehran, safe_edit_or_send, total_pages


logger = logging.getLogger(__name__)


@admin_only
async def start_posts(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    context.user_data.pop("post_upload", None)
    context.user_data.pop("post_manage", None)
    await update.message.reply_text(
        "📝 بخش پست‌ها:",
        reply_markup=POST_MENU_MARKUP,
    )
    return POST_MENU


@admin_only
async def post_menu_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    text = update.message.text.strip()

    if text == "📤 آپلود پست":
        context.user_data["post_upload"] = {"messages": []}
        await update.message.reply_text(
            "📝 نام پست را وارد کن:",
            reply_markup=POST_CANCEL_MENU,
        )
        return POST_UPLOAD_NAME

    if text == "📋 مدیریت پست‌ها":
        context.user_data["post_manage"] = {"page": 0}
        await show_post_list(update.message.chat_id, context, 0)
        return POST_MANAGE_LIST

    if text == "بازگشت به منوی اصلی":
        context.user_data.pop("post_upload", None)
        context.user_data.pop("post_manage", None)
        await update.message.reply_text(
            "✅ به منوی اصلی بازگشتید.",
            reply_markup=main_menu_for(update.effective_user.id),
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "لطفاً یکی از گزینه‌ها را انتخاب کن.",
        reply_markup=POST_MENU_MARKUP,
    )
    return POST_MENU


@admin_only
async def receive_post_name(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    text = update.message.text.strip()

    if text == "لغو":
        context.user_data.pop("post_upload", None)
        await update.message.reply_text(
            "❌ آپلود پست لغو شد.",
            reply_markup=POST_MENU_MARKUP,
        )
        return POST_MENU

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
        context.user_data.pop("post_upload", None)
        await update.message.reply_text(
            "❌ آپلود پست لغو شد.",
            reply_markup=POST_MENU_MARKUP,
        )
        return POST_MENU

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
                reply_markup=POST_MENU_MARKUP,
            )
            context.user_data.pop("post_upload", None)
            return POST_MENU

        link = await build_download_link(context, post_id)
        await update.message.reply_text(
            f"✅ پست «{post_upload['name']}» با موفقیت ذخیره شد!\n\n"
            f"📨 تعداد پیام‌ها: {len(messages)}\n\n"
            f"🔗 لینک پست:\n<code>{link}</code>",
            parse_mode="HTML",
            reply_markup=POST_MENU_MARKUP,
        )
        context.user_data.pop("post_upload", None)
        return POST_MENU

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
    context.user_data.pop("post_upload", None)
    context.user_data.pop("post_manage", None)
    await update.message.reply_text(
        "❌ عملیات لغو شد.",
        reply_markup=POST_MENU_MARKUP,
    )
    return POST_MENU


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
            [InlineKeyboardButton("🏠 بازگشت", callback_data="pm_back_menu")],
        ]
    else:
        lines = ["📋 لیست پست‌ها:\n"]
        keyboard = []

        for idx, item in enumerate(items, start=1):
            icon = "🟢" if item["status"] == "active" else "🔴"
            lines.append(f"{idx}. {icon} {item['post_name']}")
            short = item["post_name"]
            if len(short) > 25:
                short = short[:22] + "..."
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"{idx}. {short}",
                        callback_data=f"pm_view:{item['post_id']}",
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
            [InlineKeyboardButton("🏠 بازگشت", callback_data="pm_back_menu")]
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

    text = (
        "📋 جزئیات پست:\n\n"
        f"📝 نام: {post['post_name']}\n"
        f"📨 تعداد پیام‌ها: {len(messages)}\n"
        f"📊 وضعیت: {status_text}\n"
        f"👤 ایجاد کننده: {post['admin_id']}\n"
        f"📅 تاریخ ایجاد: {fmt_tehran(post['created_at'])}\n\n"
        f"🔗 لینک:\n<code>{link}</code>"
    )

    toggle_label = "🚫 غیرفعال کن" if post["status"] == "active" else "✅ فعال کن"

    keyboard = [
        [
            InlineKeyboardButton(
                toggle_label, callback_data=f"pm_toggle:{post_id}"),
            InlineKeyboardButton(
                "🗑️ حذف", callback_data=f"pm_delete:{post_id}"),
        ],
        [
            InlineKeyboardButton("📋 بازگشت به لیست",
                                 callback_data="pm_back_list"),
            InlineKeyboardButton("🏠 منو", callback_data="pm_back_menu"),
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


@admin_only
async def handle_post_manage_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id
    data = query.data
    manage = context.user_data.get("post_manage", {})

    if data == "pm_back_menu":
        await query.edit_message_text("✅ به منوی پست‌ها برگشتید.")
        await context.bot.send_message(
            chat_id,
            "📝 بخش پست‌ها:",
            reply_markup=POST_MENU_MARKUP,
        )
        return POST_MENU

    if data in ("pm_back_list", "pm_refresh"):
        await show_post_list(chat_id, context, manage.get("page", 0))
        return POST_MANAGE_LIST

    if data.startswith("pm_page:"):
        page = max(0, int(data.split(":", 1)[1]))
        await show_post_list(chat_id, context, page)
        return POST_MANAGE_LIST

    if data.startswith("pm_view:"):
        post_id = data.split(":", 1)[1]
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

    if data.startswith("pm_delete:"):
        post_id = data.split(":", 1)[1]
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ بله، حذف کن",
                    callback_data=f"pm_confirm_delete:{post_id}",
                ),
                InlineKeyboardButton(
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
