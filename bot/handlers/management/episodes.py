"""سطح ۳: قسمت‌ها."""

import logging
import sqlite3
import uuid
from collections import Counter

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from ...config import config
from ...constants import (
    ALL_QUALITIES,
    MANAGE_DETAIL,
    MANAGE_EDIT,
    MANAGE_EPISODES,
    MANAGE_GROUPS,
    MANAGE_LIST,
    MANAGE_QUALITIES,
    MANAGE_SEARCH,
    OTHER_SEASONS,
    UPLOAD_FIELD_MAP,
    Msg,
)
from ...database import db
from ...decorators import admin_only
from ...keyboards import (
    ib,
    build_add_quality_keyboard,
    build_pagination_row,
    build_quality_edit_keyboard,
    main_menu_for,
)
from ...utils import (
    build_download_link,
    fmt_tehran,
    get_database_name,
    go_to_main_menu,
    normalize_optional_text,
    parse_range,
    safe_edit_or_send,
    total_pages,
    validate_anime_name,
    validate_channel_input,
    validate_episode_input,
)

from .common import _append_name_buttons, _episode_sort_key, _group_label, _manage

logger = logging.getLogger(__name__)

# B10: تعداد قسمت‌ها در هر صفحه (انیمه‌های پرقسمت در یک پیام جا نمی‌شوند)
EPISODES_PAGE_SIZE = 20


def share_link_label(group_type: str) -> str:
    """R28: برچسب دکمهٔ لینک در مدیریت — متناسب با نوع گروه.

    سینمایی ⇒ «لینک این سینمایی»؛ فصل‌های «سایر» (OVA/ONA/Special) ⇒
    «لینک این OVA» و …؛ بقیه ⇒ «لینک این فصل».
    """
    kind = (group_type or "").strip()
    if kind == "سینمایی":
        return "لینک این سینمایی"
    if kind.lower() in {s.lower() for s in OTHER_SEASONS}:
        return f"لینک این {kind}"
    return "لینک این فصل"


async def _share_link_rows(
    context: ContextTypes.DEFAULT_TYPE,
    manage: dict,
) -> list:
    """R26e: دکمه‌های «لینک این فصل» + تاگل فعال/غیرفعال.

    فقط در صفحه‌هایی صدا زده می‌شود که به **یک** فصل/پارت/سینمایی محدودند
    (فهرست قسمت‌ها و کیفیت‌ها). در صفحهٔ «فهرست فصل‌ها» عمداً نمایش داده
    نمی‌شود، چون لینک آن‌جا معنای «همهٔ فصل‌ها» می‌گرفت (باگ گزارش‌شده).
    """
    try:
        group_type = (
            manage.get("group_type")
            or manage.get("anime_type")
            or ("سینمایی" if manage.get("is_cinema") else "سریالی")
        )
        info = db.get_or_create_group_link(
            manage.get("name") or "",
            manage.get("season") or "",
            manage.get("part") or "",
            group_type,
        )
    except Exception as err:      # noqa: BLE001 — لینک نباید صفحه را بشکند
        logger.warning("ساخت لینک فصل ناموفق بود: %s", err)
        return [], False

    manage["share_code"] = info["share_code"]
    manage["share_status"] = info["status"]
    context.user_data["manage"] = manage

    active = (info["status"] or "active") == "active"
    # R27: یک دکمهٔ ادغام‌شده — با زدنش هم لینک و هم دکمهٔ
    # فعال/غیرفعال در همان پیام نمایش داده می‌شود (درخواست کاربر).
    # R28: برچسب بر اساس نوع گروه («لینک این سینمایی» / «لینک این OVA» / …)
    # و رنگ سبز (درخواست کاربر).
    return [
        [
            ib(
                f"🔗 {share_link_label(group_type)}",
                callback_data="mg_group_link",
                style="success",
            )
        ]
    ], active


# ---------------------------------------------------------------------------
# سطح ۳: قسمت‌ها (هر آپلود جدا = یک ورودی؛ بازه‌ها تک‌دکمه)
# ---------------------------------------------------------------------------
async def show_episode_list(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    manage = _manage(context)
    name = manage.get("display_name") or manage.get("name") or ""
    entries = list(manage.get("l3") or [])

    manage["level"] = 3
    for key in ("episode", "l4"):
        manage.pop(key, None)

    entries.sort(key=_episode_sort_key)
    manage["l3"] = entries

    group_title = _group_label(
        manage.get("season") or "",
        manage.get("part") or "",
        False,
    )
    title = f"📺 {name} | {group_title} — قسمت‌ها:\n\n"

    keyboard = []

    if not entries:
        text = title + "قسمتی یافت نشد. 😕"
    else:
        # B10: صفحه‌بندی قسمت‌ها (اندیس m3 سراسری می‌ماند)
        pages = total_pages(len(entries), EPISODES_PAGE_SIZE)
        page = min(max(0, manage.get("ep_page", 0)), pages - 1)
        manage["ep_page"] = page
        start = page * EPISODES_PAGE_SIZE
        page_entries = entries[start:start + EPISODES_PAGE_SIZE]

        lines = []
        episode_buttons = []
        for idx, entry in enumerate(page_entries, start=start):
            episode = entry.get("episode_range") or ""
            display = episode or "نامشخص"
            lines.append(
                f"{idx + 1}. قسمت {display} "
                f"({entry.get('links', 0)} لینک)"
            )
            episode_buttons.append(
                ib(
                    f"Episode {episode}" if episode else "Episode ?",
                    callback_data=f"m3:{idx}",
                    style="primary",
                )
            )

        # دکمه‌های قسمت: دو تا در هر ردیف
        for row_start in range(0, len(episode_buttons), 2):
            keyboard.append(episode_buttons[row_start:row_start + 2])

        # B10: ردیف صفحه‌بندی — بالای دکمه‌های تغییر اسم (درخواست کاربر)
        if pages > 1:
            nav = build_pagination_row(
                page,
                pages,
                f"mg_ep_page:{page - 1}",
                f"mg_ep_page:{page}",
                f"mg_ep_page:{page + 1}",
            )
            if nav:
                keyboard.append(nav)
            lines.append(f"\n📄 صفحه {page + 1} از {pages}")

        text = title + "\n".join(lines)

    # R30: دکمهٔ لینک در صفحهٔ یک فصل ⇒ **زیر قسمت‌ها** و بالای
    # «تغییر اسم واقعی/ظاهری» (درخواست کاربر؛ قبلاً اشتباهاً بالای همه بود)
    share_rows, _share_active = await _share_link_rows(context, manage)
    keyboard.extend(share_rows)

    _append_name_buttons(keyboard, manage)

    # R9 + R10: افزودن قسمت جدید به همین فصل + خلاصه داستان همین فصل
    keyboard.append(
        [
            ib(
                "➕ افزودن قسمت جدید",
                callback_data="mg_add_ep",
            )
        ]
    )
    keyboard.append(
        [
            ib(
                "📝 خلاصه داستان فصل",
                callback_data="mg_sum",
            )
        ]
    )

    # B20: تاگل بلوری گروهی (همهٔ لینک‌های این فصل/پارت/سینمایی)
    _bluray_on = db.get_group_bluray(
        manage.get("name") or "",
        manage.get("season") or "",
        manage.get("part") or "",
    )
    keyboard.append(
        [
            ib(
                (
                    "🖨 بلوری: ✅ هست"
                    if _bluray_on
                    else "🖨 بلوری: ❌ نیست"
                ),
                callback_data="mg_bluray",
                style="primary",
            )
        ]
    )

    # R16: اسم‌های جستجوی اضافی — فقط همین فصل/پارت
    keyboard.append(
        [
            ib(
                "📛 اسم‌های این فصل/پارت",
                callback_data="mg_extra:group",
                style="primary",
            ),
        ]
    )

    keyboard.append(
        [
            ib("◀️ بازگشت", callback_data="mg_back"),
            ib(
                "🏠 منوی اصلی", callback_data="back_to_main"
            ),
        ]
    )

    markup = InlineKeyboardMarkup(keyboard)
    msg_id = manage.get("list_message_id")
    new_id = await safe_edit_or_send(context, chat_id, text, markup, msg_id)
    manage["list_message_id"] = new_id
    context.user_data["manage"] = manage
