"""فلوی آپلود از بخش درحال پخش."""

import logging
import sqlite3
import uuid
from typing import Any, Optional

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from ...config import config
from ...constants import (
    ONGOING_CREATE_NAME,
    ONGOING_CREATE_PART,
    ONGOING_CREATE_SEASON,
    ONGOING_DETAIL,
    ONGOING_EDIT,
    ONGOING_FIELD_MAP,
    ONGOING_LIST,
    ONGOING_UPLOAD_CONFIRM,
    ONGOING_UPLOAD_DB_SELECT,
    ONGOING_UPLOAD_EPISODE,
    ONGOING_UPLOAD_MODE,
    ONGOING_UPLOAD_MULTI_ASK,
    ONGOING_UPLOAD_MULTI_QUALITY,
    ONGOING_UPLOAD_MULTI_RANGE,
    ONGOING_UPLOAD_SELECT,
    ONGOING_UPLOAD_SINGLE_QUALITY,
    ONGOING_UPLOAD_SINGLE_RANGE,
    Msg,
)
from ...database import db
from ...decorators import admin_only
from ...keyboards import (
    ONGOING_CANCEL_MENU,
    ONGOING_PART_MENU,
    build_pagination_row,
    ib,
    main_menu_for,
    quality_keyboard,
)
from ...utils import (
    register_panel_message,
    build_download_link,
    fmt_tehran,
    get_default_channel_chat_id,
    go_to_ongoing_list,
    normalize_optional_text,
    safe_edit_or_send,
    total_pages,
    validate_channel_input,
    validate_episode_input,
)

from .cancel import handle_ongoing_text_cancel
from .views import show_ongoing_anime_list

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# آپلود قسمت جدید
# ---------------------------------------------------------------------------
async def start_ongoing_upload(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    context.user_data.pop("ongoing_upload", None)
    await show_ongoing_upload_select(update.message.chat_id, context, 0)
    return ONGOING_UPLOAD_SELECT


async def show_ongoing_upload_select(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    page: int = 0,
    message_id: Optional[int] = None,
) -> None:
    items = db.get_ongoing_animes(page=page, active_only=True)
    total = db.count_ongoing_animes(active_only=True)
    pages = total_pages(total, config.PAGE_SIZE)

    if not items:
        text = (
            "📤 آپلود قسمت جدید\n\n"
            "هنوز هیچ انیمه فعالِ درحال پخشی ثبت نشده است.\n"
            "اول از بخش مدیریت، انیمه را ثبت کن."
        )
        keyboard = [
            [ib("➕ افزودن انیمه", callback_data="og_add")],
            [ib("🏠 بازگشت", callback_data="ogup_back_menu")],
        ]
    else:
        lines = ["📤 برای آپلود قسمت جدید، انیمه را انتخاب کن:\n"]
        keyboard = []

        for idx, item in enumerate(items, start=1):
            season = item.get("season_num") or "نامشخص"
            part = item.get("part_num") or "ندارد"
            lines.append(
                f"{idx}. 🎬 {item['anime_name']} | فصل {season} | پارت {part}"
            )
            short = item["anime_name"]
            if len(short) > 22:
                short = short[:19] + "..."
            keyboard.append(
                [
                    ib(f"{idx}. {short}", "primary", callback_data=f"ogup_sel:{item['id']}")
                ]
            )

        lines.append(f"\n📄 صفحه {page + 1} از {pages}")
        text = "\n".join(lines)

        nav = build_pagination_row(
            page,
            pages,
            f"ogup_page:{page - 1}",
            "ogup_refresh",
            f"ogup_page:{page + 1}",
        )
        if nav:
            keyboard.append(nav)

        keyboard.append(
            [
                ib("🎬 مدیریت انیمه‌ها", callback_data="ogup_manage"),
                ib("🏠 بازگشت", callback_data="ogup_back_menu"),
            ]
        )

    await safe_edit_or_send(
        context, chat_id, text, InlineKeyboardMarkup(keyboard), message_id
    )
    context.user_data["ongoing_upload_page"] = page


async def prompt_ongoing_db_or_episode(
    query: Any,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    upload = context.user_data.get("ongoing_upload", {})
    anime_name = upload.get("anime_name", "")

    if len(config.DATABASES) == 1:
        only = config.DATABASES[0]
        upload["channel_chat_id"] = only["chat_id"]
        upload["db_name"] = only["name"]
        context.user_data["ongoing_upload"] = upload

        await query.edit_message_text(
            f"🎬 انیمه انتخاب‌شده: {anime_name}\n\n"
            "شماره قسمت جدید را وارد کن. مثال: 5\n"
            "اگر چند قسمت همزمان است، مثال: 5-6"
        )
        return ONGOING_UPLOAD_EPISODE

    keyboard = [
        [
            ib(f"🗄️ {dbx['name']}", "primary", callback_data=f"og_dbsel:{idx}")
        ]
        for idx, dbx in enumerate(config.DATABASES)
    ]
    keyboard.append([ib("❌ لغو", "primary", callback_data="og_dbsel_cancel")])

    await query.edit_message_text(
        f"🎬 انیمه انتخاب‌شده: {anime_name}\n\nاز کدام دیتابیس می‌خواهی استفاده کنی؟",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return ONGOING_UPLOAD_DB_SELECT


@admin_only
async def select_ongoing_database(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "og_dbsel_cancel":
        context.user_data.pop("ongoing_upload", None)
        await query.edit_message_text(Msg.UPLOAD_CANCELLED_INLINE)
        await go_to_ongoing_list(context, query.message.chat_id)
        return ONGOING_LIST

    idx = int(query.data.split(":", 1)[1])
    if idx < 0 or idx >= len(config.DATABASES):
        await query.answer("❌ دیتابیس نامعتبر.", show_alert=True)
        return ONGOING_UPLOAD_DB_SELECT

    dbx = config.DATABASES[idx]
    upload = context.user_data.setdefault("ongoing_upload", {})
    upload["channel_chat_id"] = dbx["chat_id"]
    upload["db_name"] = dbx["name"]
    anime_name = upload.get("anime_name", "")

    await query.edit_message_text(f"🗄️ دیتابیس انتخاب‌شده: {dbx['name']}")
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text=(
            f"🎬 انیمه: {anime_name}\n\n"
            "شماره قسمت جدید را وارد کن. مثال: 5\n"
            "اگر چند قسمت همزمان است، مثال: 5-6"
        ),
        reply_markup=ONGOING_CANCEL_MENU,
    )
    return ONGOING_UPLOAD_EPISODE


@admin_only
async def handle_ongoing_upload_select_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id
    data = query.data

    if data == "ogup_back_menu":
        await query.edit_message_text("✅ به منوی انیمه‌های درحال پخش برگشتید.")
        await go_to_ongoing_list(context, chat_id)
        return ONGOING_LIST

    if data == "ogup_manage":
        context.user_data["ongoing_manage"] = {"page": 0}
        await show_ongoing_anime_list(chat_id, context, 0)
        return ONGOING_LIST

    if data == "og_add":
        context.user_data["ongoing_new"] = {}
        await query.edit_message_text("➕ نام انیمه درحال پخش را وارد کن:")
        return ONGOING_CREATE_NAME

    if data == "ogup_refresh":
        page = context.user_data.get("ongoing_upload_page", 0)
        await show_ongoing_upload_select(chat_id, context, page, query.message.message_id)
        return ONGOING_UPLOAD_SELECT

    if data.startswith("ogup_page:"):
        page = max(0, int(data.split(":", 1)[1]))
        await show_ongoing_upload_select(chat_id, context, page, query.message.message_id)
        return ONGOING_UPLOAD_SELECT

    if data.startswith("ogup_sel:"):
        anime_id = int(data.split(":", 1)[1])
        item = db.get_ongoing_anime(anime_id)
        if not item:
            await query.answer("❌ انیمه پیدا نشد.")
            return ONGOING_UPLOAD_SELECT
        if item["status"] != "active":
            await query.answer("❌ این انیمه غیرفعال است.", show_alert=True)
            return ONGOING_UPLOAD_SELECT

        context.user_data["ongoing_upload"] = {
            "ongoing_anime_id": item["id"],
            "anime_name": item["anime_name"],
            "season_num": item.get("season_num"),
            "part_num": item.get("part_num"),
        }
        return await prompt_ongoing_db_or_episode(query, context)

    await query.answer(Msg.INVALID_COMMAND)
    return ONGOING_UPLOAD_SELECT


@admin_only
async def receive_ongoing_upload_episode(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    text = update.message.text.strip()
    cancel_state = await handle_ongoing_text_cancel(update, context, text)
    if cancel_state is not None:
        return cancel_state

    valid, error = validate_episode_input(text)
    if not valid:
        await update.message.reply_text(f"❌ {error}\nدوباره وارد کن:")
        return ONGOING_UPLOAD_EPISODE

    upload = context.user_data.get("ongoing_upload")
    if not upload:
        await update.message.reply_text("❌ اطلاعات انیمه پیدا نشد. دوباره شروع کن.")
        await go_to_ongoing_list(context, update.message.chat_id)
        return ONGOING_LIST

    upload["episode_range"] = text

    sent = await update.message.reply_text(
        "نوع آپلود را انتخاب کن:",
        reply_markup=_ogup_mode_markup(upload),
    )
    register_panel_message(context, sent.message_id)
    return ONGOING_UPLOAD_MODE


@admin_only
async def handle_ongoing_upload_mode_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "ogup_cancel":
        context.user_data.pop("ongoing_upload", None)
        await query.edit_message_text(Msg.UPLOAD_CANCELLED_INLINE)
        await go_to_ongoing_list(context, query.message.chat_id)
        return ONGOING_LIST

    mode = data.split(":", 1)[1]
    upload = context.user_data.setdefault("ongoing_upload", {})
    upload["upload_mode"] = mode

    if mode == "single":
        await query.edit_message_text(
            "📹 کیفیت را انتخاب کن:",
            reply_markup=quality_keyboard(
                "ogup_q:", "ogup_cancel",
                bluray=upload.get("is_bluray", 0),
            ),
        )
        return ONGOING_UPLOAD_SINGLE_QUALITY

    if mode == "multi":
        upload["qualities"] = []
        await query.edit_message_text(
            "📹 کیفیت اول را انتخاب کن:",
            reply_markup=quality_keyboard(
                "ogup_mq:", "ogup_cancel",
                bluray=upload.get("is_bluray", 0),
            ),
        )
        return ONGOING_UPLOAD_MULTI_QUALITY

    if mode == "std3":
        upload["qualities"] = []
        context.user_data["og_std_sequence"] = ["480p", "720p", "1080p"]
        context.user_data["og_std_index"] = 0
        context.user_data["_ongoing_current_quality"] = "480p"
        await query.edit_message_text(
            "🔥 حالت سه کیفیت استاندارد انتخاب شد.\n\n"
            "🔢 محدوده پیام کیفیت 480p را وارد کن. مثال: 100-105 یا 100"
        )
        return ONGOING_UPLOAD_MULTI_RANGE

    await query.answer(Msg.INVALID_COMMAND)
    return ONGOING_UPLOAD_MODE


@admin_only
async def ongoing_single_quality_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "ogup_cancel":
        context.user_data.pop("ongoing_upload", None)
        await query.edit_message_text(Msg.UPLOAD_CANCELLED_INLINE)
        await go_to_ongoing_list(context, query.message.chat_id)
        return ONGOING_LIST

    quality = query.data.split(":", 1)[1]
    upload = context.user_data.setdefault("ongoing_upload", {})
    upload["quality"] = quality

    await query.edit_message_text(
        f"✅ کیفیت: {quality}\n\n🔢 محدوده پیام‌های کانال را وارد کن. مثال: 100-110 یا 100"
    )
    return ONGOING_UPLOAD_SINGLE_RANGE


@admin_only
async def receive_ongoing_single_range(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    text = update.message.text.strip()
    cancel_state = await handle_ongoing_text_cancel(update, context, text)
    if cancel_state is not None:
        return cancel_state

    valid, error = validate_channel_input(text)
    if not valid:
        await update.message.reply_text(f"❌ {error}\nدوباره وارد کن:")
        return ONGOING_UPLOAD_SINGLE_RANGE

    upload = context.user_data.setdefault("ongoing_upload", {})
    upload["channel_msg_range"] = text

    await show_ongoing_upload_confirm(update.message, context)
    return ONGOING_UPLOAD_CONFIRM


@admin_only
async def ongoing_multi_quality_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "ogup_cancel":
        context.user_data.pop("ongoing_upload", None)
        await query.edit_message_text(Msg.UPLOAD_CANCELLED_INLINE)
        await go_to_ongoing_list(context, query.message.chat_id)
        return ONGOING_LIST

    quality = query.data.split(":", 1)[1]
    context.user_data["_ongoing_current_quality"] = quality

    await query.edit_message_text(
        f"✅ کیفیت: {quality}\n\n🔢 محدوده پیام این کیفیت را وارد کن. مثال: 100-110 یا 100"
    )
    return ONGOING_UPLOAD_MULTI_RANGE


@admin_only
async def receive_ongoing_multi_range(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    text = update.message.text.strip()
    cancel_state = await handle_ongoing_text_cancel(update, context, text)
    if cancel_state is not None:
        return cancel_state

    valid, error = validate_channel_input(text)
    if not valid:
        await update.message.reply_text(f"❌ {error}\nدوباره وارد کن:")
        return ONGOING_UPLOAD_MULTI_RANGE

    upload = context.user_data.setdefault("ongoing_upload", {})
    upload.setdefault("qualities", [])

    quality = context.user_data.get("_ongoing_current_quality")
    if not quality:
        await update.message.reply_text("❌ کیفیت انتخاب نشده است. دوباره شروع کن.")
        return ONGOING_LIST

    upload["qualities"].append({"quality": quality, "channel_msg_range": text})

    if "og_std_sequence" in context.user_data:
        seq = context.user_data["og_std_sequence"]
        idx = context.user_data.get("og_std_index", 0) + 1

        if idx < len(seq):
            context.user_data["og_std_index"] = idx
            next_quality = seq[idx]
            context.user_data["_ongoing_current_quality"] = next_quality
            await update.message.reply_text(
                f"🔢 محدوده پیام کیفیت {next_quality} را وارد کن. مثال: 120-125 یا 120",
                reply_markup=ONGOING_CANCEL_MENU,
            )
            return ONGOING_UPLOAD_MULTI_RANGE

        context.user_data.pop("og_std_sequence", None)
        context.user_data.pop("og_std_index", None)
        context.user_data.pop("_ongoing_current_quality", None)
        await show_ongoing_upload_confirm(update.message, context)
        return ONGOING_UPLOAD_CONFIRM

    context.user_data.pop("_ongoing_current_quality", None)

    keyboard = [
        [ib("✅ بله، کیفیت بعدی", callback_data="ogup_add_more")],
        [ib("❌ نه، تمام شد", callback_data="ogup_finish")],
        [ib("🚫 لغو", callback_data="ogup_cancel")],
    ]
    await update.message.reply_text(
        "آیا کیفیت دیگری اضافه می‌کنی؟",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return ONGOING_UPLOAD_MULTI_ASK


@admin_only
async def ongoing_multi_ask_more_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "ogup_cancel":
        context.user_data.pop("ongoing_upload", None)
        await query.edit_message_text(Msg.UPLOAD_CANCELLED_INLINE)
        await go_to_ongoing_list(context, query.message.chat_id)
        return ONGOING_LIST

    if query.data == "ogup_add_more":
        await query.edit_message_text(
            "📹 کیفیت بعدی را انتخاب کن:",
            reply_markup=quality_keyboard(
                "ogup_mq:", "ogup_cancel",
                bluray=upload.get("is_bluray", 0),
            ),
        )
        return ONGOING_UPLOAD_MULTI_QUALITY

    if query.data == "ogup_finish":
        upload = context.user_data.get("ongoing_upload", {})
        if not upload.get("qualities"):
            await query.answer("حداقل یک کیفیت لازم است.", show_alert=True)
            return ONGOING_UPLOAD_MULTI_ASK
        await show_ongoing_upload_confirm(query, context)
        return ONGOING_UPLOAD_CONFIRM

    await query.answer(Msg.INVALID_COMMAND)
    return ONGOING_UPLOAD_MULTI_ASK


def _ogup_mode_markup(upload: dict) -> InlineKeyboardMarkup:
    """B20: صفحهٔ انتخاب حالت آپلود + تاگل بلوری."""
    bluray_on = bool(upload.get("is_bluray"))
    keyboard = [
        [
            ib("🔥 سه کیفیت استاندارد 480/720/1080", "primary", callback_data="ogup_mode:std3")
        ],
        [ib("🔸 چند کیفیت انتخابی", "primary", callback_data="ogup_mode:multi")],
        [ib("🔹 تک کیفیت", "primary", callback_data="ogup_mode:single")],
        [
            ib(
                (
                    "✅ بلوری (Blu-ray)"
                    if bluray_on
                    else "🖨 بلوری (Blu-ray)"
                ),
                "primary",
                callback_data="ogup_bluray",
            )
        ],
        [ib("❌ لغو", callback_data="ogup_cancel")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def show_ongoing_upload_confirm(
    update_or_query: Any,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    upload = context.user_data.get("ongoing_upload", {})
    part_display = upload.get("part_num") or "ندارد"
    db_line = (
        f"🗄️ دیتابیس: {upload.get('db_name')}\n" if upload.get(
            "db_name") else ""
    )

    lines = [
        "📋 خلاصه آپلود قسمت جدید:",
        f"{db_line}🎬 انیمه: {upload.get('anime_name')}",
        f"🎞️ فصل: {upload.get('season_num') or 'نامشخص'}",
        f"📦 پارت: {part_display}",
        f"📺 قسمت: {upload.get('episode_range')}",
        f"🖨 بلوری: {'✅ بله' if upload.get('is_bluray') else '❌ خیر'}",
        "",
    ]

    if upload.get("qualities"):
        lines.append("کیفیت‌ها:")
        for idx, item in enumerate(upload["qualities"], start=1):
            lines.append(
                f"{idx}. {item['quality']} → محدوده {item['channel_msg_range']}"
            )
    else:
        lines.append(f"📹 کیفیت: {upload.get('quality')}")
        lines.append(f"🔢 محدوده پیام: {upload.get('channel_msg_range')}")

    lines.append("\nآیا اطلاعات صحیح است؟")

    keyboard = [
        [
            ib("✅ تأیید و ساخت لینک", callback_data="ogup_confirm"),
            ib("❌ انصراف", callback_data="ogup_cancel_confirm"),
        ]
    ]

    text = "\n".join(lines)
    markup = InlineKeyboardMarkup(keyboard)

    if hasattr(update_or_query, "edit_message_text"):
        await update_or_query.edit_message_text(text, reply_markup=markup)
    elif hasattr(update_or_query, "reply_text"):
        await update_or_query.reply_text(text, reply_markup=markup)
    elif getattr(update_or_query, "message", None):
        await update_or_query.message.reply_text(text, reply_markup=markup)


@admin_only
async def confirm_ongoing_upload(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "ogup_cancel_confirm":
        context.user_data.pop("ongoing_upload", None)
        await query.edit_message_text(Msg.UPLOAD_CANCELLED_INLINE)
        await go_to_ongoing_list(context, query.message.chat_id)
        return ONGOING_LIST

    upload = context.user_data.get("ongoing_upload")
    if not upload:
        await query.edit_message_text("❌ اطلاعات آپلود پیدا نشد.")
        await go_to_ongoing_list(context, query.message.chat_id)
        return ONGOING_LIST

    admin_id = query.from_user.id
    links_text = ""
    channel_chat_id = upload.get("channel_chat_id")
    if channel_chat_id is None:
        channel_chat_id = get_default_channel_chat_id()

    try:
        if upload.get("qualities"):
            for q in upload["qualities"]:
                session_id = str(uuid.uuid4())
                entry = {
                    "anime_name": upload["anime_name"],
                    "season_num": upload.get("season_num"),
                    "part_num": upload.get("part_num"),
                    "episode_range": upload["episode_range"],
                    "quality": q["quality"],
                    "channel_msg_range": q["channel_msg_range"],
                    "is_ongoing": 1,
                    "ongoing_anime_id": upload.get("ongoing_anime_id"),
                    "anime_type": "سریالی",
                    "channel_chat_id": channel_chat_id,
                    "is_bluray": 1 if upload.get("is_bluray") else 0,
                }
                db.save_upload(session_id, entry, admin_id)
                link = await build_download_link(context, session_id)
                links_text += f"🔗 {q['quality']}: <code>{link}</code>\n"
        else:
            session_id = str(uuid.uuid4())
            entry = {
                "anime_name": upload["anime_name"],
                "season_num": upload.get("season_num"),
                "part_num": upload.get("part_num"),
                "episode_range": upload["episode_range"],
                "quality": upload["quality"],
                "channel_msg_range": upload["channel_msg_range"],
                "is_ongoing": 1,
                "ongoing_anime_id": upload.get("ongoing_anime_id"),
                "anime_type": "سریالی",
                "channel_chat_id": channel_chat_id,
                "is_bluray": 1 if upload.get("is_bluray") else 0,
            }
            db.save_upload(session_id, entry, admin_id)
            link = await build_download_link(context, session_id)
            links_text = f"🔗 لینک: <code>{link}</code>\n"
    except sqlite3.Error as err:
        logger.exception("خطا در ذخیره آپلود درحال پخش: %s", err)
        if query.message:
            await query.message.reply_text(Msg.SAVE_ERROR)
        return ONGOING_UPLOAD_CONFIRM

    anime_name = upload["anime_name"]
    episode_range = upload["episode_range"]
    context.user_data.clear()

    await query.edit_message_text(Msg.UPLOAD_SAVED)
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text=(
            "✅ قسمت جدید با موفقیت ثبت شد!\n\n"
            f"🎬 {anime_name}\n"
            f"📺 قسمت: {episode_range}\n\n"
            f"{links_text}"
        ),
        parse_mode="HTML",
    )

    await go_to_ongoing_list(context, query.message.chat_id)
    return ONGOING_LIST


# ============================================================================
# B20: تاگل بلوری در سه صفحهٔ آپلود درحال‌پخش (حالت/تک/چند)
# ============================================================================
def _flip_ogup_bluray(context: ContextTypes.DEFAULT_TYPE) -> int:
    upload = context.user_data.setdefault("ongoing_upload", {})
    new_value = 0 if upload.get("is_bluray") else 1
    upload["is_bluray"] = new_value
    return new_value


@admin_only
async def ogup_bluray_mode(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()
    _flip_ogup_bluray(context)
    upload = context.user_data.get("ongoing_upload", {})
    await query.edit_message_text(
        "نوع آپلود را انتخاب کن:",
        reply_markup=_ogup_mode_markup(upload),
    )
    return ONGOING_UPLOAD_MODE


@admin_only
async def ogup_bluray_single(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()
    new_value = _flip_ogup_bluray(context)
    await query.edit_message_text(
        "📹 کیفیت را انتخاب کن:",
        reply_markup=quality_keyboard(
            "ogup_q:", "ogup_cancel", bluray=new_value
        ),
    )
    return ONGOING_UPLOAD_SINGLE_QUALITY


@admin_only
async def ogup_bluray_multi(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    query = update.callback_query
    await query.answer()
    new_value = _flip_ogup_bluray(context)
    await query.edit_message_text(
        "📹 کیفیت را انتخاب کن:",
        reply_markup=quality_keyboard(
            "ogup_mq:", "ogup_cancel", bluray=new_value
        ),
    )
    return ONGOING_UPLOAD_MULTI_QUALITY
