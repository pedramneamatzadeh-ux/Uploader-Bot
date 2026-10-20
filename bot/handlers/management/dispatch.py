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

from .common import SORT_MODES, _episode_sort_key, _level_state, _manage
from .detail import show_link_detail
from .episodes import show_episode_list
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
        current = manage.get("sort", "alpha")
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
        manage["l2"] = db.get_combined_groups(names)
        for key in ("season", "part", "episode", "l3", "l4"):
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
    if data.startswith("mg_sum"):
        return await handle_summary_callback(context, manage, query, data)

    # --- بقیه رفتارهای موجود (بدون تغییر) ---
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
        current = manage.get("display_name") or manage.get("name") or ""
        await query.edit_message_text(
            "✏️ تغییر نام ظاهری\n\n"
            f"نام فعلی: {current}\n\n"
            "نام جدید (فقط حروف انگلیسی) را وارد کن:\n"
            "• فقط در لیست اول عوض می‌شود؛ نام لینک‌ها دست نمی‌خورد.\n"
            "• اگر این نام را انیمه دیگری هم داشته باشد، هر دو در لیست "
            "اول یکی می‌شوند.\n\n"
            "برای لغو /cancel را تایپ کن."
        )
        context.user_data["rename_waiting"] = "display"
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
        members = manage.get("names") or []
        if len(members) < 2:
            await query.answer(
                "ℹ️ این ردیف ادغام نشده است.",
                show_alert=True,
            )
            return _level_state(manage)
        keyboard = [
            [ib(member, callback_data=f"split:{i}")]
            for i, member in enumerate(members)
        ]
        keyboard.append(
            [
                ib(
                    "◀️ بازگشت", callback_data="split_cancel"
                )
            ]
        )
        await query.edit_message_text(
            "✂️ جداسازی — کدام انیمه جدا شود؟\n\n"
            "(نام واقعی هر عضو نوشته شده است)",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return _level_state(manage)

    if data == "split_cancel":
        return await _refresh_current(chat_id, context, manage)

    if data.startswith("split:"):
        try:
            idx = int(data.split(":", 1)[1])
        except ValueError:
            idx = -1
        members = manage.get("names") or []
        if idx < 0 or idx >= len(members):
            await query.answer("❌ گزینه نامعتبر.", show_alert=True)
            return _level_state(manage)
        member = members[idx]
        display = manage.get("display_name") or manage.get("name") or ""
        db.split_display_name(member, display, members)

        # مرحله ۵د: هویت جدید ردیف از روی نام واقعیِ فعلی بازمحاسبه می‌شود
        current = manage.get("name") or ""
        new_display = db.get_display_map().get(current, current)
        manage["display_name"] = new_display
        manage["names"] = db.names_for_display(new_display)
        manage["l2"] = db.get_combined_groups(manage["names"])
        context.user_data["manage"] = manage

        await query.answer(f"✅ «{member}» جدا شد.")
        return await _refresh_current(chat_id, context, manage)

    if data.startswith("view_link:"):
        session_id = data.split(":", 1)[1]
        await show_link_detail(chat_id, context, session_id)
        return MANAGE_DETAIL

    if data.startswith("edit:"):
        _, action, session_id = data.split(":", 2)
        context.user_data["edit_session"] = session_id
        context.user_data["edit_field"] = action

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
            await query.edit_message_text("✅ لینک با موفقیت حذف شد.")
            manage.pop("detail_message_id", None)
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
        session_id = data.split(":", 1)[1]
        ref = db.get_upload_by_id(session_id)
        if not ref:
            await query.answer("لینک مرجع پیدا نشد.")
            return MANAGE_DETAIL

        context.user_data["add_quality_ref"] = ref
        await query.edit_message_text(
            "📹 کیفیت جدید را انتخاب کن:",
            reply_markup=build_add_quality_keyboard(session_id),
        )
        return MANAGE_DETAIL

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
