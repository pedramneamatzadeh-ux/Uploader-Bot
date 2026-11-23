"""R26: پنل کاربر برای لینک فصل/پارت/سینمایی/OVA.

مسیر: لینک `?start=s_<code>` → کیفیت‌ها → قسمت‌های همان کیفیت → ارسال
فایل‌ها (با حذف خودکار بعد از مدت تعیین‌شده). این پنل فقط‌خواندنی است و
هیچ دکمهٔ مدیریتی ندارد.
"""

import asyncio
import hashlib
import logging
from typing import Any, Dict, List, Optional

from telegram import InlineKeyboardMarkup, Update
from telegram.error import RetryAfter, TelegramError
from telegram.ext import ContextTypes

from ..config import config
from ..constants import Msg
from ..database import db
from ..keyboards import ib
from ..utils import (
    deletion_notice_text,
    format_anime_title,
    parse_id_list,
    schedule_delete,
    track_user,
)
from .delivery import build_final_text, keep_report_button, report_keyboard
from .membership import get_not_joined_channels, send_join_prompt

logger = logging.getLogger(__name__)

EPISODES_PER_PAGE = 10

PANEL_KEY = "group_panel"   # وضعیت پنل در user_data


# ---------------------------------------------------------------------------
# کمکی‌ها
# ---------------------------------------------------------------------------
def _episode_sort_key(episode: str) -> tuple:
    """جدیدترین اول: مرجع = بزرگ‌ترین آیدی؛ غیرعددی بعد از عددی‌ها."""
    ids = parse_id_list(episode or "", allow_zero=True)
    if not ids:
        return (1, 0, 0, episode or "")
    return (0, -max(ids), -min(ids), "")


def _group_title(group: Dict[str, Any]) -> str:
    """عنوان یکدست گروه (همان قواعد نام ظاهری/فصل/پارت/سینمایی)."""
    anime_name = group.get("anime_name") or ""
    anime_type = group.get("anime_type") or ""
    is_cinema = anime_type == "سینمایی"
    display = db.get_display_for(
        anime_name,
        group.get("season_num") or "",
        group.get("part_num") or "",
    ) or anime_name

    return format_anime_title(
        display,
        None if is_cinema else (group.get("season_num") or ""),
        group.get("part_num") or "",
        anime_type,
        None,
    )


def _episode_label(episode: str) -> str:
    return f"قسمت {episode}" if episode else "قسمت نامشخص"


def _code_part(text: str) -> str:
    """R38/R39: کد کوتاهِ کیفیت/قسمت برای callback_data.

    کیفیت/قسمت در `user_data` نگه داشته می‌شود (نه در دکمه) تا
    callback_data از سقف ۶۴ بایت رد نشود؛ این هش فقط برای تطبیق دکمه
    با فهرست فعلیِ کیفیت‌ها/قسمت‌هاست.
    """
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


def _panel_state(context: ContextTypes.DEFAULT_TYPE) -> Dict[str, Any]:
    """R38: وضعیت پنل کاربر — بی‌صاحب (فقط بر اساس شناسهٔ کاربر)."""
    try:
        state = context.user_data.get(PANEL_KEY)
    except (AttributeError, TypeError):
        return {}
    return state if isinstance(state, dict) else {}


def qualities_keyboard(
    group: Dict[str, Any],
    qualities: List[Dict[str, Any]],
):
    rows = []
    for item in qualities:
        quality = item.get("quality") or "نامشخص"
        # R35: تعداد **فایل/قسمتِ** هر کیفیت (مجموع بازه‌های پیام‌ها)،
        # نه تعداد لینک — درخواست کاربر
        count = item.get("files") or item.get("episodes") or 0
        rows.append(
            [
                ib(
                    f"{quality} ({count} قسمت)",
                    callback_data=f"gp_q:{_code_part(quality)}",
                    style="primary",
                )
            ]
        )

    if not rows:
        return None

    return InlineKeyboardMarkup(rows)


def episodes_keyboard(
    group: Dict[str, Any],
    quality: str,
    episodes: List[Dict[str, Any]],
    page: int,
):
    rows = []
    for item in episodes:
        episode = item.get("episode_range") or ""
        label = _episode_label(episode)
        if (item.get("links") or 0) > 1:
            label += f" ({item['links']} فایل)"
        rows.append(
            [
                ib(
                    label,
                    callback_data=f"gp_e:{_code_part(episode)}",
                    style="primary",
                )
            ]
        )

    nav = []
    if page > 0:
        nav.append(ib("⬅️ صفحه قبل", callback_data=f"gp_p:{page - 1}"))
    if (page + 1) * EPISODES_PER_PAGE < len(episodes):
        nav.append(ib("صفحه بعد ➡️", callback_data=f"gp_p:{page + 1}"))
    if nav:
        rows.append(nav)

    # R27: دکمهٔ «بروزرسانی» حذف شد (درخواست کاربر)
    rows.append([ib("◀️ بازگشت به کیفیت‌ها", callback_data="gp_back")])
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------------------
# رندر پنل
# ---------------------------------------------------------------------------
def render_qualities(group: Dict[str, Any]) -> Optional[tuple]:
    """(متن، کیبورد) صفحهٔ کیفیت‌ها — None اگر چیزی نباشد."""
    qualities = db.get_group_qualities(group)
    if not qualities:
        return None

    title = _group_title(group)
    # R35: «تعداد قسمت» = تعداد فایل‌های هر کیفیت (نه تعداد لینک)؛
    # اگر بین کیفیت‌ها فرق داشت، تفکیک هر کیفیت هم نوشته می‌شود.
    counts = {
        (item.get("quality") or "نامشخص"): (
            item.get("files") or item.get("episodes") or 0
        )
        for item in qualities
    }
    max_count = max(counts.values()) if counts else 0

    lines = [f"🎬 {title}", f"📊 {len(qualities)} کیفیت"]
    if len(set(counts.values())) <= 1:
        lines.append(f"📺 {max_count} قسمت")
    else:
        for quality, count in counts.items():
            lines.append(f"  • {quality}: {count} قسمت")
    lines += [
        "",
        "برای دریافت فایل‌ها یک کیفیت را انتخاب کن:",
    ]

    keyboard = qualities_keyboard(group, qualities)

    # هوشمند: گروه تک‌قسمتی و تک‌کیفیتی ⇒ مستقیم قسمت (بدون کلیک اضافه)
    return "\n".join(lines), keyboard


def render_episodes(
    group: Dict[str, Any],
    quality: str,
    page: int = 0,
) -> Optional[tuple]:
    episodes = db.get_group_episodes(group, quality)
    if not episodes:
        return None

    # R29: در پنل کاربر قسمت‌ها **کوچک به بزرگ** (صعودی) — درخواست کاربر
    episodes.sort(key=lambda item: _episode_sort_key(item.get("episode_range") or ""))
    episodes.reverse()

    pages = max(1, (len(episodes) + EPISODES_PER_PAGE - 1) // EPISODES_PER_PAGE)
    page = min(max(0, page), pages - 1)
    chunk = episodes[page * EPISODES_PER_PAGE:(page + 1) * EPISODES_PER_PAGE]
    if not chunk:
        return None

    title = _group_title(group)
    lines = [
        f"🎬 {title}",
        f"📹 کیفیت: {quality}",
        f"📺 {len(episodes)} قسمت" + (f" · صفحه {page + 1}/{pages}" if pages > 1 else ""),
        "",
        "برای دریافت فایل‌ها یک قسمت را انتخاب کن:",
    ]

    return "\n".join(lines), episodes_keyboard(group, quality, episodes, page)


# ---------------------------------------------------------------------------
# نمایش پنل
# ---------------------------------------------------------------------------
async def _show(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    markup,
    edit: bool = False,
) -> None:
    query = update.callback_query
    if edit and query:
        try:
            await query.edit_message_text(text, reply_markup=markup)
            state = _panel_state(context)
            if query.message is not None:
                state["msg"] = (query.message.chat_id, query.message.message_id)
                try:
                    context.user_data[PANEL_KEY] = state
                except (AttributeError, TypeError):
                    pass
            # R42: صفحهٔ پنل هم تایمر حذف دارد (زمان پنل — همان ۲۰ ثانیه)
            _schedule_panel_delete(update, context)
            return
        except TelegramError as err:
            logger.info("ویرایش پنل گروه ممکن نشد: %s", err)

    message = update.effective_message
    if message:
        sent = await message.reply_text(text, reply_markup=markup)
        if sent is not None:
            state = _panel_state(context)
            state["msg"] = (message.chat_id, sent.message_id)
            try:
                context.user_data[PANEL_KEY] = state
            except (AttributeError, TypeError):
                pass
            # R42: پیام تازهٔ پنل هم با تایمر «panel» حذف می‌شود
            _schedule_panel_delete(update, context, sent.message_id)


def _schedule_panel_delete(update, context, message_id=None, chat_id=None):
    """R29: زمان‌بندی حذف پیام پنل (صفحهٔ کیفیت/قسمت) با تایمر «panel»."""
    query = update.callback_query if update is not None else None
    message = update.effective_message if update is not None else None
    if query is not None and query.message is not None:
        chat_id = chat_id or query.message.chat_id
        message_id = message_id or query.message.message_id
    elif message is not None:
        chat_id = chat_id or message.chat_id
    if not chat_id or not message_id:
        return
    schedule_delete(context, chat_id, [message_id], kind="panel")


async def deliver_group_panel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    share_code: str,
) -> bool:
    """ورودی لینک فصل. True = رسیدگی شد (حتی اگر خطا داده شد)."""
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return False

    track_user(update)

    group = db.get_group_link(share_code)
    if not group:
        return False

    if (group.get("status") or "active") != "active":
        await message.reply_text(Msg.GROUP_LINK_INACTIVE)
        return True

    missing = await get_not_joined_channels(user.id, context)
    if missing:
        await send_join_prompt(update, context, share_code, missing)
        return True

    payload = render_qualities(group)
    if not payload:
        # R26-fix: پیام شفاف + لاگ تشخیصی (قبلاً فقط «فایلی موجود نیست»
        # بود و علت معلوم نمی‌شد).
        all_links = db.get_group_links(
            group.get("anime_name") or "",
            group.get("season_num") or "",
            group.get("part_num") or "",
        )
        same_name = db.get_upload_groups(group.get("anime_name") or "")
        logger.warning(
            "پنل فصل خالی است: code=%s name=%r season=%r part=%r type=%r | "
            "لینک‌های همین کلید=%s (فعال=%s) | گروه‌های همین نام در "
            "uploads=%s",
            group.get("share_code"),
            group.get("anime_name"),
            group.get("season_num"),
            group.get("part_num"),
            group.get("anime_type"),
            len(all_links),
            sum(
                1 for row in all_links
                if (row.get("status") or "active") == "active"
            ),
            [
                (g.get("season_num"), g.get("part_num"), g.get("links"))
                for g in same_name
            ],
        )
        other_groups = db.get_upload_groups(
            group.get("anime_name") or ""
        )
        if not all_links:
            text = Msg.GROUP_LINK_EMPTY
            if len(other_groups) > 1:
                text += "\n" + Msg.GROUP_LINK_OTHER_SEASONS
        else:
            text = Msg.GROUP_LINK_ALL_INACTIVE
        await message.reply_text(text)
        return True

    text, markup = payload
    # R42: خودِ پیام پنل (کیفیت‌ها/قسمت‌ها) با تایمر «پنل» حذف می‌شود
    # (زمان پنل؛ اگر تنظیم نشده باشد از زمان فایل‌ها ارث می‌برد).
    # R43: هیچ خط اطلاع‌رسانی زیر متن پنل نمی‌آید (درخواست کاربر).
    context.user_data[PANEL_KEY] = {
        "code": share_code,
        "quality": None,
        "page": 0,
        "msg": None,
    }
    panel_msg = await message.reply_text(text, reply_markup=markup)
    if panel_msg is not None:
        state = context.user_data.get(PANEL_KEY) or {}
        state["msg"] = (message.chat_id, panel_msg.message_id)
        context.user_data[PANEL_KEY] = state
        # R42: تایمر «panel» برای همین پیام — دقیقاً مثل قبل (R29)
        _schedule_panel_delete(
            None, context, panel_msg.message_id, chat_id=message.chat_id
        )
    return True


# ---------------------------------------------------------------------------
# هندلر callback پنل
# ---------------------------------------------------------------------------
def _quality_rows(group: Dict[str, Any]) -> List[Dict[str, Any]]:
    """R38: کیفیت‌های همین گروه (برای تطبیق کد دکمه با فهرست فعلی)."""
    try:
        rows = db.get_group_qualities(group)
    except Exception:          # noqa: BLE001 — پنل نباید به‌خاطر خطای DB بشکند
        logger.exception("خواندن کیفیت‌های پنل ناموفق بود")
        return []
    return rows or []


def _match_quality(group: Dict[str, Any], code: str) -> Optional[str]:
    """R38: کد دکمه ⇒ نام کیفیت (اگر دیگر وجود نداشته باشد None)."""
    for item in _quality_rows(group):
        quality = item.get("quality") or "نامشخص"
        if _code_part(quality) == code:
            return item.get("quality") or "نامشخص"
    return None


def _match_episode(
    group: Dict[str, Any], quality: str, code: str
) -> Optional[str]:
    """R38: کد دکمه ⇒ بازهٔ قسمت (اگر دیگر وجود نداشته باشد None)."""
    for item in db.get_group_episodes(group, quality) or []:
        episode = item.get("episode_range") or ""
        if _code_part(episode) == code:
            return episode
    return None


async def handle_group_panel_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> Optional[int]:
    """R39: دکمه‌های پنل کاربر (کیفیت‌ها ⇄ قسمت‌ها).

    کیفیت/قسمت در state همین پنل نگه داشته می‌شود. پیام پنل با تایمر
    «پنل» حذف می‌شود (R42) و بقیهٔ پنل‌های ربات مثل قبل با باز شدن پنل
    بعدی بسته می‌شوند (این پنل در `register_panels` نیست).
    """
    query = update.callback_query
    if not query or not query.data:
        return None

    data = query.data
    state = _panel_state(context)
    share_code = state.get("code")
    group = db.get_group_link(share_code) if share_code else None

    # --- دکمه‌های پنلِ منقضی/بسته‌شده ---
    if data.startswith(("gp_cancel", "gp_close")):
        await query.answer(Msg.GROUP_PANEL_CLOSED, show_alert=True)
        return None

    if not group:
        await query.answer(Msg.PANEL_CLOSED, show_alert=True)
        return None

    if (group.get("status") or "active") != "active":
        await query.answer(Msg.GROUP_LINK_INACTIVE, show_alert=True)
        return None

    parts = data.split(":")

    # --- انتخاب کیفیت ⇒ صفحهٔ قسمت‌ها ---
    if data.startswith("gp_q:"):
        code = parts[1] if len(parts) > 1 else ""
        quality = _match_quality(group, code)
        if not quality:
            await query.answer(Msg.GROUP_LINK_EMPTY, show_alert=True)
            return None
        state["quality"] = quality
        state["page"] = 0
        context.user_data[PANEL_KEY] = state

        # هوشمند (سینمایی/OVA تک‌قسمتی): لیست یک‌قسمتی نشان داده نمی‌شود
        episodes = db.get_group_episodes(group, quality)
        if len(episodes) == 1:
            await query.answer()
            await send_episode_files(
                update,
                context,
                group,
                quality,
                episodes[0].get("episode_range") or "",
            )
            return None

        payload = render_episodes(group, quality, 0)
        if not payload:
            await query.answer(Msg.GROUP_LINK_EMPTY, show_alert=True)
            return None
        await query.answer()
        await _show(update, context, payload[0], payload[1], edit=True)
        return None

    # --- صفحه‌بندی قسمت‌ها ---
    if data.startswith("gp_p:"):
        page = 0
        if len(parts) > 1:
            try:
                page = int(parts[1])
            except ValueError:
                page = 0
        quality = state.get("quality")
        if not quality:
            await query.answer(Msg.GROUP_PANEL_CLOSED, show_alert=True)
            return None
        payload = render_episodes(group, quality, page)
        if not payload:
            await query.answer(Msg.GROUP_LINK_EMPTY, show_alert=True)
            return None
        state["page"] = page
        context.user_data[PANEL_KEY] = state
        await query.answer()
        await _show(update, context, payload[0], payload[1], edit=True)
        return None

    # --- بازگشت به کیفیت‌ها ---
    if data.startswith("gp_back"):
        payload = render_qualities(group)
        if not payload:
            await query.answer(Msg.GROUP_LINK_EMPTY, show_alert=True)
            return None
        state.pop("quality", None)
        context.user_data[PANEL_KEY] = state
        await query.answer()
        await _show(update, context, payload[0], payload[1], edit=True)
        return None

    # --- ارسال فایل‌های یک قسمت ---
    if data.startswith("gp_e:"):
        code = parts[1] if len(parts) > 1 else ""
        quality = state.get("quality")
        if not quality:
            await query.answer(Msg.GROUP_PANEL_CLOSED, show_alert=True)
            return None
        episode = _match_episode(group, quality, code)
        if episode is None:
            await query.answer(Msg.GROUP_LINK_EMPTY, show_alert=True)
            return None
        await query.answer()
        await send_episode_files(update, context, group, quality, episode)
        return None

    await query.answer(Msg.INVALID_COMMAND)
    return None


# ---------------------------------------------------------------------------
# ارسال فایل‌ها
# ---------------------------------------------------------------------------
async def send_episode_files(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    group: Dict[str, Any],
    quality: str,
    episode: str,
) -> None:
    """همهٔ فایل‌های یک قسمت در یک کیفیت را ارسال می‌کند (+ حذف خودکار)."""
    user = update.effective_user
    chat = update.effective_chat
    query = update.callback_query
    message = update.effective_message

    if not user or not chat or (not message and not query):
        return

    rows = [
        row for row in db.get_group_links(
            group.get("anime_name", ""),
            group.get("season_num") or "",
            group.get("part_num") or "",
            episode_range=episode,
            anime_type=group.get("anime_type") or None,
        )
        if (row.get("quality") or "") == quality
    ]

    if not rows:
        if query:
            await query.answer(Msg.GROUP_LINK_EMPTY, show_alert=True)
        return

    missing = await get_not_joined_channels(user.id, context)
    if missing:
        await send_join_prompt(update, context, group.get("share_code"), missing)
        return

    chat_id = chat.id
    panel_ids: List[int] = []          # تایمر «panel»
    file_ids: List[int] = []           # تایمر «files» (مثل لینک عادی)
    failed_ids: List[int] = []
    final_msg_ids: List[int] = []      # پیام‌های پایانیِ هر آپلود (دکمهٔ گزارش)

    loop = asyncio.get_running_loop()
    prep = await message.reply_text(Msg.PREPARING) if message else None
    if prep:
        panel_ids.append(prep.message_id)

    sent_count = 0
    delivered: List[Dict[str, Any]] = []   # (upload_data، تعداد ارسال‌شده)
    delivered_sessions: List[str] = []

    for row in rows:
        if (row.get("status") or "active") != "active":
            continue

        session_id = row.get("session_id")
        upload_data = db.get_upload(session_id) if session_id else None
        if not upload_data:
            continue

        msg_ids = parse_id_list(upload_data.get("channel_msg_range"))
        if not msg_ids:
            continue

        raw_from = upload_data.get("channel_chat_id")
        try:
            from_chat_id = int(raw_from) if raw_from not in (None, "") else None
        except (TypeError, ValueError):
            from_chat_id = None
        if from_chat_id is None:
            from_chat_id = (
                int(config.DATABASES[0]["chat_id"]) if config.DATABASES else None
            )
        if from_chat_id is None:
            continue

        before = sent_count
        for msg_id in msg_ids:
            for attempt in (1, 2):
                try:
                    copied = await context.bot.copy_message(
                        chat_id=chat_id,
                        from_chat_id=from_chat_id,
                        message_id=msg_id,
                    )
                    file_ids.append(copied.message_id)
                    sent_count += 1
                    break
                except RetryAfter as error:
                    if attempt == 2:
                        failed_ids.append(msg_id)
                        break
                    await asyncio.sleep(error.retry_after + 1)
                except TelegramError as err:
                    logger.warning("ارسال فایل %s ناموفق بود: %s", msg_id, err)
                    failed_ids.append(msg_id)
                    break

        if sent_count > before:
            delivered.append(
                {
                    "upload": upload_data,
                    "count": sent_count - before,
                    "session_id": session_id,
                }
            )
            if session_id and session_id not in delivered_sessions:
                delivered_sessions.append(session_id)

    # آمار: برای هر لینکِ واقعاً ارسال‌شده یک رکورد دانلود ثبت می‌شود
    # (کلید خارجی downloads.session_id به uploads وصل است، نه به کد فصل).
    for session_id in delivered_sessions:
        try:
            db.record_download(session_id, user.id)
        except Exception as err:      # noqa: BLE001 — آمار نباید تحویل را بشکند
            logger.warning("ثبت دانلود ناموفق بود: %s", err)

    # R28: پیام پایانی + دکمهٔ گزارش، **دقیقاً** مثل لینک‌های عادی
    for item in delivered:
        upload_data = item["upload"]
        final_text = build_final_text(upload_data, item["count"])
        try:
            final_msg = await (message or query.message).reply_text(
                final_text,
                reply_markup=report_keyboard(str(item.get("session_id") or "")),
            )
        except TelegramError as err:
            logger.warning("ارسال پیام پایانی ناموفق بود: %s", err)
            continue
        final_msg_ids.append(final_msg.message_id)

    notice_id = None
    if delivered:
        # R31: پیام «🗑️ … ثانیه» جزو **فایل‌ها** است و باید دقیقاً با
        # همان‌ها (و با همان زمان) پاک شود — قبلاً اشتباهاً در سبد تایمر
        # «پنل» می‌رفت و زودتر پاک می‌شد (باگ گزارش‌شده).
        notice = await (message or query.message).reply_text(
            deletion_notice_text("files")
        )
        notice_id = notice.message_id

    finished_at = loop.time()

    # R30: پیام موقت «⏳ در حال آماده‌سازی…» بلافاصله بعد از پایان ارسال
    # پاک می‌شود (قبلاً تا ۳۰ ثانیه می‌ماند و با حذف فایل‌ها قاطی می‌شد).
    if prep is not None:
        try:
            await context.bot.delete_message(
                chat_id=chat_id, message_id=prep.message_id
            )
        except TelegramError as err:
            logger.info("حذف پیام آماده‌سازی ممکن نشد: %s", err)
        panel_ids = [mid for mid in panel_ids if mid != prep.message_id]

    # R28/R30: فایل‌ها و پیام‌های پایانی با تایمر «فایل‌های آپلود» پاک
    # می‌شوند — شمارش از **پایان ارسال** (یک زمان مشترک، بدون تکرار).
    if file_ids or notice_id:
        schedule_delete(
            context,
            chat_id,
            file_ids + ([notice_id] if notice_id else []),
            kind="files",
            start_at=finished_at,
        )
    for final_id in final_msg_ids:
        keep_report_button(
            context, chat_id, final_id, kind="files", start_at=finished_at
        )

    # R28: خودِ پنل (پیام‌های توضیحی) تایمر مستقل دارد
    if panel_ids:
        schedule_delete(context, chat_id, panel_ids, kind="panel")

    if failed_ids:
        # R22: با فهرست‌های بلند، پیام از سقف تلگرام رد نشود
        shown = failed_ids[:50]
        rest = len(failed_ids) - len(shown)
        header = "⚠️ بعضی پیام‌ها ارسال نشدند. لطفاً آیدی‌های زیر را بررسی کن:\n"
        if rest > 0:
            header = f"⚠️ {len(failed_ids)} پیام ارسال نشد. ۵۰ آیدی اول:\n"
        try:
            await (message or query.message).reply_text(
                header + ", ".join(str(mid) for mid in shown)
            )
        except TelegramError as err:
            logger.warning("ارسال فهرست خطا ناموفق بود: %s", err)
