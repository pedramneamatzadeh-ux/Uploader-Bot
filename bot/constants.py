# ============================================================================
# حالت‌های ConversationHandler
# ============================================================================

# نکته مرحله ۳ (R1): MULTI_CHOICE / QUALITY / CHANNEL_RANGE /
# MULTI_QUALITY_ASK_MORE دیگر در فلوی آپلود استفاده نمی‌شوند
# (انتخاب «تک/چند کیفیت» با «چندانتخابی کیفیت + ثبت» جایگزین شد).
# عدد آن‌ها حفظ شده تا شماره بقیه stateها تغییر نکند.
(
    DB_SELECT,
    ANIME_TYPE,
    ANIME_NAME,
    MOVIE_NUM,
    SEASON_NUM,
    PART_NUM,
    EPISODE_RANGE,
    MULTI_CHOICE,
    QUALITY,
    CHANNEL_RANGE,
    MULTI_QUALITY,
    MULTI_QUALITY_CHANNEL,
    MULTI_QUALITY_ASK_MORE,
    CONFIRM,
) = range(14)


(
    MANAGE_LIST,
    MANAGE_DETAIL,
    MANAGE_EDIT,
    MANAGE_SEARCH,
    MANAGE_STATS,
) = range(14, 19)


(
    ONGOING_MENU,
    ONGOING_LIST,
    ONGOING_CREATE_NAME,
    ONGOING_CREATE_SEASON,
    ONGOING_CREATE_PART,
    ONGOING_DETAIL,
    ONGOING_EDIT,
    ONGOING_UPLOAD_SELECT,
    ONGOING_UPLOAD_EPISODE,
    ONGOING_UPLOAD_MODE,
    ONGOING_UPLOAD_SINGLE_QUALITY,
    ONGOING_UPLOAD_SINGLE_RANGE,
    ONGOING_UPLOAD_MULTI_QUALITY,
    ONGOING_UPLOAD_MULTI_RANGE,
    ONGOING_UPLOAD_MULTI_ASK,
    ONGOING_UPLOAD_CONFIRM,
    ONGOING_UPLOAD_DB_SELECT,
) = range(19, 36)


(
    BROADCAST_INPUT,
    BROADCAST_CONFIRM,
) = range(36, 38)


(
    POST_MENU,
    POST_UPLOAD_NAME,
    POST_UPLOAD_MESSAGES,
    POST_MANAGE_LIST,
    POST_MANAGE_DETAIL,
) = range(38, 43)


# مرحله ۳ (R1): سؤال «وضعیت پخش» برای دیتابیس‌های سفارشی (بخشی از R7)
CUSTOM_AIRING = 43
# بازه ۴۴–۴۵ برای نیازهای احتمالی R1 مصرف نشد (رزرو بود)


# مرحله ۴ (R5): سطوح سلسله‌مراتبی «مدیریت فایل‌ها»
# سطح ۱ = MANAGE_LIST (اسامی) — سطح ۲ گروه فصل/پارت — سطح ۳ قسمت‌ها
# سطح ۴ کیفیت‌ها — سطح ۵ = MANAGE_DETAIL (جزئیات لینک)
MANAGE_GROUPS = 46
MANAGE_EPISODES = 47
MANAGE_QUALITIES = 48


# R2: پنل تنظیمات (فقط مالک) — بازه ۴۹–۵۴
(
    SETTINGS_PANEL,
    SETTINGS_ADMIN,
    SETTINGS_CHANNEL,
    SETTINGS_DURATION,
    SETTINGS_DB_NAME,
    SETTINGS_DB_CHAT,
) = range(49, 55)


# R10: خلاصه داستان فصل — بازه ۵۵–۵۶
(
    MANAGE_SUMMARY_TEXT,
    MANAGE_SUMMARY_PHOTO,
) = range(55, 57)


# دکمه ورود به پنل در منوی اصلی (فقط مالک) — باید با متن دکمه یکی باشد
SETTINGS_BUTTON = "⚙️ تنظیمات"


# ============================================================================
# کیفیت‌ها
# ============================================================================

ALL_QUALITIES = [
    "480p",
    "720p",
    "1080p",
    "720p x265",
    "1080p x265",
]


# ============================================================================
# فیلدهای قابل ویرایش
# ============================================================================

ALLOWED_UPLOAD_UPDATE_FIELDS = {
    "anime_name",
    "season_num",
    "part_num",
    "episode_range",
    "quality",
    "channel_msg_range",
    "anime_type",
}


ALLOWED_ONGOING_UPDATE_FIELDS = {
    "anime_name",
    "season_num",
    "part_num",
    "status",
}


UPLOAD_FIELD_MAP = {
    "name": "anime_name",
    "season": "season_num",
    "part": "part_num",
    "episode": "episode_range",
    "channel": "channel_msg_range",
    "quality": "quality",
}


ONGOING_FIELD_MAP = {
    "name": "anime_name",
    "season": "season_num",
    "part": "part_num",
}


# ============================================================================
# متن‌های ثابت
# ============================================================================

class Msg:
    ACCESS_DENIED = "❌ دسترسی غیرمجاز!"
    MAIN_MENU_PROMPT = "منوی اصلی:"

    ADMIN_WELCOME = (
        "🤖 سلام ادمین عزیز! لطفاً یک گزینه را انتخاب کن:"
    )

    USER_WELCOME = (
        "👋 سلام!\n"
        "این ربات مخصوص دریافت فایل‌های انیمه است.\n"
        "برای دسترسی، از لینک رسمی که ادمین می‌دهد استفاده کن."
    )

    INVALID_LINK = "❌ لینک نامعتبر یا منقضی شده است."
    LINK_INACTIVE = "🚧 این لینک در حال حاضر غیرفعال است."
    INVALID_RANGE = "⚠️ محدوده‌ی پیام ذخیره‌شده نامعتبر است."
    PREPARING = "🔄 در حال آماده‌سازی فایل‌ها..."
    UPLOAD_CANCELLED = "❌ فرآیند آپلود لغو شد."
    UPLOAD_CANCELLED_INLINE = "❌ آپلود لغو شد."
    UPLOAD_SAVED = "✅ آپلود با موفقیت ثبت شد."
    SAVE_ERROR = "❌ خطایی رخ داد. لطفاً دوباره تلاش کن."
    REPORT_SAVED = "✅ گزارش شما با موفقیت ثبت شد.\n"
    LINK_NOT_FOUND = "❌ لینک پیدا نشد!"
    INVALID_COMMAND = "⚠️ دستور نامعتبر!"

    NO_STORAGE_CHANNEL = (
        "❌ کانال ذخیره‌سازی برای این لینک مشخص نیست."
    )

    # ------------------------------------------------------------------
    # R2 — پنل تنظیمات (فقط مالک)
    # ------------------------------------------------------------------
    SETTINGS_TITLE = "⚙️ تنظیمات ربات"
    SETTINGS_CLOSED = "⚙️ تنظیمات بسته شد."

    ADD_ADMIN_PROMPT = (
        "👨‍💼 شناسه عددی ادمین جدید را بفرست\n"
        "(یا یکی از پیام‌های او را فوروارد کن):\n\n"
        "برای انصراف دکمه «❌ انصراف» را بزن."
    )
    ADD_CHANNEL_PROMPT = (
        "📢 یک پیام از کانال را فوروارد کن، "
        "یا @username / شناسه عددی بفرست:\n\n"
        "⚠️ ربات باید در کانال ادمین باشد.\n"
        "برای انصراف دکمه «❌ انصراف» را بزن."
    )
    ADD_DURATION_PROMPT = (
        "⏱ مدت حذف خودکار پیام‌ها را به «ثانیه» وارد کن.\n"
        "مثال: 600 (حداکثر 2592000 ثانیه = 30 روز)\n\n"
        "برای انصراف دکمه «❌ انصراف» را بزن."
    )
    ADD_DB_NAME_PROMPT = (
        "🗄️ نام دیتابیس سفارشی جدید را وارد کن:\n\n"
        "برای انصراف دکمه «❌ انصراف» را بزن."
    )
    ADD_DB_CHAT_PROMPT = (
        "🗄️ کانال مقصد این دیتابیس را مشخص کن:\n"
        "یک پیام از کانال را فوروارد کن یا شناسه عددی بفرست.\n\n"
        "برای انصراف دکمه «❌ انصراف» را بزن."
    )

    ADMIN_ID_INVALID = (
        "❌ شناسه نامعتبر است. فقط عدد صحیح مثبت یا فوروارد پست کاربر."
    )
    ADMIN_ALREADY = "ℹ️ این شناسه از قبل در لیست ادمین‌هاست."
    ADMIN_IS_OWNER = (
        "ℹ️ این شناسه مالک ربات است؛ مالک همیشه دسترسی دارد."
    )
    ADMIN_ADDED = "✅ ادمین جدید اضافه شد."
    ADMIN_REMOVED = "✅ ادمین حذف شد."

    CHANNEL_INVALID = (
        "❌ کانال نامعتبر است. پیامی از کانال فوروارد کن "
        "یا @username / شناسه عددی بفرست."
    )
    CHANNEL_CHECK_FAILED = (
        "❌ کانال پیدا نشد یا ربات به آن دسترسی ندارد."
    )
    CHANNEL_BOT_NOT_ADMIN = (
        "⚠️ ربات در این کانال ادمین نیست؛ "
        "اول ربات را ادمین کانال کن و دوباره تلاش کن."
    )
    CHANNEL_ALREADY = "ℹ️ این کانال از قبل در لیست است."
    CHANNEL_ADDED = "✅ کانال اجباری عضویت اضافه شد."
    CHANNEL_REMOVED = "✅ کانال از لیست حذف شد."

    DURATION_INVALID = (
        "❌ عدد نامعتبر است. بین 1 تا 2592000 ثانیه وارد کن."
    )
    DURATION_SET = "✅ مدت حذف خودکار پیام‌ها تنظیم شد."

    DB_NAME_INVALID = "❌ نام نامعتبر است (باید 1 تا 60 کاراکتر باشد)."
    DB_NAME_DUPLICATE = "❌ دیتابیسی با این نام از قبل وجود دارد."
    DB_CHAT_INVALID = (
        "❌ مقصد نامعتبر است. پیامی از کانال فوروارد کن یا شناسه عددی بفرست."
    )
    DB_ADDED = "✅ دیتابیس سفارشی اضافه شد."
    DB_REMOVED = (
        "✅ دیتابیس سفارشی از لیست حذف شد (فایل‌های موجود پاک نشدند)."
    )
