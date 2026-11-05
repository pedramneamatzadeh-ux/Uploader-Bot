# -*- coding: utf-8 -*-
"""R16 — پنل «📛 فهرست اسم‌ها»: اسم‌های جستجوی اضافی.

سه دامنه (درخواست کاربر):
- کل انیمه (صفحهٔ سطح ۲ مدیریت) ⇒ روی همهٔ فصل/پارت/سینمایی‌هایش؛
- یک فصل/پارت/سینمایی (صفحهٔ قسمت‌ها / صفحهٔ کیفیت‌های سینمایی)؛
- یک لینک (صفحهٔ جزئیات لینک).

پنل = فهرست اسم‌های فعلی (هر کدام یک دکمهٔ قرمز حذف) + «➕ افزودن
اسم» + «◀️ بازگشت». افزودن در state جدید MANAGE_EXTRA_TEXT متن را
منتظر می‌ماند — چند اسم با «,» یا «،» (تصمیم کاربر: batch)، هر کدام
با validate_anime_name (تصمیم کاربر: فقط انگلیسی).

تصمیم کاربر: این اسم‌ها فقط در جستجوی مدیریت اثر می‌کنند و در
«پرش مستقیم» تک‌نتیجه‌ای هم استفاده می‌شوند (jump_to_extra_hit).

مثل بقیهٔ صفحات مدیریت، این پنل هم تک‌پیامی است: همهٔ رندرها با
safe_edit_or_send روی manage["list_message_id"] ⇒ بستن پنل R15
خودکار پوشش می‌دهد.
"""
import logging
import re
from typing import Any, Dict, List, Optional

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ...constants import (
    MANAGE_DETAIL,
    MANAGE_EPISODES,
    MANAGE_EXTRA_TEXT,
    MANAGE_GROUPS,
    MANAGE_QUALITIES,
)
from ...database import db
from ...keyboards import ib
from ...utils import safe_edit_or_send, validate_anime_name
from .common import _manage
from .detail import show_link_detail
from .episodes import show_episode_list
from .groups import show_group_list
from .qualities import show_quality_list

logger = logging.getLogger(__name__)

_SPLIT_PATTERN = re.compile(r"[,،]")


def _extra_kwargs(manage: Dict[str, Any]) -> Dict[str, Any]:
    """آرگومان‌های متدهای db برای دامنهٔ فعلی پنل."""
    extra = manage.get("extra") or {}
    scope = extra.get("scope", "anime")
    if scope == "group":
        return {
            "scope": scope,
            "real_names": [manage.get("name") or ""],
            "season_num": manage.get("season") or "",
            "part_num": manage.get("part") or "",
        }
    if scope == "link":
        return {
            "scope": scope,
            "real_names": [extra.get("anime_name") or ""],
            "session_id": extra.get("session") or "",
        }
    return {"scope": "anime", "real_names": list(manage.get("names") or [])}


def _scope_group_text(manage: Dict[str, Any]) -> str:
    """برچسب فصل/پارت/سینمایی جاری (هم‌سبک برچسب‌های سطح ۲)."""
    season = manage.get("season") or ""
    part = manage.get("part") or ""
    if manage.get("is_cinema"):
        return f"سینمایی شماره {season}"
    text = f"فصل {season}" if season else "بدون فصل"
    if part:
        text += f" | پارت {part}"
    return text


def extras_ret_state(manage: Dict[str, Any]) -> int:
    """state صفحهٔ میزبان پنل — همان‌جا که پنل رویش ویرایش می‌شود."""
    extra = manage.get("extra") or {}
    scope = extra.get("scope", "anime")
    if scope == "link":
        return MANAGE_DETAIL
    if scope == "group":
        return (
            MANAGE_QUALITIES
            if extra.get("level") == 4
            else MANAGE_EPISODES
        )
    return MANAGE_GROUPS


async def show_extras_panel(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    scope: Optional[str] = None,
    session_id: Optional[str] = None,
) -> None:
    """رندر پنل 📛 — scope=None یعنی رندر مجدد همان پنل باز."""
    manage = _manage(context)
    extra = manage.setdefault("extra", {})

    if scope is not None:
        extra["scope"] = scope
        extra["level"] = manage.get("level", 2)
        if scope == "link":
            extra["session"] = session_id or ""
            link = db.get_upload_by_id(session_id or "")
            extra["anime_name"] = (link or {}).get("anime_name", "")

    names: List[str] = db.list_extra_names(**_extra_kwargs(manage))
    extra["names"] = names

    display = (
        manage.get("display_name")
        or manage.get("name")
        or "؟"
    )
    cur_scope = extra.get("scope", "anime")

    lines = [f"📛 فهرست اسم‌ها — «{display}»", ""]
    if cur_scope == "anime":
        lines.append("🎯 دامنه: کل انیمه (همهٔ فصل/پارت/سینمایی‌ها)")
    elif cur_scope == "group":
        lines.append(f"🎯 دامنه: فقط {_scope_group_text(manage)}")
    else:
        lines.append("🎯 دامنه: فقط این لینک")
    lines.append("")
    if names:
        lines.append(f"اسم‌های فعلی ({len(names)}):")
        lines.extend(f"{i + 1}. {n}" for i, n in enumerate(names))
    else:
        lines.append("هنوز اسم اضافی ندارد.")
    lines.append("")
    lines.append("این اسم‌ها فقط در جستجوی مدیریت اثر می‌کنند.")

    keyboard = [
        [
            ib(
                f"❌ {n}",
                callback_data=f"mg_extra_del:{i}",
                style="danger",
            )
        ]
        for i, n in enumerate(names)
    ]
    keyboard.append(
        [ib("➕ افزودن اسم", callback_data="mg_extra_add", style="success")]
    )
    keyboard.append([ib("◀️ بازگشت", callback_data="mg_extra_back")])

    msg_id = manage.get("list_message_id")
    new_id = await safe_edit_or_send(
        context, chat_id, "\n".join(lines),
        InlineKeyboardMarkup(keyboard), msg_id,
    )
    manage["list_message_id"] = new_id
    context.user_data["manage"] = manage


async def start_extras_add(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """پرامپت افزودن اسم — منتظر متن در MANAGE_EXTRA_TEXT."""
    manage = _manage(context)
    extra = manage.get("extra") or {}
    scope = extra.get("scope", "anime")

    if scope == "anime":
        where = "کل انیمه (همهٔ فصل/پارت/سینمایی‌ها)"
    elif scope == "group":
        where = f"فقط {_scope_group_text(manage)}"
    else:
        where = "فقط این لینک"

    text = (
        f"➕ افزودن اسم اضافی — {where}\n\n"
        "اسم انگلیسی را وارد کن:\n"
        "• چند اسم با «,» جدا شوند — مثال: one piece, attack on titan\n"
        "• اسم تکراری خودکار رد می‌شود.\n"
        "• این اسم‌ها فقط در جستجوی مدیریت اثر می‌کنند.\n\n"
        "برای لغو دکمهٔ زیر را بزن یا «لغو» بفرست."
    )
    keyboard = [[ib("◀️ بازگشت", callback_data="mg_extra_back")]]

    msg_id = manage.get("list_message_id")
    new_id = await safe_edit_or_send(
        context, chat_id, text, InlineKeyboardMarkup(keyboard), msg_id,
    )
    manage["list_message_id"] = new_id
    context.user_data["manage"] = manage


async def handle_extra_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """متن ورودی پنل 📛: افزودن گروهی اسم‌ها (state=MANAGE_EXTRA_TEXT)."""
    chat_id = update.message.chat_id
    manage = _manage(context)
    ret = extras_ret_state(manage)
    text = (update.message.text or "").strip()

    if text in ("لغو", "/cancel"):
        await show_extras_panel(chat_id, context)
        return ret

    parts = [p.strip() for p in _SPLIT_PATTERN.split(text) if p.strip()]
    valid: List[str] = []
    invalid: List[str] = []
    for part in parts:
        ok, _err = validate_anime_name(part)
        (valid if ok else invalid).append(part)

    if not valid:
        lines = ["❌ هیچ اسم معتبری پیدا نشد:"]
        if invalid:
            lines.append(
                "• «" + "، ".join(invalid) + "» — اسم باید انگلیسی "
                "باشد (حروف فارسی/عربی مجاز نیست)."
            )
        else:
            lines.append("• متن خالی بود.")
        lines.append("دوباره وارد کن یا «◀️ بازگشت» را بزن.")
        await update.message.reply_text("\n".join(lines))
        return MANAGE_EXTRA_TEXT

    added = db.add_extra_names(extra_names=valid, **_extra_kwargs(manage))
    dups = [v for v in valid if v not in added]

    lines = []
    if added:
        lines.append(f"✅ {len(added)} اسم اضافه شد: " + ", ".join(added))
    if dups:
        lines.append("➖ تکراری (رد شد): " + ", ".join(dups))
    if invalid:
        lines.append("❌ غیرانگلیسی (رد شد): " + ", ".join(invalid))
    await update.message.reply_text("\n".join(lines))

    await show_extras_panel(chat_id, context)
    return ret


async def render_extras_host(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """«◀️ بازگشت» پنل 📛 → رندر مجدد صفحهٔ میزبان."""
    manage = _manage(context)
    extra = manage.get("extra") or {}
    scope = extra.get("scope", "anime")

    if scope == "link":
        await show_link_detail(chat_id, context, extra.get("session") or "")
        return MANAGE_DETAIL
    if scope == "group":
        if extra.get("level") == 4:
            await show_quality_list(chat_id, context)
            return MANAGE_QUALITIES
        await show_episode_list(chat_id, context)
        return MANAGE_EPISODES
    await show_group_list(chat_id, context)
    return MANAGE_GROUPS


async def jump_to_extra_hit(
    update: Update,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    manage: Dict[str, Any],
    hit: Dict[str, Any],
) -> Optional[int]:
    """R16 «پرش مستقیم» (تصمیم کاربر): تک‌نتیجهٔ جستجو یک اسم
    فصل/پارت/سینمایی یا لینک باشد ⇒ همان صفحه باز می‌شود.

    hit یتیم (لینک/گروه حذف‌شده) ⇒ None تا جستجو به مسیر عادی
    (لیست سطح ۱) برگردد.
    """
    if hit.get("scope") == "link":
        session_id = hit.get("session_id") or ""
        if not session_id or not db.get_upload_by_id(session_id):
            return None
        await update.message.reply_text(
            "🔍 اسمِ این لینک پیدا شد — مستقیم به جزئیات می‌رویم."
        )
        await show_link_detail(chat_id, context, session_id)
        return MANAGE_DETAIL

    # ایمپورت تنبل: dispatch خودش extras را در سطح ماژول وارد می‌کند
    from .dispatch import _episode_sort_key

    entry = db.get_l1_entry_for(hit.get("anime_name") or "")
    if not entry:
        return None

    season = hit.get("season_num") or ""
    part = hit.get("part_num") or ""
    member = None
    for m in entry.get("members") or []:
        if (
            m.get("anime_name") == hit.get("anime_name")
            and (m.get("season_num") or "") == season
            and (m.get("part_num") or "") == part
        ):
            member = m
            break
    if member is None:
        return None

    manage.update({
        "display_name": entry.get("display_name") or hit["anime_name"],
        "names": list(entry.get("names") or [hit["anime_name"]]),
        "name": member.get("anime_name") or hit["anime_name"],
        "season": member.get("season_num") or "",
        "part": member.get("part_num") or "",
        "group_type": member.get("anime_type") or "",
        "is_cinema": bool(member.get("is_cinema")),
        "l2": entry.get("members") or [],
    })
    manage.pop("episode", None)
    manage.pop("l4", None)
    manage.pop("extra", None)
    context.user_data["manage"] = manage

    if member.get("session_id"):
        # B1: عضو لینک‌محور ⇒ صفحهٔ همان گروه = جزئیات لینک
        await update.message.reply_text(
            "🔍 مستقیم به جزئیات لینک می‌رویم."
        )
        await show_link_detail(chat_id, context, member["session_id"])
        return MANAGE_DETAIL

    if manage["is_cinema"]:
        manage["l4"] = db.get_group_links(
            manage["name"],
            manage["season"],
            manage["part"],
            episode_range=None,
            anime_type=manage["group_type"],
        )
        context.user_data["manage"] = manage
        await update.message.reply_text(
            "🔍 اسمِ این سینمایی پیدا شد — مستقیم به فهرست کیفیت‌ها می‌رویم."
        )
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
    manage["ep_page"] = 0
    context.user_data["manage"] = manage
    await update.message.reply_text(
        "🔍 اسمِ این فصل/پارت پیدا شد — مستقیم به فهرست قسمت‌ها می‌رویم."
    )
    await show_episode_list(chat_id, context)
    return MANAGE_EPISODES
