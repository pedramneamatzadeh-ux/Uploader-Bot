from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from ..config import config
from ..constants import MANAGE_STATS
from ..database import db
from ..decorators import admin_only
from ..keyboards import build_pagination_row
from ..utils import fmt_tehran, go_to_main_menu, safe_edit_or_send, total_pages


@admin_only
async def show_stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    await show_stats_menu(update.message.chat_id, context)
    return MANAGE_STATS


async def show_stats_menu(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    message_id: int = None,
) -> None:
    text = "📊 **بخش آمار و گزارشات**\n\nگزینه مورد نظر را انتخاب کنید:"
    keyboard = [
        [InlineKeyboardButton("👥 کاربران ربات", callback_data="stats_users")],
        [InlineKeyboardButton("🏆 انیمه‌های پرطرفدار",
                              callback_data="stats_top_anime")],
        [InlineKeyboardButton("🔴 گزارش‌های خرابی",
                              callback_data="stats_reports")],
        [InlineKeyboardButton("🏠 بازگشت به منوی اصلی",
                              callback_data="stats_back_main")],
    ]
    await safe_edit_or_send(
        context,
        chat_id,
        text,
        InlineKeyboardMarkup(keyboard),
        message_id,
        parse_mode="Markdown",
    )


async def show_users_stats(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    page: int = 0,
    message_id: int = None,
) -> None:
    users = db.get_all_users()
    total = len(users)
    per_page = config.USERS_PAGE_SIZE
    start = page * per_page
    page_users = users[start: start + per_page]

    lines = [
        "👥 **لیست کاربران ربات**\n",
        f"📈 تعداد کل کاربران: {total}\n",
        "─" * 25 + "\n",
    ]

    for idx, user in enumerate(page_users, start=start + 1):
        name = user["first_name"] or "نامشخص"
        if user["last_name"]:
            name += f" {user['last_name']}"
        username = f"@{user['username']}" if user["username"] else "بدون یوزرنیم"
        lines.append(f"{idx}. {name}")
        lines.append(f"   🆔 {user['user_id']} | {username}")
        lines.append(f"   📅 آخرین فعالیت: {fmt_tehran(user['last_activity'])}\n")

    pages = total_pages(total, per_page)
    lines.append(f"\n📄 صفحه {page + 1} از {pages}")

    keyboard = []
    nav = build_pagination_row(
        page,
        pages,
        f"stats_users_page:{page - 1}",
        "stats_users",
        f"stats_users_page:{page + 1}",
    )
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton(
        "🔙 بازگشت", callback_data="stats_back")])

    await safe_edit_or_send(
        context,
        chat_id,
        "\n".join(lines),
        InlineKeyboardMarkup(keyboard),
        message_id,
        parse_mode="Markdown",
    )


async def show_top_anime_stats(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    message_id: int = None,
) -> None:
    top = db.get_top_anime(10)
    total = db.count_total_downloads()

    lines = [
        "🏆 **انیمه‌های پرطرفدار**\n",
        f"📥 تعداد کل دانلودها: {total}\n",
        "─" * 25 + "\n",
    ]

    if not top:
        lines.append("هنوز دانلودی ثبت نشده است.")
    else:
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        for idx, anime in enumerate(top, start=1):
            medal = medals.get(idx, f"{idx}.")
            lines.append(f"{medal} **{anime['anime_name']}**")
            lines.append(
                f"   📹 کیفیت: {anime['quality']} | 📥 دانلود: {anime['download_count']}\n"
            )

    keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="stats_back")]]
    await safe_edit_or_send(
        context,
        chat_id,
        "\n".join(lines),
        InlineKeyboardMarkup(keyboard),
        message_id,
        parse_mode="Markdown",
    )


async def show_reports_stats(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    page: int = 0,
    message_id: int = None,
) -> None:
    reports = db.get_all_reports()
    pending = [r for r in reports if r["status"] == "pending"]
    resolved = [r for r in reports if r["status"] == "resolved"]

    total = len(reports)
    per_page = config.REPORTS_PAGE_SIZE
    start = page * per_page
    page_reports = reports[start: start + per_page]

    lines = [
        "🔴 **گزارش‌های خرابی لینک**\n",
        f"📊 کل گزارش‌ها: {total}",
        f"⏳ در انتظار بررسی: {len(pending)}",
        f"✅ بررسی شده: {len(resolved)}\n",
        "─" * 25 + "\n",
    ]

    if not page_reports:
        lines.append("گزارشی یافت نشد.")
    else:
        for idx, report in enumerate(page_reports, start=start + 1):
            icon = "⏳" if report["status"] == "pending" else "✅"
            lines.append(
                f"{idx}. {icon} **{report['anime_name']}** ({report['quality']})")
            lines.append(f"   🆔 کاربر: {report['user_id']}")
            lines.append(f"   📅 تاریخ: {fmt_tehran(report['created_at'])}")
            lines.append(f"   🆔 گزارش: {report['id']}\n")

    pages = total_pages(total, per_page)
    lines.append(f"\n📄 صفحه {page + 1} از {pages}")

    keyboard = []
    for report in page_reports:
        if report["status"] == "pending":
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"✅ حل شد #{report['id']}",
                        callback_data=f"resolve_report:{report['id']}",
                    )
                ]
            )

    nav = build_pagination_row(
        page,
        pages,
        f"stats_reports_page:{page - 1}",
        "stats_reports",
        f"stats_reports_page:{page + 1}",
    )
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton(
        "🔙 بازگشت", callback_data="stats_back")])

    await safe_edit_or_send(
        context,
        chat_id,
        "\n".join(lines),
        InlineKeyboardMarkup(keyboard),
        message_id,
        parse_mode="Markdown",
    )


@admin_only
async def handle_stats_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id
    message_id = query.message.message_id
    data = query.data

    if data == "stats_back_main":
        await query.edit_message_text("✅ به منوی اصلی بازگشتید.")
        await go_to_main_menu(context, chat_id)
        return ConversationHandler.END

    if data == "stats_back":
        await show_stats_menu(chat_id, context, message_id)
    elif data == "stats_users":
        await show_users_stats(chat_id, context, 0, message_id)
    elif data.startswith("stats_users_page:"):
        await show_users_stats(chat_id, context, int(data.split(":")[1]), message_id)
    elif data == "stats_top_anime":
        await show_top_anime_stats(chat_id, context, message_id)
    elif data == "stats_reports":
        await show_reports_stats(chat_id, context, 0, message_id)
    elif data.startswith("stats_reports_page:"):
        await show_reports_stats(chat_id, context, int(data.split(":")[1]), message_id)
    elif data.startswith("resolve_report:"):
        report_id = int(data.split(":")[1])
        if db.update_report_status(report_id, "resolved"):
            await query.answer("✅ گزارش به عنوان حل‌شده علامت‌گذاری شد.")
            await show_reports_stats(chat_id, context, 0, message_id)
        else:
            await query.answer("❌ خطا در بروزرسانی وضعیت.")

    return MANAGE_STATS
