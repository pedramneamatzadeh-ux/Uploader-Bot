from typing import List, Optional

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from .config import config
from .constants import ALL_QUALITIES, SETTINGS_BUTTON

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
    """منوی اصلی بر اساس نقش (R2): فقط مالک دکمه «تنظیمات» را می‌بیند."""
    rows = [_main_menu_row(row) for row in MAIN_MENU_ROWS]

    if (
        user_id is not None
        and config.OWNER_ID is not None
        and user_id == config.OWNER_ID
    ):
        rows[-1] = rows[-1] + [
            KeyboardButton(SETTINGS_BUTTON, style="primary")
        ]

    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


CANCEL_MENU = ReplyKeyboardMarkup(
    [[KeyboardButton("لغو آپلود", style="danger")]],
    resize_keyboard=True,
)


MANAGE_CANCEL_MENU = ReplyKeyboardMarkup(
    [[KeyboardButton("لغو", style="danger")]],
    resize_keyboard=True,
)


ANIME_TYPE_MENU = ReplyKeyboardMarkup(
    [
        [
            KeyboardButton("🎬 سینمایی", style="success"),
            KeyboardButton("📺 سریالی", style="success"),
        ],
        [KeyboardButton("لغو آپلود", style="danger")],
    ],
    resize_keyboard=True,
)


ONGOING_MENU_MARKUP = ReplyKeyboardMarkup(
    [
        ["آپلود قسمت جدید", "مدیریت انیمه‌ها"],
        ["بازگشت به منوی اصلی"],
    ],
    resize_keyboard=True,
)


ONGOING_CANCEL_MENU = ReplyKeyboardMarkup(
    [
        ["لغو"],
        ["بازگشت به منوی اصلی"],
    ],
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
        ["ندارد ➖"],
        ["لغو"],
        ["بازگشت به منوی اصلی"],
    ],
    resize_keyboard=True,
)


BROADCAST_CANCEL_MENU = ReplyKeyboardMarkup(
    [["لغو"]],
    resize_keyboard=True,
)


POST_MENU_MARKUP = ReplyKeyboardMarkup(
    [
        ["📤 آپلود پست", "📋 مدیریت پست‌ها"],
        ["بازگشت به منوی اصلی"],
    ],
    resize_keyboard=True,
)


POST_UPLOAD_CANCEL_MENU = ReplyKeyboardMarkup(
    [
        ["✅ تمام شد"],
        ["لغو"],
    ],
    resize_keyboard=True,
)


POST_CANCEL_MENU = ReplyKeyboardMarkup(
    [["لغو"]],
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
                    style="primary",
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


def part_keyboard() -> InlineKeyboardMarkup:
    """دکمه‌های ۱ تا ۴ + «پارت ندارد» زیر سؤال پارت (مرحله ۳ — R1)."""
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
                    "➖ پارت ندارد",
                    callback_data="pn:none",
                    style="primary",
                )
            ],
        ]
    )


def quality_multiselect_keyboard(
    selected: List[str],
) -> InlineKeyboardMarkup:
    """کیبورد چندانتخابی کیفیت‌ها: ضربه = سلکت/آنسلت + «ثبت انتخاب‌ها»."""
    keyboard = [
        [
            ib(
                ("✅ " if quality in selected else "") + quality,
                callback_data=f"mqs:{idx}",
                style="primary",
            )
        ]
        for idx, quality in enumerate(ALL_QUALITIES)
    ]

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
) -> InlineKeyboardMarkup:
    keyboard = [
        [
            ib(
                "480p",
                callback_data=f"{prefix}480p",
                style="primary",
            ),
            ib(
                "720p",
                callback_data=f"{prefix}720p",
                style="primary",
            ),
            ib(
                "1080p",
                callback_data=f"{prefix}1080p",
                style="primary",
            ),
        ],
        [
            ib(
                "720p x265",
                callback_data=f"{prefix}720p x265",
                style="primary",
            ),
            ib(
                "1080p x265",
                callback_data=f"{prefix}1080p x265",
                style="primary",
            ),
        ],
    ]

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
    return InlineKeyboardMarkup(
        [
            [
                ib(
                    "480p",
                    callback_data=f"set_quality:480p:{session_id}",
                    style="primary",
                ),
                ib(
                    "720p",
                    callback_data=f"set_quality:720p:{session_id}",
                    style="primary",
                ),
                ib(
                    "1080p",
                    callback_data=f"set_quality:1080p:{session_id}",
                    style="primary",
                ),
            ],
            [
                ib(
                    "720p x265",
                    callback_data=(
                        f"set_quality:720p x265:{session_id}"
                    ),
                    style="primary",
                ),
                ib(
                    "1080p x265",
                    callback_data=(
                        f"set_quality:1080p x265:{session_id}"
                    ),
                    style="primary",
                ),
            ],
            [
                ib(
                    "❌ لغو",
                    callback_data=f"view_link:{session_id}",
                )
            ],
        ]
    )


def build_add_quality_keyboard(
    session_id: str,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                ib(
                    "480p",
                    callback_data="aq_480p",
                    style="primary",
                ),
                ib(
                    "720p",
                    callback_data="aq_720p",
                    style="primary",
                ),
                ib(
                    "1080p",
                    callback_data="aq_1080p",
                    style="primary",
                ),
            ],
            [
                ib(
                    "720p x265",
                    callback_data="aq_720p x265",
                    style="primary",
                ),
                ib(
                    "1080p x265",
                    callback_data="aq_1080p x265",
                    style="primary",
                ),
            ],
            [
                ib(
                    "❌ لغو",
                    callback_data=f"view_link:{session_id}",
                )
            ],
        ]
    )


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
