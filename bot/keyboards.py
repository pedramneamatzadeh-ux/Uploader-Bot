from typing import List, Optional

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from .config import config
from .constants import ALL_QUALITIES, OTHER_SEASONS, QUALITY_ROWS, SETTINGS_BUTTON

# ---------------------------------------------------------------------------
# رنگ دکمه‌ها (Bot API 9.4 — style: primary/success/danger)
# ---------------------------------------------------------------------------

# قرمز: بازگشت/منوی اصلی/خیر + حذف/لغو/انصراف؛ بقیه سبز (primary فقط با style صریح)
_RED_WORDS = ("خیر", "بازگشت", "منوی اصلی", "حذف", "لغو", "انصراف")


def _infer_style(text: str, callback_data: str = "") -> Optional[str]:
    """استنتاج رنگ دکمه از برچسب/داده callback وقتی style صریح نباشد."""
    if any(word in text for word in _RED_WORDS):
        return "danger"
    if any(
        token in callback_data
        for token in ("_del", ":del", "delete")
    ):
        return "danger"
    return "success"


def ib(
    text: str,
    style: Optional[str] = None,
    **kwargs,
):
    """InlineKeyboardButton با رنگ خودکار؛ style صریح مقدم است."""
    if style is None:
        style = _infer_style(text, str(kwargs.get("callback_data") or ""))
    if style:
        kwargs["style"] = style
    return InlineKeyboardButton(text, **kwargs)




MAIN_MENU_ROWS = [
    ["آپلود", "مدیریت فایل‌ها", "آمار"],
    ["انیمه‌های درحال پخش"],
    ["📢 پیام همگانی", "📝 پست‌ها"],
    ["💾 بک‌آپ"],
]

# رنگ دکمه‌های منوی اصلی (باقیمانده → primary)
MAIN_MENU_STYLES = {
    "آپلود": "success",
    SETTINGS_BUTTON: "primary",
}


def _main_menu_row(row: list) -> list:
    return [
        KeyboardButton(text, style=MAIN_MENU_STYLES.get(text, "primary"))
        for text in row
    ]


MAIN_MENU = ReplyKeyboardMarkup(
    [_main_menu_row(row) for row in MAIN_MENU_ROWS],
    resize_keyboard=True,
)


def main_menu_for(user_id: Optional[int]) -> ReplyKeyboardMarkup:
    """منوی اصلی بر اساس نقش (R2+B13): مالک و ادمین‌ها دکمهٔ
    «تنظیمات» را می‌بینند — ولی ورودی آن owner_only است، پس برای
    ادمین‌ها کار نمی‌کند (فقط «دسترسی ندارید»)."""
    rows = [_main_menu_row(row) for row in MAIN_MENU_ROWS]

    if user_id is not None and (
        user_id == config.OWNER_ID
        or user_id in config.ADMIN_IDS
    ):
        rows[-1] = rows[-1] + [
            KeyboardButton(SETTINGS_BUTTON, style="primary")
        ]

    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


# R17: لغو اینلاینِ پرامپت‌های متنیِ فلؤ آپلود اصلی — جایگزین
# ریپلای‌کیبورد CANCEL_MENU در این فلو (ریپلای‌کیبورد لغو آپلود کلاً
# حذف شد؛ CANCEL_MENU خودش برای ongoing/posts دست‌نخورده ماند).
UPLOAD_CANCEL_INLINE = InlineKeyboardMarkup(
    [[ib("لغو آپلود", callback_data="cancel_prompt", style="danger")]]
)

CANCEL_MENU = ReplyKeyboardMarkup(
    [[KeyboardButton("لغو آپلود", style="danger")]],
    resize_keyboard=True,
)


MANAGE_CANCEL_MENU = ReplyKeyboardMarkup(
    [[KeyboardButton("لغو", style="danger")]],
    resize_keyboard=True,
)


ONGOING_CANCEL_MENU = ReplyKeyboardMarkup(
    [[KeyboardButton("لغو", style="danger")]],
    resize_keyboard=True,
)


PART_NUM_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("ندارد ➖", style="primary")],
        [KeyboardButton("لغو آپلود", style="danger")],
    ],
    resize_keyboard=True,
)


ONGOING_PART_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("ندارد ➖", style="primary")],
        [KeyboardButton("لغو", style="danger")],
    ],
    resize_keyboard=True,
)


BROADCAST_CANCEL_MENU = ReplyKeyboardMarkup(
    [[KeyboardButton("لغو", style="danger")]],
    resize_keyboard=True,
)


POST_UPLOAD_CANCEL_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("✅ تمام شد", style="success")],
        [KeyboardButton("لغو", style="danger")],
    ],
    resize_keyboard=True,
)


POST_CANCEL_MENU = ReplyKeyboardMarkup(
    [[KeyboardButton("لغو", style="danger")]],
    resize_keyboard=True,
)


# ============================================================================
# R2 — کیبوردهای پنل تنظیمات (فقط مالک)
# ============================================================================


def settings_panel_keyboard() -> InlineKeyboardMarkup:
    """صفحه اصلی پنل تنظیمات."""
    return InlineKeyboardMarkup(
        [
            [
                ib(
                    "👨‍💼 ادمین‌ها", callback_data="st:admins"
                ),
                ib(
                    "📢 کانال‌های اجباری", callback_data="st:channels"
                ),
            ],
            [
                ib(
                    "⏱ مدت حذف پیام",
                    callback_data="st:duration",
                    style="success",
                ),
                ib(
                    "🗄️ دیتابیس‌های سفارشی", callback_data="st:dbs"
                ),
            ],
            [
                ib(
                    "🔄 به‌روزرسانی", callback_data="st:panel"
                ),
                ib(
                    "🔙 بازگشت", callback_data="st:back"
                ),
            ],
        ]
    )


def settings_admins_keyboard(
    admin_ids: List[int],
    owner_id: Optional[int],
) -> InlineKeyboardMarkup:
    rows = [
        [
            ib(
                f"❌ {admin_id}", callback_data=f"st:adm_del:{admin_id}"
            )
        ]
        for admin_id in admin_ids
        if owner_id is None or admin_id != owner_id
    ]
    rows.append(
        [ib("➕ افزودن ادمین", callback_data="st:adm_add")]
    )
    rows.append(
        [ib("🔙 بازگشت", callback_data="st:panel")]
    )
    return InlineKeyboardMarkup(rows)


def settings_channels_keyboard(channels: List) -> InlineKeyboardMarkup:
    rows = []
    for idx, channel in enumerate(channels):
        label = str(channel)
        rows.append(
            [
                ib(
                    f"❌ {label}", callback_data=f"st:ch_del:{idx}"
                )
            ]
        )
    rows.append(
        [ib("➕ افزودن کانال", callback_data="st:ch_add")]
    )
    rows.append(
        [ib("🔙 بازگشت", callback_data="st:panel")]
    )
    return InlineKeyboardMarkup(rows)


def settings_duration_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                ib(
                    "5 دقیقه", callback_data="st:dur:300"
                ),
                ib(
                    "10 دقیقه", callback_data="st:dur:600"
                ),
                ib(
                    "30 دقیقه", callback_data="st:dur:1800"
                ),
            ],
            [
                ib(
                    "1 ساعت", callback_data="st:dur:3600"
                ),
                ib(
                    "24 ساعت", callback_data="st:dur:86400"
                ),
            ],
            [
                ib(
                    "📝 مقدار دلخواه", callback_data="st:dur_custom"
                )
            ],
            [
                ib(
                    "🔙 بازگشت", callback_data="st:panel"
                )
            ],
        ]
    )


def settings_databases_keyboard(databases: List[dict]) -> InlineKeyboardMarkup:
    rows = [
        [
            ib(
                f"❌ {row['name']}",
                callback_data=f"st:db_del:{row['id']}",
            )
        ]
        for row in databases
    ]
    rows.append(
        [
            ib(
                "➕ دیتابیس جدید", callback_data="st:db_add"
            )
        ]
    )
    rows.append(
        [ib("🔙 بازگشت", callback_data="st:panel")]
    )
    return InlineKeyboardMarkup(rows)


def settings_confirm_keyboard(
    yes_callback: str,
    no_callback: str,
) -> InlineKeyboardMarkup:
    """دکمه‌های تأیید/انصراف حذف."""
    return InlineKeyboardMarkup(
        [
            [
                ib(
                    "✅ بله، حذف کن", callback_data=yes_callback
                ),
                ib("❌ خیر", callback_data=no_callback),
            ]
        ]
    )


def settings_input_keyboard() -> InlineKeyboardMarkup:
    """دکمه انصراف زیر پیام‌های ورودی متنی پنل."""
    return InlineKeyboardMarkup(
        [
            [
                ib(
                    "❌ انصراف", callback_data="st:cancel"
                )
            ]
        ]
    )


def db_select_page1_keyboard(
    databases: List[dict],
    has_custom_database: bool,
) -> InlineKeyboardMarkup:
    """صفحه ۱ انتخاب دیتابیس: همیشه دیتابیس‌های اصلی (مرحله ۳ — R1)."""
    keyboard = [
        [
            ib(
                f"🗄️ {entry['name']}",
                callback_data=f"dbsel:{idx}",
                style="primary",
            )
        ]
        for idx, entry in enumerate(databases)
    ]

    if has_custom_database:
        keyboard.append(
            [
                ib(
                    "🗃️ دیتابیس‌های سفارشی ▶️",
                    callback_data="dbsel_pg2",
                    style="success",
                )
            ]
        )

    keyboard.append(
        [ib("❌ لغو", callback_data="dbsel_cancel")]
    )
    return InlineKeyboardMarkup(keyboard)


def db_select_page2_keyboard(
    custom_databases: List[dict],
) -> InlineKeyboardMarkup:
    """صفحه ۲ انتخاب دیتابیس: فقط لیست دیتابیس‌های سفارشی (بدون دکمه افزودن)."""
    keyboard = [
        [
            ib(
                f"🗄️ {row['name']}",
                callback_data=f"dbsel_c:{idx}",
                style="primary",
            )
        ]
        for idx, row in enumerate(custom_databases)
    ]

    keyboard.append(
        [
            ib(
                "◀️ دیتابیس‌های اصلی",
                callback_data="dbsel_pg1",
            )
        ]
    )
    keyboard.append(
        [ib("❌ لغو", callback_data="dbsel_cancel")]
    )
    return InlineKeyboardMarkup(keyboard)


def anime_type_keyboard() -> InlineKeyboardMarkup:
    """B11: «سینمایی یا سریالی» به‌صورت inline (هم‌شکل وضعیت پخش)."""
    return InlineKeyboardMarkup(
        [
            [
                ib("🎬 سینمایی", callback_data="uptype:movie"),
                ib("📺 سریالی", callback_data="uptype:series"),
            ],
            [ib("لغو آپلود", callback_data="uptype:cancel")],
        ]
    )


def airing_status_keyboard() -> InlineKeyboardMarkup:
    """سؤال «وضعیت پخش» برای دیتابیس‌های سفارشی (مرحله ۳ — R7)."""
    return InlineKeyboardMarkup(
        [
            [
                ib(
                    "⏳ درحال پخش",
                    callback_data="airing:ongoing",
                )
            ],
            [
                ib(
                    "✅ اتمام پخش",
                    callback_data="airing:finished",
                )
            ],
            [
                ib(
                    "❌ لغو",
                    callback_data="dbsel_cancel",
                )
            ],
        ]
    )


def season_keyboard() -> InlineKeyboardMarkup:
    """دکمه‌های ۱ تا ۴ + «سایر» زیر سؤال فصل (مرحله ۳ — R1)."""
    return InlineKeyboardMarkup(
        [
            [
                ib("1", callback_data="sn:1", style="primary"),
                ib("2", callback_data="sn:2", style="primary"),
            ],
            [
                ib("3", callback_data="sn:3", style="primary"),
                ib("4", callback_data="sn:4", style="primary"),
            ],
            [
                ib(
                    "📝 سایر (OVA/ONA/…)",
                    callback_data="sn:other",
                    style="success",
                )
            ],
        ]
    )


def movie_keyboard() -> InlineKeyboardMarkup:
    """دکمه‌های ۱ تا ۴ زیر سؤال «سینمایی چندم هست؟» (مرحله ۳ — R1)."""
    return InlineKeyboardMarkup(
        [
            [
                ib("1", callback_data="mn:1", style="primary"),
                ib("2", callback_data="mn:2", style="primary"),
            ],
            [
                ib("3", callback_data="mn:3", style="primary"),
                ib("4", callback_data="mn:4", style="primary"),
            ],
        ]
    )


def part_keyboard(other: bool = False) -> InlineKeyboardMarkup:
    """دکمه‌های ۱ تا ۴ + «ندارد» زیر سؤال پارت/شماره (مرحله ۳ — R1).

    R17: «ندارد» قرمز است؛ برای فصل‌های «سایر» (OVA/ONA/Special —
    other=True) که سؤال «شماره چند هست؟» می‌شود، برچسب «شماره ندارد».
    """
    none_label = "شماره ندارد" if other else "پارت ندارد"
    return InlineKeyboardMarkup(
        [
            [
                ib("1", callback_data="pn:1", style="primary"),
                ib("2", callback_data="pn:2", style="primary"),
            ],
            [
                ib("3", callback_data="pn:3", style="primary"),
                ib("4", callback_data="pn:4", style="primary"),
            ],
            [
                ib(
                    f"➖ {none_label}",
                    callback_data="pn:none",
                    style="danger",
                )
            ],
        ]
    )


def season_other_keyboard() -> InlineKeyboardMarkup:
    """R17: زیرصفحهٔ «📝 سایر» — دکمه‌های OVA/ONA/Special + لغو.

    مثل خود سؤال فصل، تایپ دستی هم مجاز است (state همان SEASON_NUM
    می‌ماند و receive_season_num متن را می‌گیرد).
    """
    rows = [
        [
            ib(s, callback_data=f"sn_other:{s}", style="primary")
            for s in OTHER_SEASONS
        ],
        [ib("لغو آپلود", callback_data="cancel_prompt", style="danger")],
    ]
    return InlineKeyboardMarkup(rows)


def quality_multiselect_keyboard(
    selected: List[str],
    bluray: int = 0,
) -> InlineKeyboardMarkup:
    """کیبورد چندانتخابی کیفیت‌ها: ضربه = سلکت/آنسلت + «ثبت انتخاب‌ها»."""
    # B22: ردیف‌های کیفیت همان چیدمان QUALITY_ROWS (هر x265 با AV1
    # هم‌ردیف). idx = جایگاه در ALL_QUALITIES (flat) ⇒ mqs:idx بدون تغییر.
    keyboard = []
    idx = 0
    for row in QUALITY_ROWS:
        buttons = []
        for quality in row:
            buttons.append(
                ib(
                    ("✅ " if quality in selected else "") + quality,
                    callback_data=f"mqs:{idx}",
                    style="primary",
                )
            )
            idx += 1
        keyboard.append(buttons)

    # B20: تاگل بلوری — ضربه = تیک می‌خورد/برمی‌دارد
    keyboard.append(
        [
            ib(
                (
                    "✅ بلوری (Blu-ray)"
                    if bluray
                    else "🖨 بلوری (Blu-ray)"
                ),
                callback_data="bluray_toggle",
                style="primary",
            )
        ]
    )

    keyboard.append(
        [
            ib(
                f"✅ ثبت انتخاب‌ها ({len(selected)})",
                callback_data="mqs_go",
            )
        ]
    )
    keyboard.append(
        [ib("❌ لغو", callback_data="mqs_cancel")]
    )
    return InlineKeyboardMarkup(keyboard)


def quality_keyboard(
    prefix: str,
    cancel_callback: Optional[str] = None,
    bluray: Optional[int] = None,
) -> InlineKeyboardMarkup:
    """B19: ردیف‌ها از QUALITY_ROWS ساخته می‌شوند."""
    keyboard = [
        [
            ib(
                quality,
                callback_data=f"{prefix}{quality}",
                style="primary",
            )
            for quality in row
        ]
        for row in QUALITY_ROWS
    ]

    # B20: تاگل بلوری — فقط وقتی caller مقدار bluray بدهد
    if bluray is not None:
        keyboard.append(
            [
                ib(
                    (
                        "✅ بلوری (Blu-ray)"
                        if bluray
                        else "🖨 بلوری (Blu-ray)"
                    ),
                    callback_data="ogup_bluray",
                    style="primary",
                )
            ]
        )

    if cancel_callback:
        keyboard.append(
            [
                ib(
                    "❌ لغو",
                    callback_data=cancel_callback,
                )
            ]
        )

    return InlineKeyboardMarkup(keyboard)


def build_quality_edit_keyboard(
    session_id: str,
) -> InlineKeyboardMarkup:
    """B19: ردیف‌ها از QUALITY_ROWS ساخته می‌شوند."""
    keyboard = [
        [
            ib(
                quality,
                callback_data=(
                    f"set_quality:{quality}:{session_id}"
                ),
                style="primary",
            )
            for quality in row
        ]
        for row in QUALITY_ROWS
    ]
    keyboard.append(
        [
            ib(
                "❌ لغو",
                callback_data=f"view_link:{session_id}",
            )
        ]
    )
    return InlineKeyboardMarkup(keyboard)


def build_add_quality_keyboard(
    session_id: str,
) -> InlineKeyboardMarkup:
    """B19: ردیف‌ها از QUALITY_ROWS ساخته می‌شوند."""
    keyboard = [
        [
            ib(
                quality,
                callback_data=f"aq_{quality}",
                style="primary",
            )
            for quality in row
        ]
        for row in QUALITY_ROWS
    ]
    keyboard.append(
        [
            ib(
                "❌ لغو",
                callback_data=f"view_link:{session_id}",
            )
        ]
    )
    return InlineKeyboardMarkup(keyboard)


def build_pagination_row(
    page: int,
    total_pages_count: int,
    previous_callback: str,
    refresh_callback: str,
    next_callback: str,
) -> List[InlineKeyboardButton]:
    row: List[InlineKeyboardButton] = []

    if page > 0:
        row.append(
            ib(
                "◀️ قبلی",
                callback_data=previous_callback,
            )
        )

    row.append(
        ib(
            "🔄",
            callback_data=refresh_callback,
        )
    )

    if page < total_pages_count - 1:
        row.append(
            ib(
                "▶️ بعدی",
                callback_data=next_callback,
            )
        )

    return row


def quality_pattern_string() -> str:
    import re

    escaped = [
        re.escape(quality)
        for quality in ALL_QUALITIES
    ]

    return "|".join(escaped)
