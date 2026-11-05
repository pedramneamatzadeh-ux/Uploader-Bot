"""دیسپچر callbackهای مدیریت."""

import logging
import sqlite3
import uuid
from collections import Counter

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from ...config import config
from ...constants import (
    ALL_QUALITIES,
    EPISODE_RANGE,
    MANAGE_DETAIL,
    MANAGE_EDIT,
    MANAGE_EPISODES,
    MANAGE_EXTRA_TEXT,
    MANAGE_GROUPS,
    MANAGE_LIST,
    MANAGE_QUALITIES,
    MANAGE_SEARCH,
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

from .common import (
    SORT_MODES,
    _episode_sort_key,
    _group_label,
    _level_state,
    _manage,
    _recalc_manage_group,
)
from .detail import show_link_detail
from .episodes import show_episode_list
from .extras import (
    _extra_kwargs,
    extras_ret_state,
    render_extras_host,
    show_extras_panel,
    start_extras_add,
)
from .groups import show_group_list
from .list_l1 import show_link_list
from .qualities import show_quality_list
from .refresh import _refresh_current
from .summary import handle_summary_callback

logger = logging.getLogger(__name__)


@admin_only
async def handle_management_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    try:
        return await _dispatch_management(context, query)
    finally:
        # رفع باگ ۵د-۲: answerCallbackQuery فقط یک بار پاسخ می‌گیرد؛
        # پاسخ اصلی اینجا (بعد از alert/toast شاخه‌ها) زده می‌شود تا
        # پیام‌های شاخه‌ها اول باشند و بی‌صدا حذف نشوند.
        try:
            await query.answer()
        except Exception:
            logger.debug(
                "answerCallbackQuery ناموفق بود", exc_info=True
            )


def _alias_reset_keyboard(
    reset_callback: str,
    back_callback: str,
) -> InlineKeyboardMarkup:
    """R12-2: ریست به نام واقعی + بازگشت (زیر پرامپت‌های نام ظاهری)."""
    return InlineKeyboardMarkup(
        [
            [
                ib("↩️ ریست به نام واقعی", callback_data=reset_callback)
            ],
            [ib("◀️ بازگشت", callback_data=back_callback)],
        ]
    )


async def _dispatch_management(
    context: ContextTypes.DEFAULT_TYPE,
    query,
) -> int:
    chat_id = query.message.chat_id
    data = query.data
    manage = _manage(context)

    # رفع باگ ۵د-۲: فشردن هر دکمه، انتظار تایپ قبلی را لغو می‌کند
    # (وگرنه state انتظار می‌ماند و پیام‌های بعدی بی‌پاسخ می‌مانند)
    for key in (
        "rename_waiting",
        "search_mode",
        "edit_session",
        "edit_field",
        "waiting_for_input",
        "aq_waiting",
        "aq_quality",
    ):
        context.user_data.pop(key, None)

    if data == "back_to_main":
        await query.edit_message_text("✅ به منوی اصلی بازگشتید.")
        await go_to_main_menu(context, chat_id)
        context.user_data.pop("manage", None)
        return ConversationHandler.END

    if data == "refresh_list":
        await show_link_list(chat_id, context, manage.get("page", 0))
        return MANAGE_LIST

    if data == "back_to_list":
        if (
            manage.get("level") == 4
            and manage.get("l4") is not None
        ):
            await show_quality_list(chat_id, context)
            return MANAGE_QUALITIES
        await show_link_list(chat_id, context, manage.get("page", 0))
        return MANAGE_LIST

    if data.startswith("page:"):
        page = max(0, int(data.split(":")[1]))
        manage["page"] = page
        context.user_data["manage"] = manage
        await show_link_list(chat_id, context, page)
        return MANAGE_LIST

    if data == "mg_sort":
        current = manage.get("sort", "new")  # B3
        next_idx = (
            SORT_MODES.index(current) + 1
            if current in SORT_MODES
            else 0
        )
        manage["sort"] = SORT_MODES[next_idx % len(SORT_MODES)]
        context.user_data["manage"] = manage
        await show_link_list(chat_id, context, manage.get("page", 0))
        return MANAGE_LIST

    if data == "search_clear":
        manage["mode"] = "list"
        manage["search_term"] = None
        manage["page"] = 0
        context.user_data["manage"] = manage
        await show_link_list(chat_id, context, 0)
        return MANAGE_LIST

    # --- سطح ۱: انتخاب اسم ---
    if data.startswith("m1:"):
        try:
            idx = int(data.split(":", 1)[1])
        except ValueError:
            idx = -1
        items = manage.get("l1") or []
        if idx < 0 or idx >= len(items):
            await query.answer("❌ گزینه نامعتبر.", show_alert=True)
            return MANAGE_LIST

        item = items[idx]
        names = list(item.get("names") or [])
        display = item.get("display_name") or (
            names[0] if names else ""
        )
        if not names and display:
            names = [display]
        manage["display_name"] = display
        manage["names"] = names
        manage["name"] = names[0] if names else ""
        manage["is_cinema"] = bool(item.get("cinema"))
        # R12-2: ردیف‌های سطح ۲ = اعضای (نام، نوع، فصل، پارت) خود گروه
        manage["l2"] = item.get("members") or db.get_combined_groups(names)
        for key in ("season", "part", "episode", "l3", "l4", "extra"):
            manage.pop(key, None)
        context.user_data["manage"] = manage
        await show_group_list(chat_id, context)
        return MANAGE_GROUPS

    # --- سطح ۲: انتخاب فصل/پارت (سینمایی ⇒ پرش به کیفیت‌ها) ---
    if data.startswith("m2:"):
        try:
            idx = int(data.split(":", 1)[1])
        except ValueError:
            idx = -1
        groups = manage.get("l2") or []
        if idx < 0 or idx >= len(groups):
            await query.answer("❌ گزینه نامعتبر.", show_alert=True)
            return MANAGE_GROUPS

        group = groups[idx]
        manage["season"] = group.get("season_num") or ""
        manage["part"] = group.get("part_num") or ""
        # نام واقعیِ همین گروه (در ردیف ادغام‌شده هر گروه نام خودش را دارد)
        manage["name"] = group.get("anime_name") or manage.get("name") or ""
        # نوع از خود گروه گرفته می‌شود، نه از نام انیمه (رفع باگ مخلوط)
        manage["group_type"] = group.get("anime_type") or ""
        manage["is_cinema"] = bool(group.get("is_cinema"))
        manage.pop("episode", None)
        manage.pop("l4", None)
        manage.pop("extra", None)

        if group.get("session_id"):
            # B1: عضو لینک‌محور (یک لینک با alias جدا) ⇒ مستقیم جزئیات
            context.user_data["manage"] = manage
            await show_link_detail(chat_id, context, group["session_id"])
            return MANAGE_DETAIL

        if manage["is_cinema"]:
            # R5: در سینمایی سطح «قسمت» ادغام شده ⇒ مستقیم کیفیت‌ها
            manage["l4"] = db.get_group_links(
                manage["name"],
                manage["season"],
                manage["part"],
                episode_range=None,
                anime_type=manage["group_type"],
            )
            context.user_data["manage"] = manage
            await show_quality_list(chat_id, context)
            return MANAGE_QUALITIES

        entries = db.get_episode_entries(
            manage["name"],
            manage["season"],
            manage["part"],
            anime_type=manage["group_type"],
        )
        entries.sort(key=_episode_sort_key)
        manage["l3"] = entries
        manage["ep_page"] = 0  # B10: فصل تازه ⇒ صفحهٔ اول
        context.user_data["manage"] = manage
        await show_episode_list(chat_id, context)
        return MANAGE_EPISODES

    # --- سطح ۳: انتخاب قسمت ---
    if data.startswith("m3:"):
        try:
            idx = int(data.split(":", 1)[1])
        except ValueError:
            idx = -1
        entries = manage.get("l3") or []
        if idx < 0 or idx >= len(entries):
            await query.answer("❌ گزینه نامعتبر.", show_alert=True)
            return MANAGE_EPISODES

        episode = entries[idx].get("episode_range") or ""
        manage["episode"] = episode
        manage["l4"] = db.get_group_links(
            manage["name"],
            manage["season"],
            manage["part"],
            episode_range=episode,
            anime_type=manage.get("group_type"),
        )
        context.user_data["manage"] = manage
        await show_quality_list(chat_id, context)
        return MANAGE_QUALITIES

    # --- سطح ۴: انتخاب کیفیت ⇒ جزئیات ---
    if data.startswith("m4:"):
        try:
            idx = int(data.split(":", 1)[1])
        except ValueError:
            idx = -1
        rows = manage.get("l4") or []
        if idx < 0 or idx >= len(rows):
            await query.answer("❌ گزینه نامعتبر.", show_alert=True)
            return MANAGE_QUALITIES

        session_id = rows[idx]["session_id"]
        await show_link_detail(chat_id, context, session_id)
        return MANAGE_DETAIL

    # --- B10: صفحه‌بندی لیست قسمت‌ها ---
    if data.startswith("mg_ep_page:"):
        try:
            manage["ep_page"] = max(0, int(data.split(":", 1)[1]))
        except ValueError:
            manage["ep_page"] = 0
        context.user_data["manage"] = manage
        await show_episode_list(chat_id, context)
        return MANAGE_EPISODES

    # --- بازگشت یک سطح بالاتر ---
    if data == "mg_back":
        level = manage.get("level", 1)

        if level == 4:
            if manage.get("is_cinema"):
                await show_group_list(chat_id, context)
                return MANAGE_GROUPS
            if manage.get("l3") is not None:
                await show_episode_list(chat_id, context)
                return MANAGE_EPISODES
            await show_group_list(chat_id, context)
            return MANAGE_GROUPS

        if level == 3:
            await show_group_list(chat_id, context)
            return MANAGE_GROUPS

        await show_link_list(chat_id, context, manage.get("page", 0))
        return MANAGE_LIST

    # --- R9: افزودن قسمت جدید به همین فصل (ورود به زنجیره آپلود) ---
    if data == "mg_add_ep":
        if manage.get("level") != 3:
            await query.answer(
                "❌ ابتدا فصل را انتخاب کنید.", show_alert=True
            )
            return MANAGE_EPISODES

        name = manage.get("name") or ""
        season = manage.get("season") or ""
        part = manage.get("part") or ""
        group_type = manage.get("group_type") or ""
        rows = db.get_group_links(
            name,
            season,
            part,
            episode_range=None,
            anime_type=group_type,
        )
        ref = {}
        if rows:
            ref = db.get_upload_by_id(rows[0].get("session_id")) or {}

        # کلیدهای ثابت فلوی آپلود از همین فصل پر می‌شوند
        # (بازه قسمت و کیفیت‌ها مثل «آپلود قسمت بعدی» از نو پرسیده می‌شوند)
        context.user_data["anime_name"] = name
        context.user_data["season_num"] = season
        context.user_data["part_num"] = part
        context.user_data["anime_type"] = ref.get("anime_type") or group_type
        context.user_data["channel_chat_id"] = ref.get("channel_chat_id")
        context.user_data["airing_status"] = ref.get("airing_status")
        context.user_data["db_name"] = get_database_name(
            ref.get("channel_chat_id")
        )
        for key in ("episode_range", "qualities", "mq_selected", "mq_queue"):
            context.user_data.pop(key, None)

        # import تنبل — بدون ایجاد حلقه ماژولی بین پکیج‌ها
        from ..upload.common import EPISODE_QUESTION_TEXT

        await query.edit_message_text(EPISODE_QUESTION_TEXT)
        return EPISODE_RANGE

    # --- R10: خلاصه داستان فصل ---
    if data in ("mg_bluray", "mg_bluray_ep"):
        # B20/B22: تاگل بلوری دوطرفه — صفحهٔ قسمت‌ها (mg_bluray) کل
        # فصل/پارت/سینمایی؛ صفحهٔ کیفیت‌ها (mg_bluray_ep) فقط اپیزود
        # انتخاب‌شده (سینمایی: episode=None ⇒ همان کل فیلم).
        name = manage.get("name") or ""
        season = manage.get("season") or ""
        part = manage.get("part") or ""
        episode = (
            manage.get("episode")
            if data == "mg_bluray_ep"
            else None
        )
        current = db.get_group_bluray(
            name, season, part, episode_range=episode
        )
        new_value = 0 if current else 1
        changed = db.set_group_bluray(
            name, season, part, new_value, episode_range=episode
        )
        toast = (
            f"🖨 بلوری شد — {changed} لینک"
            if new_value
            else f"🖨 بلوری حذف شد — {changed} لینک"
        )
        await query.answer(toast)
        return await _refresh_current(chat_id, context, manage)

    if data.startswith("mg_sum"):
        return await handle_summary_callback(context, manage, query, data)

    # --- بقیه رفتارهای موجود (بدون تغییر) ---
    # --- R16: «📛 فهرست اسم‌ها» — اسم‌های جستجوی اضافی (۳ دامنه) ---
    if data.startswith("mg_extra:"):
        scope = data.split(":", 1)[1]
        session_id = ""
        if scope.startswith("link:"):
            session_id = scope.split(":", 1)[1]
            scope = "link"
        if scope not in ("anime", "group", "link") or (
            scope == "link" and not session_id
        ):
            await query.answer("❌ گزینه نامعتبر.", show_alert=True)
            return _level_state(manage)
        if scope == "anime" and not (manage.get("names") or []):
            await query.answer(
                "❌ ابتدا یک انیمه را انتخاب کن.", show_alert=True
            )
            return _level_state(manage)
        if scope == "group" and not (manage.get("name") or ""):
            await query.answer(
                "❌ ابتدا یک فصل/پارت را انتخاب کن.", show_alert=True
            )
            return _level_state(manage)
        await query.answer()
        await show_extras_panel(chat_id, context, scope, session_id or None)
        return extras_ret_state(_manage(context))

    if data.startswith("mg_extra_del:"):
        try:
            idx = int(data.split(":", 1)[1])
        except ValueError:
            idx = -1
        names = (manage.get("extra") or {}).get("names") or []
        if idx < 0 or idx >= len(names):
            await query.answer("❌ گزینه نامعتبر.", show_alert=True)
            await show_extras_panel(chat_id, context)
            return extras_ret_state(manage)
        name = names[idx]
        db.delete_extra_name(extra_name=name, **_extra_kwargs(manage))
        await query.answer(f"🗑 اسم «{name}» حذف شد.")
        await show_extras_panel(chat_id, context)
        return extras_ret_state(_manage(context))

    if data == "mg_extra_add":
        await query.answer()
        await start_extras_add(chat_id, context)
        return MANAGE_EXTRA_TEXT

    if data in ("mg_extra_back", "mg_extra_cancel"):
        await query.answer()
        return await render_extras_host(chat_id, context)

    if data == "create_new":
        await query.edit_message_text(
            "📤 برای ایجاد لینک جدید، از منوی اصلی گزینه «آپلود» را انتخاب کنید."
        )
        await go_to_main_menu(context, chat_id)
        context.user_data.pop("manage", None)
        return ConversationHandler.END

    if data == "search_links":
        await query.edit_message_text("🔍 نام انیمه را برای جستجو وارد کنید:")
        context.user_data["search_mode"] = True
        return MANAGE_SEARCH

    if data == "rename_display":
        # R12-2: تغییر نام ظاهری در سطح عضو (نام واقعی، فصل، پارت) —
        # دیگر روی کل نام واقعی اثر نمی‌گذارد.
        current_name = manage.get("name") or ""
        season = manage.get("season") or ""
        part = manage.get("part") or ""
        if not current_name:
            await query.answer(
                "❌ ابتدا یک فصل/پارت را انتخاب کن.",
                show_alert=True,
            )
            return _level_state(manage)

        current_alias = db.get_display_for(current_name, season, part)
        label = _group_label(season, part, bool(manage.get("is_cinema")))
        context.user_data["rename_waiting"] = "display"
        context.user_data["rename_triple"] = (current_name, season, part)
        await query.edit_message_text(
            f"🎭 تغییر نام ظاهری — فقط برای «{current_name} {label}»\n\n"
            f"📛 نام واقعی: {current_name}\n"
            f"🎭 نام ظاهری فعلی: {current_alias}\n\n"
            "نام جدید (فقط حروف انگلیسی) را وارد کن:\n"
            "• اگر با نام ظاهری انیمه دیگری یکی شود، در لیست اول "
            "پیش هم قرار می‌گیرند.\n"
            "• اگر متفاوت باشد، این فصل/پارت یک انیمه جدا می‌شود.\n"
            "• نام لینک‌ها دست نمی‌خورد.\n\n"
            "برای لغو /cancel را تایپ کن.",
            reply_markup=_alias_reset_keyboard(
                "alias_reset_member", "split_cancel"
            ),
        )
        return MANAGE_EDIT

    if data == "rename_physical":
        current = manage.get("name") or ""
        # رفع باگ ۵د-۱: فقط نام واقعیِ همین فصل/فیلم درگیر تغییر می‌شود
        members = [current] if current else list(manage.get("names") or [])
        member_note = ""
        if len(members) > 1:
            member_note = (
                "نام‌های واقعی این ردیف:\n• "
                + "\n• ".join(members)
                + "\n\n"
            )
        await query.edit_message_text(
            "🔁 تغییر نام لینک‌های همین فصل\n\n"
            f"نام فعلی: {current}\n\n"
            + member_note
            + "نام جدید را وارد کن (فقط حروف انگلیسی).\n"
            "⚠️ نام لینک‌های همین فصل در دیتابیس واقعاً تغییر می‌کند؛ "
            "اگر نام از قبل وجود داشته باشد، لینک‌ها زیر آن ادغام "
            "می‌شوند.\n\n"
            "برای لغو /cancel را تایپ کن."
        )
        context.user_data["rename_waiting"] = "physical"
        return MANAGE_EDIT

    if data == "split_anime":
        # R12-2: جداسازی = انتخاب عضو (نام، فصل، پارت) و دادن
        # نام ظاهری جدید به آن — دیگر برچسبی حذف نمی‌شود.
        members = manage.get("l2") or []
        if len(members) < 2:
            await query.answer(
                "ℹ️ این ردیف ادغام نشده است.",
                show_alert=True,
            )
            return _level_state(manage)
        keyboard = []
        for i, member in enumerate(members):
            member_label = _group_label(
                member.get("season_num") or "",
                member.get("part_num") or "",
                bool(member.get("is_cinema")),
            )
            keyboard.append(
                [
                    ib(
                        f"{member.get('anime_name')} — {member_label}",
                        callback_data=f"split:{i}",
                    )
                ]
            )
        keyboard.append(
            [
                ib(
                    "◀️ بازگشت", callback_data="split_cancel"
                )
            ]
        )
        await query.edit_message_text(
            "✂️ جداسازی — کدام فصل/پارت جدا شود؟\n\n"
            "(برای عضو انتخابی نام ظاهری جدید پرسیده می‌شود.)",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return _level_state(manage)

    if data == "split_cancel":
        context.user_data.pop("rename_waiting", None)
        context.user_data.pop("rename_triple", None)
        return await _refresh_current(chat_id, context, manage)

    if data.startswith("split:"):
        try:
            idx = int(data.split(":", 1)[1])
        except ValueError:
            idx = -1
        members = manage.get("l2") or []
        if idx < 0 or idx >= len(members):
            await query.answer("❌ گزینه نامعتبر.", show_alert=True)
            return _level_state(manage)
        member = members[idx]
        name = member.get("anime_name") or ""
        season = member.get("season_num") or ""
        part = member.get("part_num") or ""
        current_alias = db.get_display_for(name, season, part)
        label = _group_label(season, part, bool(member.get("is_cinema")))
        context.user_data["rename_waiting"] = "display"
        context.user_data["rename_triple"] = (name, season, part)
        await query.edit_message_text(
            f"✂️ جداسازی «{name} {label}»\n\n"
            f"🎭 نام ظاهری فعلی: {current_alias}\n\n"
            "نام ظاهری جدید (فقط حروف انگلیسی) را وارد کن —\n"
            "باید با نام ظاهری گروه متفاوت باشد تا جدا شود.\n\n"
            "برای لغو /cancel را تایپ کن.",
            reply_markup=_alias_reset_keyboard(
                "alias_reset_member", "split_cancel"
            ),
        )
        return MANAGE_EDIT

    if data.startswith("view_link:"):
        # R12-2: بازگشت از پرامپت‌ها ⇒ کلیدهای موقت ویرایش پاک شوند
        for key in ("edit_session", "edit_field", "waiting_for_input"):
            context.user_data.pop(key, None)
        session_id = data.split(":", 1)[1]
        await show_link_detail(chat_id, context, session_id)
        return MANAGE_DETAIL

    if data == "alias_reset_member":
        # R12-2: ریست نام ظاهری عضو به نام واقعی (حذف ردیف سطح فصل
        # + برچسب پیش‌فرض کل نام) — مسیر بازگشت از ادغام قدیمی.
        triple = context.user_data.pop("rename_triple", None)
        context.user_data.pop("rename_waiting", None)
        if not triple:
            await query.answer("❌ عملیات نامعتبر.", show_alert=True)
            return _level_state(manage)
        name, season, part = triple
        db.clear_display_for(name, season, part)
        db.clear_display_for(name, "", "")
        _recalc_manage_group(manage, name, season, part)
        context.user_data["manage"] = manage
        await query.answer(
            f"↩️ نام ظاهری «{name}» به نام واقعی‌اش برگشت."
        )
        return await _refresh_current(chat_id, context, manage)

    if data.startswith("alias_reset_detail:"):
        # B1: ریست فقط alias خودِ لینک را پاک می‌کند ⇒ بازگشت به ارثی
        # فصل/نام/واقعی (دکمه‌های سطح فصل در صفحه قسمت‌ها/کیفیت‌ها هستند).
        session_id = data.split(":", 1)[1]
        link = db.get_upload_by_id(session_id)
        if not link:
            await query.answer("❌ لینک پیدا نشد.", show_alert=True)
            return MANAGE_DETAIL
        had_own = db.clear_link_display(session_id)
        for key in ("edit_session", "edit_field", "waiting_for_input"):
            context.user_data.pop(key, None)
        effective = db.get_display_for(
            link["anime_name"],
            link.get("season_num"),
            link.get("part_num"),
        )
        if had_own:
            toast = f"↩️ alias خود لینک حذف شد — ارثی فصل: {effective}"
        else:
            toast = f"↩️ این لینک alias جدا نداشت — ارثی فصل: {effective}"
        await query.answer(toast)
        await show_link_detail(chat_id, context, session_id)
        return MANAGE_DETAIL

    if data.startswith("edit:"):
        _, action, session_id = data.split(":", 2)
        context.user_data["edit_session"] = session_id
        context.user_data["edit_field"] = action

        if action == "alias":
            # B1: نام ظاهری در سطح *لینک* — فقط همین لینک تغییر می‌کند
            link = db.get_upload_by_id(session_id)
            if not link:
                await query.answer("❌ لینک پیدا نشد.", show_alert=True)
                for key in ("edit_session", "edit_field"):
                    context.user_data.pop(key, None)
                return MANAGE_DETAIL
            own = db.get_link_display(session_id)
            inherited = db.get_display_for(
                link["anime_name"],
                link.get("season_num"),
                link.get("part_num"),
            )
            current_line = (
                f"🎭 نام ظاهری فعلی: {own} (ست‌شده روی همین لینک)"
                if own
                else f"🎭 نام ظاهری فعلی: {inherited} (ارثی از فصل)"
            )
            await query.edit_message_text(
                "🎭 تغییر نام ظاهری — فقط برای همین لینک\n\n"
                f"📛 نام واقعی: {link['anime_name']}\n"
                f"{current_line}\n\n"
                "نام ظاهری جدید (فقط حروف انگلیسی) را وارد کن:\n"
                "• فقط همین لینک تغییر می‌کند؛ بقیه لینک‌های فصل دست "
                "نمی‌خورند.\n"
                "• اگر با نام ظاهری گروه دیگری یکی شود، در لیست اول "
                "پیش آن‌ها قرار می‌گیرد.\n"
                "• اگر متفاوت باشد، این لینک یک انیمه جدا حساب می‌شود.\n\n"
                "برای لغو /cancel را تایپ کن.",
                reply_markup=_alias_reset_keyboard(
                    f"alias_reset_detail:{session_id}",
                    f"view_link:{session_id}",
                ),
            )
            context.user_data["waiting_for_input"] = True
            return MANAGE_EDIT

        if action == "quality":
            await query.edit_message_text(
                "📹 کیفیت جدید را انتخاب کنید:",
                reply_markup=build_quality_edit_keyboard(session_id),
            )
            return MANAGE_DETAIL

        if action == "part":
            kb = InlineKeyboardMarkup(
                [
                    [
                        ib(
                            "ندارد ➖",
                            callback_data=f"set_part_none:{session_id}",
                        )
                    ]
                ]
            )
            await query.edit_message_text(
                "📦 پارت جدید را وارد کنید:\n"
                "(اگر ندارد دکمه «ندارد ➖» را بزن)\n\n"
                "برای لغو /cancel را تایپ کنید.",
                reply_markup=kb,
            )
            context.user_data["waiting_for_input"] = True
            return MANAGE_EDIT

        if action == "season":
            link = db.get_upload_by_id(session_id)
            if link and link.get("anime_type") == "سینمایی":
                season_prompt = "🎬 شماره سینمایی جدید را وارد کنید:"
            else:
                season_prompt = "🔢 فصل جدید را وارد کنید:"
            prompts = {"season": season_prompt}
        else:
            prompts = {
                "name": "✏️ نام جدید انیمه را وارد کنید:",
                "episode": "📺 محدوده قسمت‌های جدید را وارد کنید. مثال: 1-12",
                "channel": "🔢 محدوده پیام جدید را وارد کنید. مثال: 100-110 یا 100",
            }

        await query.edit_message_text(
            prompts[action] + "\n\nبرای لغو /cancel را تایپ کنید."
        )
        context.user_data["waiting_for_input"] = True
        return MANAGE_EDIT

    if data.startswith("set_part_none:"):
        session_id = data.split(":", 1)[1]
        if db.update_upload(session_id, "part_num", ""):
            await query.answer("✅ پارت حذف شد.")
            for key in ("edit_session", "edit_field", "waiting_for_input"):
                context.user_data.pop(key, None)
            await show_link_detail(chat_id, context, session_id)
        else:
            await query.answer("❌ خطا در ذخیره.")
        return MANAGE_DETAIL

    if data.startswith("set_quality:"):
        parts = data.split(":")
        session_id = parts[-1]
        quality = ":".join(parts[1:-1])
        if db.update_upload(session_id, "quality", quality):
            await query.answer(f"✅ کیفیت به {quality} تغییر یافت.")
            await show_link_detail(chat_id, context, session_id)
        else:
            await query.answer("❌ خطا در تغییر کیفیت.")
        return MANAGE_DETAIL

    if data.startswith("toggle:"):
        session_id = data.split(":", 1)[1]
        if db.toggle_status(session_id):
            await query.answer("✅ وضعیت لینک تغییر یافت.")
            await show_link_detail(chat_id, context, session_id)
        else:
            await query.answer("❌ خطا در تغییر وضعیت.")
        return MANAGE_DETAIL

    if data.startswith("delete:"):
        session_id = data.split(":", 1)[1]
        keyboard = [
            [
                ib(
                    "✅ بله، حذف کن",
                    callback_data=f"confirm_delete:{session_id}",
                ),
                ib(
                    "❌ خیر، لغو کن",
                    callback_data=f"view_link:{session_id}",
                ),
            ]
        ]
        await query.edit_message_text(
            "⚠️ آیا مطمئنید که می‌خواهید این لینک را حذف کنید؟",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return MANAGE_DETAIL

    if data.startswith("confirm_delete:"):
        session_id = data.split(":", 1)[1]
        if db.delete_upload(session_id):
            # R16: اسم‌های جستجوی لینک‌محور هم با خود لینک می‌روند
            db.delete_link_extra_names(session_id)
            await query.edit_message_text("✅ لینک با موفقیت حذف شد.")
            # B16: پیامِ جاری حالا toast حذف است ⇒ لیست بعدی با پیام
            # جدید ارسال شود (list_message_id پاک می‌شود).
            manage.pop("list_message_id", None)
            if manage.get("l4") is not None:
                manage["l4"] = [
                    row
                    for row in manage["l4"]
                    if row.get("session_id") != session_id
                ]
            context.user_data["manage"] = manage

            if manage.get("level") == 4 and manage.get("l4") is not None:
                await show_quality_list(chat_id, context)
                return MANAGE_QUALITIES

            await show_link_list(chat_id, context, manage.get("page", 0))
            return MANAGE_LIST
        await query.answer("❌ خطا در حذف لینک.")
        await show_link_detail(chat_id, context, session_id)
        return MANAGE_DETAIL

    if data.startswith("add_quality:"):
        # P17 — دکمه از صفحه‌ی جزئیات به لیست کیفیت‌ها منتقل شد؛
        # state هم همان MANAGE_QUALITIES می‌ماند.
        session_id = data.split(":", 1)[1]
        ref = db.get_upload_by_id(session_id)
        if not ref:
            await query.answer("لینک مرجع پیدا نشد.")
            return MANAGE_QUALITIES

        context.user_data["add_quality_ref"] = ref
        await query.edit_message_text(
            "📹 کیفیت جدید را انتخاب کن:",
            reply_markup=build_add_quality_keyboard(session_id),
        )
        return MANAGE_QUALITIES

    if data.startswith("aq_"):
        quality = data[3:]
        context.user_data["aq_quality"] = quality
        context.user_data["aq_waiting"] = True
        await query.edit_message_text(
            f"✅ کیفیت: {quality}\n\n🔢 محدوده پیام را وارد کن. مثال: 100-110 یا 100"
        )
        return MANAGE_EDIT

    await query.answer(Msg.INVALID_COMMAND)
    return MANAGE_LIST
