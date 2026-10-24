import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes, ConversationHandler

from ..config import config
from ..constants import MANAGE_STATS, Msg
from ..database import db
from ..decorators import admin_only
from ..keyboards import build_pagination_row
from ..utils import (
    build_download_link,
    fmt_tehran,
    format_anime_title,
    go_to_main_menu,
    safe_edit_or_send,
    total_pages,
)


logger = logging.getLogger(__name__)

# R8b: تعداد گروه‌ها در هر صفحه «پرطرفدار» (صفحه‌بندی «نمایش بیشتر»)
TOP_PAGE_SIZE = 10


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

    # R8a: آخرین دانلود + شمار یکتای فصل/پارت برای هر کاربر
    download_info = db.get_user_download_info()

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
        lines.append(f"   📅 آخرین فعالیت: {fmt_tehran(user['last_activity'])}")
        info = download_info.get(user["user_id"]) or {}
        last = info.get("last")
        if last:
            title = format_anime_title(
                last["anime_name"],
                last.get("season_num"),
                last.get("part_num"),
                last.get("anime_type"),
                display=db.get_display_for(
                    last["anime_name"],
                    last.get("season_num"),
                    last.get("part_num"),
                ),
            )
            lines.append(
                f"   🎬 آخرین دانلود: {title} ({last['quality']})"
            )
            lines.append(
                f"      🕒 {fmt_tehran(last['downloaded_at'])}"
                f" | 📥 {info.get('uniq', 0)} فصل/پارت (یکتا)\n"
            )
        else:
            lines.append("   🎬 آخرین دانلود: —\n")

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
    page: int = 0,
    message_id: int = None,
) -> None:
    # R8b: گروه‌بندی بر (نام، نوع، فصل، پارت) — همه کیفیت‌ها با هم؛
    # هر کاربر برای هر فصل/پارت فقط یک‌بار شمرده می‌شود.
    total = db.count_total_downloads()
    group_count = db.count_top_anime_groups()
    top = db.get_top_anime_grouped(TOP_PAGE_SIZE, page * TOP_PAGE_SIZE)

    lines = [
        "🏆 **انیمه‌های پرطرفدار**\n",
        f"📥 تعداد کل دانلودها: {total}",
        "👤 هر کاربر برای هر فصل/پارت فقط یک‌بار شمرده می‌شود.\n",
        "─" * 25 + "\n",
    ]

    if not top:
        lines.append("هنوز دانلودی ثبت نشده است.")
    else:
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        start = page * TOP_PAGE_SIZE
        for idx, anime in enumerate(top, start=start + 1):
            medal = medals.get(idx, f"{idx}.")
            title = format_anime_title(
                anime["anime_name"],
                anime.get("season_num"),
                anime.get("part_num"),
                anime.get("anime_type"),
                display=db.get_display_for(
                    anime["anime_name"],
                    anime.get("season_num"),
                    anime.get("part_num"),
                ),
            )
            lines.append(f"{medal} **{title}**")
            lines.append(
                f"   👥 {anime['users_count']} نفر"
                f" | 📥 {anime['total_count']} بار\n"
            )

    pages = total_pages(group_count, TOP_PAGE_SIZE)
    lines.append(f"\n📄 صفحه {page + 1} از {pages}")

    keyboard = []
    nav = build_pagination_row(
        page,
        pages,
        f"stats_top_page:{page - 1}",
        f"stats_top_page:{page}",
        f"stats_top_page:{page + 1}",
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


async def show_reports_stats(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    page: int = 0,
    message_id: int = None,
    only_pending: bool = False,
) -> None:
    reports = db.get_all_reports()
    pending = [r for r in reports if r["status"] == "pending"]
    resolved = [r for r in reports if r["status"] == "resolved"]

    # پیشنهاد ۵ (R8+): فیلتر «فقط در انتظار / همه»
    listed = pending if only_pending else reports
    f = "p" if only_pending else "a"

    total = len(listed)
    per_page = config.REPORTS_PAGE_SIZE
    start = page * per_page
    page_reports = listed[start: start + per_page]

    lines = [
        "🔴 **گزارش‌های خرابی لینک**\n",
        f"📊 کل گزارش‌ها: {len(reports)}",
        f"⏳ در انتظار بررسی: {len(pending)}",
        f"✅ بررسی شده: {len(resolved)}\n",
        "─" * 25 + "\n",
    ]

    if not page_reports:
        lines.append(
            "گزارش در انتظاری وجود ندارد. 🎉"
            if only_pending
            else "گزارشی یافت نشد."
        )
    else:
        for idx, report in enumerate(page_reports, start=start + 1):
            icon = "⏳" if report["status"] == "pending" else "✅"
            # 📝 یعنی کاربر توضیحات نوشته است (R8c)
            note = " 📝" if report.get("report_text") else ""
            lines.append(
                f"{idx}. {icon} **{report['anime_name']}** "
                f"({report['quality']}){note}"
            )
            lines.append(f"   🆔 کاربر: {report['user_id']}")
            lines.append(f"   📅 تاریخ: {fmt_tehran(report['created_at'])}")
            lines.append(f"   🆔 گزارش: {report['id']}\n")

    pages = total_pages(total, per_page)
    lines.append(f"\n📄 صفحه {page + 1} از {pages}")

    keyboard = []
    if only_pending:
        keyboard.append([InlineKeyboardButton(
            "📋 همه گزارش‌ها",
            callback_data="stats_reports_filter:all",
        )])
    else:
        keyboard.append([InlineKeyboardButton(
            "⏳ فقط در انتظار",
            callback_data="stats_reports_filter:pending",
        )])

    # R8c: «حل شد» + «جزئیات» در یک ردیف برای هر گزارش
    for report in page_reports:
        row = []
        if report["status"] == "pending":
            row.append(
                InlineKeyboardButton(
                    f"✅ حل شد #{report['id']}",
                    callback_data=(
                        f"resolve_report:{report['id']}:{page}:{f}"
                    ),
                )
            )
        row.append(
            InlineKeyboardButton(
                f"🔍 جزئیات #{report['id']}",
                callback_data=(
                    f"report_detail:{report['id']}:{page}:{f}"
                ),
            )
        )
        keyboard.append(row)

    nav = build_pagination_row(
        page,
        pages,
        f"stats_reports_go:{page - 1}:{f}",
        f"stats_reports_go:{page}:{f}",
        f"stats_reports_go:{page + 1}:{f}",
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


async def show_report_detail(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    report_id: int,
    page: int = 0,
    f: str = "a",
    message_id: int = None,
) -> None:
    """R8c: صفحه جزئیات یک گزارش — اطلاعات کامل فایل + توضیحات کاربر."""
    back = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔙 بازگشت به گزارش‌ها",
                    callback_data=f"stats_reports_go:{page}:{f}",
                )
            ]
        ]
    )

    report = db.get_report_by_id(report_id)
    if not report:
        await safe_edit_or_send(
            context,
            chat_id,
            "❌ گزارش پیدا نشد.",
            back,
            message_id,
        )
        return

    title = format_anime_title(
        report["anime_name"],
        report.get("season_num"),
        report.get("part_num"),
        report.get("anime_type"),
        display=db.get_display_for(
            report["anime_name"],
            report.get("season_num"),
            report.get("part_num"),
        ),
    )
    uname = (
        f"@{report['reporter_username']}"
        if report.get("reporter_username")
        else "بدون یوزرنیم"
    )
    status_txt = (
        "⏳ در انتظار بررسی"
        if report["status"] == "pending"
        else "✅ حل‌شده"
    )
    channel = report.get("channel_chat_id") or "کانال پیش‌فرض"

    # بدون parse_mode: متن آزاد کاربر ممکن است مارک‌داون را بشکند.
    text = "\n".join(
        [
            f"🔍 جزئیات گزارش #{report['id']}",
            "─" * 25,
            f"🎬 انیمه: {title}",
            f"📹 کیفیت: {report['quality']}",
            f"📺 بازه قسمت: {report.get('episode_range') or '—'}",
            f"🗄️ کانال ذخیره: {channel}",
            f"📨 بازه پیام‌ها: {report.get('channel_msg_range') or '—'}",
            f"📁 وضعیت فایل: {report.get('upload_status') or '—'}",
            "─" * 25,
            f"👤 گزارش‌دهنده: {report['user_id']} | {uname}",
            f"📅 تاریخ: {fmt_tehran(report['created_at'])}",
            f"🚦 وضعیت: {status_txt}",
            "─" * 25,
            "📝 توضیحات:",
            report.get("report_text") or "توضیحی ثبت نشده است.",
        ]
    )

    await safe_edit_or_send(
        context,
        chat_id,
        text,
        back,
        message_id,
    )


async def _resolve_report(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    data: str,
) -> None:
    """R8c: حل‌شدن گزارش + اطلاع خصوصی به گزارش‌دهنده.

    نکته: answer این callback باید *اولین* پاسخ باشد (هر query فقط
    یک‌بار answer می‌شود) — برای همین در handle_stats_callback برای
    این شاخه answer عمومی فراخوانی نمی‌شود.
    """
    parts = data.split(":")
    report_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0
    only_pending = len(parts) > 3 and parts[3] == "p"

    report = db.get_report_by_id(report_id)

    if not db.update_report_status(report_id, "resolved"):
        await query.answer("❌ خطا در بروزرسانی وضعیت.")
        return

    notified = False
    if report:
        title = format_anime_title(
            report["anime_name"],
            report.get("season_num"),
            report.get("part_num"),
            report.get("anime_type"),
            display=db.get_display_for(
                report["anime_name"],
                report.get("season_num"),
                report.get("part_num"),
            ),
        )
        notice = Msg.REPORT_RESOLVED_NOTICE.format(
            title=f"{title} ({report['quality']})"
        )
        # R8f: لینک دانلود همان جلسه گزارش‌شده — کاربر با یک
        # ضربه فایل‌ها را دوباره دریافت می‌کند.
        try:
            link = await build_download_link(
                context, report["session_id"]
            )
            notice += f"\n\n🔗 {link}"
        except TelegramError:
            logger.warning(
                "ساخت لینک دانلود برای گزارش #%s ناموفق بود",
                report_id,
            )
        try:
            await context.bot.send_message(
                report["user_id"],
                notice,
            )
            notified = True
        except TelegramError:
            logger.warning(
                "ارسال اطلاع حل‌شدن گزارش #%s به کاربر %s ناموفق بود",
                report_id,
                report["user_id"],
            )

    if report is None:
        toast = Msg.REPORT_RESOLVED_TOAST_NONE
    elif notified:
        toast = Msg.REPORT_RESOLVED_TOAST_OK
    else:
        toast = Msg.REPORT_RESOLVED_TOAST_FAIL
    await query.answer(toast)

    await show_reports_stats(
        chat_id, context, page, message_id, only_pending
    )


@admin_only
async def handle_stats_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    data = query.data or ""

    chat_id = query.message.chat_id
    message_id = query.message.message_id

    # R8-fix: برای resolve_report جواب باید همراه toast و *اولین*
    # answer باشد — هر query فقط یک‌بار answer می‌شود.
    if not data.startswith("resolve_report:"):
        await query.answer()

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
        await show_top_anime_stats(chat_id, context, 0, message_id)
    elif data.startswith("stats_top_page:"):
        await show_top_anime_stats(
            chat_id, context, int(data.split(":")[1]), message_id
        )
    elif data == "stats_reports":
        await show_reports_stats(chat_id, context, 0, message_id)
    elif data.startswith("stats_reports_page:"):
        await show_reports_stats(chat_id, context, int(data.split(":")[1]), message_id)
    elif data.startswith("stats_reports_filter:"):
        await show_reports_stats(
            chat_id,
            context,
            0,
            message_id,
            only_pending=data.split(":")[1] == "pending",
        )
    elif data.startswith("stats_reports_go:"):
        parts = data.split(":")
        await show_reports_stats(
            chat_id,
            context,
            int(parts[1]),
            message_id,
            only_pending=len(parts) > 2 and parts[2] == "p",
        )
    elif data.startswith("report_detail:"):
        parts = data.split(":")
        await show_report_detail(
            chat_id,
            context,
            int(parts[1]),
            int(parts[2]) if len(parts) > 2 else 0,
            parts[3] if len(parts) > 3 else "a",
            message_id,
        )
    elif data.startswith("resolve_report:"):
        await _resolve_report(query, context, chat_id, message_id, data)

    return MANAGE_STATS
