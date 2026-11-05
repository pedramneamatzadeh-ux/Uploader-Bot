import html
import logging
import os

from telegram import InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes, ConversationHandler

from ..config import config
from ..constants import ALL_QUALITIES, MANAGE_STATS, Msg
from ..database import db
from ..decorators import admin_only
from ..keyboards import build_pagination_row, ib
from ..utils import (
    build_download_link,
    count_range_messages,
    fmt_tehran,
    format_anime_title,
    go_to_main_menu,
    period_boundaries,
    safe_edit_or_send,
    total_pages,
)


logger = logging.getLogger(__name__)

# R8b: تعداد گروه‌ها در هر صفحه «پرطرفدار» (صفحه‌بندی «نمایش بیشتر»)
TOP_PAGE_SIZE = 10


def _display_for_row(row) -> str:
    """B1: نام ظاهری مؤثر — alias سطح لینک اولویت دارد (ردیف‌هایی که
    session_id دارند: آخرین دانلود کاربر، گزارش‌ها)، وگرنه زنجیرهٔ
    فصل/پارت → سطح-نام → نام واقعی."""
    sid = row.get("session_id")
    if sid:
        effective = db.get_effective_display_for_link(sid)
        if effective:
            return effective
    return db.get_display_for(
        row["anime_name"],
        row.get("season_num"),
        row.get("part_num"),
    )


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
    text = "📊 <b>بخش آمار و گزارشات</b>\n\nگزینه مورد نظر را انتخاب کنید:"
    keyboard = [
        # B6: منوی دو ستونی
        [
            ib("👥 کاربران", callback_data="stats_users"),
            ib("🏆 پرطرفدار", callback_data="stats_top_anime"),
        ],
        [
            ib("📅 دوره‌ای", callback_data="stats_periods"),
            ib("🔴 گزارش‌ها", callback_data="stats_reports"),
        ],
        [
            ib("🗂️ آمار دیتابیس", callback_data="stats_db"),
            ib("📈 آمار آپلود", callback_data="stats_uploads"),
        ],
        [ib("🏠 بازگشت به منوی اصلی", callback_data="stats_back_main")],
    ]
    await safe_edit_or_send(
        context,
        chat_id,
        text,
        InlineKeyboardMarkup(keyboard),
        message_id,
        parse_mode="HTML",
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
        "👥 <b>لیست کاربران ربات</b>\n",
        f"📈 تعداد کل کاربران: {total}\n",
        "─" * 25 + "\n",
    ]

    for idx, user in enumerate(page_users, start=start + 1):
        name = user["first_name"] or "نامشخص"
        if user["last_name"]:
            name += f" {user['last_name']}"
        username = f"@{user['username']}" if user["username"] else "بدون یوزرنیم"
        lines.append(f"{idx}. {html.escape(name)}")
        lines.append(f"   🆔 {user['user_id']} | {html.escape(username)}")
        lines.append(f"   📅 آخرین فعالیت: {fmt_tehran(user['last_activity'])}")
        info = download_info.get(user["user_id"]) or {}
        last = info.get("last")
        if last:
            title = format_anime_title(
                last["anime_name"],
                last.get("season_num"),
                last.get("part_num"),
                last.get("anime_type"),
                display=_display_for_row(last),
            )
            lines.append(
                f"   🎬 آخرین دانلود: {html.escape(title)}"
                f" ({html.escape(last['quality'])})"
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
    keyboard.append([ib("🔙 بازگشت", callback_data="stats_back")])

    await safe_edit_or_send(
        context,
        chat_id,
        "\n".join(lines),
        InlineKeyboardMarkup(keyboard),
        message_id,
        parse_mode="HTML",
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
        "🏆 <b>انیمه‌های پرطرفدار</b>\n",
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
            lines.append(f"{medal} <b>{html.escape(title)}</b>")
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
    keyboard.append([ib("🔙 بازگشت", callback_data="stats_back")])

    await safe_edit_or_send(
        context,
        chat_id,
        "\n".join(lines),
        InlineKeyboardMarkup(keyboard),
        message_id,
        parse_mode="HTML",
    )


async def show_periods_menu(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    message_id: int = None,
) -> None:
    """R8d — صفحهٔ انتخاب دورهٔ آمار (تقویم شمسی، به وقت تهران)."""
    text = (
        "📅 <b>آمار دوره‌ای</b>\n\n"
        "دوره را انتخاب کنید (مرزها بر مبنای تقویم شمسی و وقت تهران):"
    )
    keyboard = [
        [ib("📅 هفتگی (از شنبهٔ این هفته)", callback_data="stats_period:w")],
        [ib("📆 ماهانه (از ۱م ماه جاری)", callback_data="stats_period:m")],
        [ib("🗓 سالانه (از ۱ فروردین)", callback_data="stats_period:y")],
        [ib("🔙 بازگشت", callback_data="stats_back")],
    ]
    await safe_edit_or_send(
        context,
        chat_id,
        text,
        InlineKeyboardMarkup(keyboard),
        message_id,
        parse_mode="HTML",
    )


async def show_period_stats(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    period: str,
    message_id: int = None,
) -> None:
    """R8d — کارت آمار یک دوره: خلاصه + مقایسه با دورهٔ قبل + ۱۰ پرطرفدار."""
    bounds = period_boundaries(period)
    current = db.get_period_stats(bounds["start"])
    previous = db.get_period_stats(
        bounds["prev_start"], end=bounds["prev_end"]
    )

    def _signed(value: int) -> str:
        return f"+{value}" if value > 0 else str(value)

    d_total = current["total"] - previous["total"]
    d_users = current["users"] - previous["users"]

    lines = [
        f"📅 <b>آمار {bounds['title']}</b>\n",
        f"🗓 {bounds['label']} — به وقت تهران",
        "─" * 25,
        f"📥 کل دانلودها: {current['total']}",
        f"👥 کاربران یکتا: {current['users']}",
        f"🎬 فصل/پارت یکتا: {current['groups']}",
        (
            f"📈 نسبت به دورهٔ قبل ({bounds['prev_label']}):"
            f" 📥 {_signed(d_total)} | 👥 {_signed(d_users)}\n"
        ),
        "─" * 25 + "\n",
        "🏆 <b>۱۰ پرطرفدار دوره:</b>\n",
    ]

    if not current["top"]:
        lines.append("در این دوره دانلودی ثبت نشده است.")
    else:
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        for idx, anime in enumerate(current["top"], start=1):
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
            lines.append(f"{medal} <b>{html.escape(title)}</b>")
            lines.append(
                f"   👥 {anime['users_count']} نفر"
                f" | 📥 {anime['total_count']} بار\n"
            )

    keyboard = [
        [ib("🔙 بازگشت", callback_data="stats_periods")],
    ]

    await safe_edit_or_send(
        context,
        chat_id,
        "\n".join(lines),
        InlineKeyboardMarkup(keyboard),
        message_id,
        parse_mode="HTML",
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
        "🔴 <b>گزارش‌های خرابی لینک</b>\n",
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
                f"{idx}. {icon} <b>{html.escape(report['anime_name'])}</b> "
                f"({html.escape(report['quality'])}){note}"
            )
            lines.append(f"   🆔 کاربر: {report['user_id']}")
            lines.append(f"   📅 تاریخ: {fmt_tehran(report['created_at'])}")
            lines.append(f"   🆔 گزارش: {report['id']}\n")

    pages = total_pages(total, per_page)
    lines.append(f"\n📄 صفحه {page + 1} از {pages}")

    keyboard = []
    if only_pending:
        keyboard.append([ib("📋 همه گزارش‌ها", callback_data="stats_reports_filter:all")])
    else:
        keyboard.append([ib("⏳ فقط در انتظار", callback_data="stats_reports_filter:pending")])

    # R8c: «حل شد» + «جزئیات» در یک ردیف برای هر گزارش
    for report in page_reports:
        row = []
        if report["status"] == "pending":
            row.append(
                ib(f"✅ حل شد #{report['id']}", callback_data=(
                        f"resolve_report:{report['id']}:{page}:{f}"
                    ))
            )
        row.append(
            ib(f"🔍 جزئیات #{report['id']}", callback_data=(
                    f"report_detail:{report['id']}:{page}:{f}"
                ))
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
    keyboard.append([ib("🔙 بازگشت", callback_data="stats_back")])

    await safe_edit_or_send(
        context,
        chat_id,
        "\n".join(lines),
        InlineKeyboardMarkup(keyboard),
        message_id,
        parse_mode="HTML",
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
                ib("🔙 بازگشت به گزارش‌ها", callback_data=f"stats_reports_go:{page}:{f}")
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
        display=_display_for_row(report),
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

    # بدون parse_mode: متن آزاد کاربر خام نمایش داده می‌شود (ایمن).
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
        # B21: اطلاع مرتب با جزئیات کامل — نام/فصل/پارت/قسمت/کیفیت
        name = _display_for_row(report) or report["anime_name"]
        detail_lines = [f"🎬 «{name}»"]
        season = (report.get("season_num") or "").strip()
        part = (report.get("part_num") or "").strip()
        if season:
            if (report.get("anime_type") or "") == "سینمایی":
                detail_lines.append(f"📽 سینمایی شماره {season}")
            else:
                season_line = f"📚 فصل {season}"
                if part:
                    season_line += f" | پارت {part}"
                detail_lines.append(season_line)
        episode_range = (report.get("episode_range") or "").strip()
        # برای سینمایی، episode_range placeholder («1») است — نشان نده
        if episode_range and (report.get("anime_type") or "") != "سینمایی":
            detail_lines.append(f"📺 قسمت: {episode_range}")
        detail_lines.append(f"🎞 کیفیت: {report['quality']}")
        notice = Msg.REPORT_RESOLVED_NOTICE.format(
            details="\n".join(detail_lines)
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


# ============================================================================
# R13 — آمار دیتابیس: کارت مرور + لیست‌های جزئیات
# ============================================================================
_DB_LIST_PAGE_SIZE = 10


def _db_group_label(name, season, part, is_cinema):
    """برچسب گروه برای لیست‌های آمار (HTML-escape شده)."""
    name = html.escape(name or "")
    season = html.escape(str(season or "").strip())
    part = html.escape(str(part or "").strip())
    if is_cinema:
        return f"«{name}» — سینمایی شماره {season or 'نامشخص'}"
    label = f"«{name}» — فصل {season or 'نامشخص'}"
    if part:
        label += f" | پارت {part}"
    return label


def _db_sort_key(key):
    name, season, part, _is_cinema = key
    return (
        name,
        int(season) if season.isdigit() else 0,
        int(part) if part.isdigit() else 0,
        part,
    )


def _db_stats_collect():
    """گروه‌های فیزیکی را با نام ظاهری مؤثر ادغام می‌کند (R12).

    خروجی: dict با کلیدهای groups/series/movies/bluray.
    """
    groups = {}
    for row in db.get_stats_groups():
        display = db.get_display_for(
            row["anime_name"], row["season_num"], row["part_num"]
        )
        is_cinema = (row["anime_type"] or "") == "سینمایی"
        key = (
            display,
            (row["season_num"] or "").strip(),
            (row["part_num"] or "").strip(),
            is_cinema,
        )
        item = groups.setdefault(key, {"links": 0, "bluray": 0})
        item["links"] += row["cnt"]
        item["bluray"] = max(item["bluray"], int(row["bluray"] or 0))

    bluray = [(k, groups[k]) for k in groups if groups[k]["bluray"]]
    bluray.sort(key=lambda kv: _db_sort_key(kv[0]))
    return {
        "groups": groups,
        "series": [k for k in groups if not k[3]],
        "movies": [k for k in groups if k[3]],
        "bluray": bluray,
        # R14: نام‌های ظاهری یکتا = «تعداد کل انیمه‌ها»
        "titles": {k[0] for k in groups},
    }


async def show_db_stats(chat_id, context, message_id=None):
    """R13: کارت مرور آمار دیتابیس — همهٔ اعداد کلیدی در یک نگاه."""
    data = _db_stats_collect()
    total_links = db.count_all_uploads()
    # R14: کل فایل‌ها = جمع بازهٔ پیام‌های کانالِ همهٔ لینک‌ها
    total_files = sum(
        count_range_messages(r) for r in db.get_upload_ranges()
    )
    n_air = db.count_ongoing_animes(active_only=True)
    n_fin = db.count_ongoing_animes() - n_air
    db_label = html.escape(
        os.path.basename(getattr(db, "path", "") or "") or "دیتابیس"
    )

    text = (
        f"📊 <b>آمار دیتابیس</b> — <code>{db_label}</code>\n\n"
        f"🔗 کل لینک‌ها: <b>{total_links}</b>\n"
        f"📁 کل فایل‌ها: <b>{total_files}</b>\n"
        f"🎌 کل انیمه‌ها: <b>{len(data['titles'])}</b>\n\n"
        f"📚 فصل/پارت (سریالی): <b>{len(data['series'])}</b>\n"
        f"🎬 آثار سینمایی: <b>{len(data['movies'])}</b>\n"
        f"🖨 گروه‌های بلوری: <b>{len(data['bluray'])}</b>\n\n"
        f"📮 پست‌ها: <b>{db.count_all_posts()}</b>\n"
        f"📝 خلاصه داستان: <b>{db.count_season_summaries()}</b>\n"
        f"📺 درحال پخش: <b>{n_air}</b>\n"
        f"🏁 اتمام پخش: <b>{n_fin}</b>\n\n"
        "<i>گروه‌ها بر مبنای نام ظاهری شمرده شده‌اند.</i>"
    )

    keyboard = [
        [ib("🎞 لینک هر کیفیت", callback_data="stats_db_qual")],
        [
            ib(
                f"🖨 لیست بلوری‌ها ({len(data['bluray'])})",
                callback_data="stats_db_bluray",
            )
        ],
        [
            ib(
                f"📺 درحال پخش ({n_air})",
                callback_data="stats_db_air",
            ),
            ib(
                f"🏁 اتمام پخش ({n_fin})",
                callback_data="stats_db_fin",
            ),
        ],
        [
            ib("🔄 تازه‌سازی", callback_data="stats_db"),
            ib("◀️ بازگشت", callback_data="stats_back"),
        ],
    ]

    await safe_edit_or_send(
        context,
        chat_id,
        text,
        InlineKeyboardMarkup(keyboard),
        message_id,
        parse_mode="HTML",
    )


async def show_db_quality_stats(chat_id, context, message_id=None):
    """R13: تعداد لینک هر کیفیت — ترتیب منوی کیفیت + درصد."""
    counts = db.get_quality_counts()
    total = sum(row["cnt"] for row in counts)
    by_quality = {
        (row["quality"] or "نامشخص"): row["cnt"] for row in counts
    }

    lines = [f"🎞 <b>لینک‌ها بر اساس کیفیت</b> — کل: {total}\n"]
    idx = 1
    for quality in ALL_QUALITIES:
        cnt = by_quality.pop(quality, 0)
        pct = f"{round(cnt * 100 / total)}%" if total else "—"
        lines.append(
            f"{idx}. {html.escape(quality)}: <b>{cnt}</b> ({pct})"
        )
        idx += 1
    # مقدار‌های خارج از منو (قدیمی) — نزولی بر اساس تعداد
    for quality, cnt in sorted(by_quality.items(), key=lambda kv: -kv[1]):
        pct = f"{round(cnt * 100 / total)}%" if total else "—"
        lines.append(
            f"{idx}. {html.escape(quality)}: <b>{cnt}</b> ({pct})"
        )
        idx += 1

    keyboard = [
        [ib("◀️ بازگشت", callback_data="stats_db")],
    ]
    await safe_edit_or_send(
        context,
        chat_id,
        "\n".join(lines),
        InlineKeyboardMarkup(keyboard),
        message_id,
        parse_mode="HTML",
    )


async def _show_db_paged_list(
    chat_id,
    context,
    title,
    prefix,
    items,
    page=0,
    message_id=None,
):
    """صفحه‌بندی مشترک لیست‌های آمار دیتابیس (R13)."""
    total = len(items)
    pages = max(
        1, (total + _DB_LIST_PAGE_SIZE - 1) // _DB_LIST_PAGE_SIZE
    )
    page = max(0, min(page, pages - 1))
    start = page * _DB_LIST_PAGE_SIZE
    chunk = items[start:start + _DB_LIST_PAGE_SIZE]

    lines = [f"{title} — {total}\n"]
    if not chunk:
        lines.append("موردی یافت نشد. 😕")
    for idx, (label, extra) in enumerate(chunk, start=start + 1):
        suffix = f" ({extra})" if extra else ""
        lines.append(f"{idx}. {label}{suffix}")
    if pages > 1:
        lines.append(f"\n📄 صفحه {page + 1} از {pages}")

    keyboard = [
        build_pagination_row(
            page,
            pages,
            f"{prefix}:{page - 1}",
            prefix,
            f"{prefix}:{page + 1}",
        ),
        [ib("◀️ بازگشت", callback_data="stats_db")],
    ]
    await safe_edit_or_send(
        context,
        chat_id,
        "\n".join(lines),
        InlineKeyboardMarkup(keyboard),
        message_id,
        parse_mode="HTML",
    )


async def show_db_bluray_list(chat_id, context, page=0, message_id=None):
    """R13: فهرست گروه‌های بلوری (فصل/پارت/سینمایی)."""
    items = _db_stats_collect()["bluray"]
    await _show_db_paged_list(
        chat_id,
        context,
        title="🖨 <b>گروه‌های بلوری</b>",
        prefix="stats_db_bluray",
        items=[
            (
                _db_group_label(key[0], key[1], key[2], key[3]),
                f"{item['links']} لینک",
            )
            for key, item in items
        ],
        page=page,
        message_id=message_id,
    )


async def show_db_ongoing_list(
    chat_id,
    context,
    status,
    page=0,
    message_id=None,
):
    """R13: فهرست انیمه‌های درحال پخش / اتمام‌یافته."""
    rows = db.get_ongoing_by_status(status)
    if status == "active":
        title = "📺 <b>انیمه‌های درحال پخش</b>"
        prefix = "stats_db_air"
    else:
        title = "🏁 <b>انیمه‌های اتمام‌یافته/غیرفعال</b>"
        prefix = "stats_db_fin"
    await _show_db_paged_list(
        chat_id,
        context,
        title=title,
        prefix=prefix,
        items=[
            (
                _db_group_label(
                    row["anime_name"],
                    row.get("season_num"),
                    row.get("part_num"),
                    False,
                ),
                None,
            )
            for row in rows
        ],
        page=page,
        message_id=message_id,
    )


async def show_upload_stats(chat_id, context, message_id=None):
    """R14: آمار آپلود — روزانه/هفتگی/ماهانه/سالانه (شمسی، وقت تهران).

    هر دوره: تعداد لینک + تعداد فایل (جمع بازهٔ پیام‌ها) + مقایسه با
    دورهٔ قبلِ بسته. مرزها از period_boundaries (هفته = شنبه).
    """
    headers = {
        "d": "📅 امروز",
        "w": "📆 این هفته",
        "m": "🗓 این ماه",
        "y": "📊 امسال",
    }
    lines = [
        "📈 <b>آمار آپلود</b>",
        "<i>شمسی · به وقت تهران · دورهٔ جاری تا این لحظه</i>",
    ]

    for period in ("d", "w", "m", "y"):
        bounds = period_boundaries(period)
        current = db.get_upload_ranges(start=bounds["start"])
        previous = db.get_upload_ranges(
            start=bounds["prev_start"], end=bounds["prev_end"]
        )
        cur_files = sum(count_range_messages(r) for r in current)
        if len(current) > len(previous):
            arrow = "▲"
        elif len(current) < len(previous):
            arrow = "▼"
        else:
            arrow = "="

        # R15: انیمه‌های یکتای دوره بر مبنای نام ظاهری
        names = set()
        for name, season, part in db.get_upload_identities(
            start=bounds["start"]
        ):
            names.add(db.get_display_for(name, season, part) or name)

        lines.append("")
        lines.append(f"<b>{headers[period]}</b> — {bounds['label']}")
        lines.append(
            f"🔗 {len(current)} لینک · 📁 {cur_files} فایل"
            f" · 🎌 {len(names)} انیمه"
        )
        lines.append(f"⏮ {bounds['prev_label']}: {len(previous)} لینک {arrow}")

    keyboard = [
        [
            ib("🔄 تازه‌سازی", callback_data="stats_uploads"),
            ib("◀️ بازگشت", callback_data="stats_back"),
        ],
    ]

    await safe_edit_or_send(
        context,
        chat_id,
        "\n".join(lines),
        InlineKeyboardMarkup(keyboard),
        message_id,
        parse_mode="HTML",
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
    elif data == "stats_db":
        await show_db_stats(chat_id, context, message_id)
    elif data == "stats_uploads":
        await show_upload_stats(chat_id, context, message_id)
    elif data == "stats_db_qual":
        await show_db_quality_stats(chat_id, context, message_id)
    elif data.startswith("stats_db_bluray"):
        page = int(data.split(":")[1]) if ":" in data else 0
        await show_db_bluray_list(chat_id, context, page, message_id)
    elif data.startswith("stats_db_air"):
        page = int(data.split(":")[1]) if ":" in data else 0
        await show_db_ongoing_list(
            chat_id, context, "active", page, message_id
        )
    elif data.startswith("stats_db_fin"):
        page = int(data.split(":")[1]) if ":" in data else 0
        await show_db_ongoing_list(
            chat_id, context, "inactive", page, message_id
        )
    elif data == "stats_periods":
        await show_periods_menu(chat_id, context, message_id)
    elif data.startswith("stats_period:"):
        # R8d — کارت آمار دورهٔ شمسی (هفتگی/ماهانه/سالانه)
        period = data.split(":", 1)[1]
        if period in ("w", "m", "y"):
            await show_period_stats(chat_id, context, period, message_id)
        else:
            await show_periods_menu(chat_id, context, message_id)
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
