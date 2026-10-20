"""گیرنده‌های متنی، ورود و لغو گفتگو."""

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
    UPLOAD_FIELD_MAP,
    Msg,
)
from ...database import db
from ...decorators import admin_only
from ...keyboards import (
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

from .common import _manage
from .detail import show_link_detail
from .groups import show_group_list
from .list_l1 import show_link_list
from .refresh import _refresh_current

logger = logging.getLogger(__name__)


@admin_only
async def start_management(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    context.user_data["manage"] = {
        "page": 0,
        "mode": "list",
        "search_term": None,
        "sort": "alpha",
        "level": 1,
    }
    await show_link_list(update.message.chat_id, context)
    return MANAGE_LIST


@admin_only
async def handle_edit_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    chat_id = update.message.chat_id
    text = update.message.text.strip()
    manage = _manage(context)

    # --- تغییر نام انیمه (ظاهری/واقعی) — مرحله ۵ج ---
    rename_mode = context.user_data.get("rename_waiting")
    if rename_mode:
        if text.lower() == "/cancel":
            context.user_data.pop("rename_waiting", None)
            await update.message.reply_text("❌ تغییر نام لغو شد.")
            # مرحله ۵د: برگشت به همان صفحه‌ای که عملیات از آنجا شروع شد
            return await _refresh_current(chat_id, context, manage)

        valid, error = validate_anime_name(text)
        if not valid:
            await update.message.reply_text(
                f"❌ {error}\nدوباره وارد کن یا /cancel را تایپ کن."
            )
            return MANAGE_EDIT

        # رفع باگ ۵د-۱: از داخل صفحهٔ فصل/فیلم فقط همین فصل درگیر می‌شود
        current_physical = manage.get("name") or ""
        if current_physical:
            members = [current_physical]
        else:
            members = list(manage.get("names") or [])

        if not members:
            context.user_data.pop("rename_waiting", None)
            await update.message.reply_text("❌ نام انیمه پیدا نشد.")
            await show_link_list(chat_id, context, manage.get("page", 0))
            return MANAGE_LIST

        if rename_mode == "display":
            old_display = (
                manage.get("display_name") or manage.get("name") or ""
            )
            if text == old_display:
                await update.message.reply_text(
                    "نام جدید با نام ظاهری فعلی یکسان است.\n"
                    "نام دیگری وارد کن یا /cancel را تایپ کن."
                )
                return MANAGE_EDIT

            # فقط برچسب: نام لینک‌ها و رکوردها دست نمی‌خورند
            db.set_display_names(members, text)
            context.user_data.pop("rename_waiting", None)

            all_members = db.names_for_display(text)
            added = [name for name in all_members if name not in members]

            manage["display_name"] = text
            manage["names"] = all_members
            manage["l2"] = db.get_combined_groups(all_members)
            context.user_data["manage"] = manage

            result = (
                "✅ نام ظاهری تغییر یافت:\n"
                f"«{old_display}» → «{text}»\n\n"
                "🔗 نام لینک‌ها تغییری نکرد."
            )
            if added:
                result += f"\n🔀 با {len(added)} انیمه دیگر ادغام شد."
            await update.message.reply_text(result)
            # مرحله ۵د: ماندن در همان صفحه (قسمت‌ها/کیفیت‌ها) با عنوان جدید
            return await _refresh_current(chat_id, context, manage)

        # حالت واقعی: تغییر نام لینک‌های همین فصل
        if len(members) == 1 and text == members[0]:
            await update.message.reply_text(
                "نام جدید با نام فعلی یکسان است.\n"
                "نام دیگری وارد کن یا /cancel را تایپ کن."
            )
            return MANAGE_EDIT

        old_display = current_physical
        uploads_count, ongoing_count = db.rename_animes(members, text)
        context.user_data.pop("rename_waiting", None)

        result = (
            "✅ نام لینک‌های همین فصل تغییر یافت:\n"
            f"«{old_display}» → «{text}»\n\n"
            f"🔗 {uploads_count} لینک تغییر نام یافت."
        )
        if ongoing_count:
            result += f"\n📺 {ongoing_count} انیمه درحال پخش هم به‌روز شد."
        await update.message.reply_text(result)

        display_map = db.get_display_map()
        new_display = display_map.get(text, text)
        manage["name"] = text
        manage["display_name"] = new_display
        manage["names"] = db.names_for_display(new_display)
        manage["l2"] = db.get_combined_groups(manage["names"])
        context.user_data["manage"] = manage
        await show_group_list(chat_id, context)
        return MANAGE_GROUPS

    if text.lower() == "/cancel":
        await update.message.reply_text("❌ ویرایش لغو شد.")
        if context.user_data.get("aq_waiting"):
            session_id = context.user_data.get(
                "add_quality_ref", {}).get("session_id")
            if session_id:
                await show_link_detail(chat_id, context, session_id)
            return MANAGE_DETAIL
        session_id = context.user_data.get("edit_session")
        if session_id:
            await show_link_detail(chat_id, context, session_id)
            return MANAGE_DETAIL
        await show_link_list(
            chat_id,
            context,
            manage.get("page", 0),
        )
        return MANAGE_LIST

    if context.user_data.get("aq_waiting"):
        valid, error = validate_channel_input(text)
        if not valid:
            await update.message.reply_text(
                f"❌ {error}\nدوباره وارد کن یا /cancel را تایپ کن."
            )
            return MANAGE_EDIT

        ref = context.user_data["add_quality_ref"]
        quality = context.user_data["aq_quality"]
        new_sid = str(uuid.uuid4())

        entry = {
            "anime_name": ref["anime_name"],
            "season_num": ref.get("season_num"),
            "part_num": ref.get("part_num"),
            "episode_range": ref["episode_range"],
            "quality": quality,
            "channel_msg_range": text,
            "is_ongoing": ref.get("is_ongoing", 0),
            "ongoing_anime_id": ref.get("ongoing_anime_id"),
            "anime_type": ref.get("anime_type", ""),
            "channel_chat_id": ref.get("channel_chat_id"),
            # TODO مرحله R5: کپی وضعیت پخش از لینک مرجع
            # (برای دیتابیس سفارشی بدون این خط مقدار NULL می‌شد)
            "airing_status": ref.get("airing_status"),
        }

        try:
            db.save_upload(new_sid, entry, update.effective_user.id)
        except sqlite3.Error as err:
            logger.exception("ذخیره کیفیت جدید ناموفق: %s", err)
            await update.message.reply_text(Msg.SAVE_ERROR)
            return MANAGE_EDIT

        link = await build_download_link(context, new_sid)
        await update.message.reply_text(
            f"✅ کیفیت جدید با موفقیت اضافه شد!\n\n🔗 لینک:\n<code>{link}</code>",
            parse_mode="HTML",
        )

        for key in ("aq_waiting", "aq_quality", "add_quality_ref"):
            context.user_data.pop(key, None)

        await show_link_detail(chat_id, context, ref["session_id"])
        return MANAGE_DETAIL

    session_id = context.user_data.get("edit_session")
    field = context.user_data.get("edit_field")

    if not session_id or not field:
        await update.message.reply_text("❌ اطلاعات ویرایش نامعتبر است.")
        return MANAGE_LIST

    if field == "episode":
        valid, error = validate_episode_input(text)
    elif field == "channel":
        valid, error = validate_channel_input(text)
    else:
        valid, error = True, ""

    if not valid:
        await update.message.reply_text(
            f"❌ {error}\nدوباره وارد کن یا /cancel را تایپ کن."
        )
        return MANAGE_EDIT

    if field == "part":
        text = normalize_optional_text(text)

    db_field = UPLOAD_FIELD_MAP.get(field, field)

    if db.update_upload(session_id, db_field, text):
        download_link = await build_download_link(context, session_id)
        await update.message.reply_text(
            "✅ اطلاعات با موفقیت به‌روز شد!\n\n"
            f"🔗 لینک:\n<code>{download_link}</code>",
            parse_mode="HTML",
        )
        for key in ("edit_session", "edit_field", "waiting_for_input"):
            context.user_data.pop(key, None)
        await show_link_detail(chat_id, context, session_id)
        return MANAGE_DETAIL

    await update.message.reply_text("❌ خطا در ذخیره تغییرات.")
    return MANAGE_EDIT


@admin_only
async def handle_search_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    chat_id = update.message.chat_id
    text = update.message.text.strip()
    manage = _manage(context)

    if text.lower() == "/cancel":
        await update.message.reply_text("❌ جستجو لغو شد.")
        await show_link_list(chat_id, context, manage.get("page", 0))
        return MANAGE_LIST

    manage.update({"search_term": text, "mode": "search", "page": 0})
    context.user_data["manage"] = manage
    context.user_data.pop("search_mode", None)

    await update.message.reply_text(f"🔍 در حال جستجو برای '{text}'...")
    await show_link_list(chat_id, context, 0)
    return MANAGE_LIST


async def cancel_management(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    await update.message.reply_text(
        "❌ عملیات مدیریت لغو شد.",
        reply_markup=main_menu_for(update.effective_user.id),
    )
    context.user_data.pop("manage", None)
    return ConversationHandler.END
