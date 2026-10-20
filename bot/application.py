import logging
import re

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from .config import config
from .constants import (
    ANIME_NAME,
    ANIME_TYPE,
    BROADCAST_CONFIRM,
    BROADCAST_INPUT,
    CONFIRM,
    CUSTOM_AIRING,
    DB_SELECT,
    EPISODE_RANGE,
    MANAGE_DETAIL,
    MANAGE_EDIT,
    MANAGE_EPISODES,
    MANAGE_GROUPS,
    MANAGE_LIST,
    MANAGE_QUALITIES,
    MANAGE_SEARCH,
    MANAGE_STATS,
    MANAGE_SUMMARY_PHOTO,
    MANAGE_SUMMARY_TEXT,
    MOVIE_NUM,
    MULTI_QUALITY,
    MULTI_QUALITY_CHANNEL,
    ONGOING_CREATE_NAME,
    ONGOING_CREATE_PART,
    ONGOING_CREATE_SEASON,
    ONGOING_DETAIL,
    ONGOING_EDIT,
    ONGOING_LIST,
    ONGOING_MENU,
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
    PART_NUM,
    POST_MANAGE_DETAIL,
    POST_MANAGE_LIST,
    POST_MENU,
    POST_UPLOAD_MESSAGES,
    POST_UPLOAD_NAME,
    SEASON_NUM,
    SETTINGS_ADMIN,
    SETTINGS_CHANNEL,
    SETTINGS_DB_CHAT,
    SETTINGS_DB_NAME,
    SETTINGS_DURATION,
    SETTINGS_PANEL,
    SETTINGS_BUTTON,
)
from .keyboards import quality_pattern_string
from .handlers.backup import handle_backup
from .handlers.base import (
    handle_report_callback,
    recheck_callback,
    start,
)
from .handlers.broadcast import (
    cancel_broadcast,
    confirm_broadcast,
    receive_broadcast_message,
    start_broadcast,
)
from .handlers.management import (
    cancel_management,
    handle_edit_input,
    handle_management_callback,
    handle_search_input,
    handle_summary_photo,
    handle_summary_text,
    start_management,
)
from .handlers.ongoing import (
    cancel_ongoing,
    confirm_ongoing_upload,
    handle_ongoing_edit_input,
    handle_ongoing_manage_callback,
    handle_ongoing_upload_mode_callback,
    handle_ongoing_upload_select_callback,
    ongoing_menu_handler,
    ongoing_multi_ask_more_callback,
    ongoing_multi_quality_callback,
    ongoing_single_quality_callback,
    receive_ongoing_create_name,
    receive_ongoing_create_part,
    receive_ongoing_create_season,
    receive_ongoing_multi_range,
    receive_ongoing_single_range,
    receive_ongoing_upload_episode,
    select_ongoing_database,
    start_ongoing,
)
from .handlers.posts import (
    cancel_posts,
    handle_post_manage_callback,
    post_menu_handler,
    receive_post_messages,
    receive_post_name,
    start_posts,
)
from .handlers.stats import handle_stats_callback, show_stats
from .handlers.upload import (
    cancel_from_inline,
    cancel_upload,
    confirm_upload,
    movie_num_callback,
    multi_quality_channel_range,
    multiselect_callback,
    part_callback,
    receive_airing_status,
    receive_anime_name,
    receive_anime_type,
    receive_episode_range,
    receive_movie_num,
    receive_part_num,
    receive_season_num,
    season_callback,
    select_database,
    start_upload,
)
from .handlers.settings import (
    cancel_settings,
    open_settings,
    receive_admin_input,
    receive_channel_input,
    receive_db_chat_input,
    receive_db_name_input,
    receive_duration_input,
    settings_callback,
)


logger = logging.getLogger(__name__)


def _build_upload_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^آپلود$"), start_upload),
        ],
        states={
            # صفحه ۱ (اصلی) / صفحه ۲ (سفارشی) انتخاب دیتابیس
            DB_SELECT: [
                CallbackQueryHandler(
                    select_database,
                    pattern=(
                        r"^(dbsel:\d+|dbsel_pg1|dbsel_pg2"
                        r"|dbsel_c:\d+|dbsel_cancel)$"
                    ),
                )
            ],
            # سؤال وضعیت پخش فقط برای دیتابیس‌های سفارشی (R7)
            CUSTOM_AIRING: [
                CallbackQueryHandler(
                    receive_airing_status,
                    pattern=r"^(airing:ongoing|airing:finished)$",
                )
            ],
            ANIME_TYPE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_anime_type)
            ],
            ANIME_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_anime_name)
            ],
            MOVIE_NUM: [
                CallbackQueryHandler(
                    movie_num_callback, pattern=r"^mn:\d+$"
                ),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_movie_num),
            ],
            SEASON_NUM: [
                CallbackQueryHandler(
                    season_callback,
                    pattern=r"^(sn:\d+|sn:other)$",
                ),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_season_num),
            ],
            PART_NUM: [
                CallbackQueryHandler(
                    part_callback,
                    pattern=r"^(pn:\d+|pn:none)$",
                ),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_part_num),
            ],
            EPISODE_RANGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_episode_range)
            ],
            # چندانتخابی کیفیت + ثبت انتخاب‌ها
            MULTI_QUALITY: [
                CallbackQueryHandler(
                    multiselect_callback,
                    pattern=r"^(mqs:\d+|mqs_go|mqs_cancel)$",
                )
            ],
            # پرسش محدوده پیام هر کیفیت، به ترتیب انتخاب
            MULTI_QUALITY_CHANNEL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, multi_quality_channel_range)
            ],
            CONFIRM: [
                CallbackQueryHandler(
                    confirm_upload,
                    pattern=r"^(confirm_save|next_ep|up_done"
                    r"|cancel_confirm)$",
                ),
            ],
        },
        fallbacks=[
            MessageHandler(filters.Regex("^لغو آپلود$"), cancel_upload),
            CallbackQueryHandler(
                cancel_from_inline,
                pattern=r"^(dbsel_cancel|cancel_multi)$",
            ),
        ],
        allow_reentry=True,
    )


def _build_ongoing_conversation(quality_pattern: str) -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(
                "^انیمه‌های درحال پخش$"), start_ongoing),
        ],
        states={
            ONGOING_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND,
                               ongoing_menu_handler),
            ],
            ONGOING_LIST: [
                CallbackQueryHandler(handle_ongoing_manage_callback),
            ],
            ONGOING_DETAIL: [
                CallbackQueryHandler(handle_ongoing_manage_callback),
            ],
            ONGOING_CREATE_NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_ongoing_create_name,
                ),
            ],
            ONGOING_CREATE_SEASON: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_ongoing_create_season,
                ),
            ],
            ONGOING_CREATE_PART: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_ongoing_create_part,
                ),
            ],
            ONGOING_EDIT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handle_ongoing_edit_input,
                ),
            ],
            ONGOING_UPLOAD_SELECT: [
                CallbackQueryHandler(handle_ongoing_upload_select_callback),
            ],
            ONGOING_UPLOAD_DB_SELECT: [
                CallbackQueryHandler(
                    select_ongoing_database,
                    pattern=r"^(og_dbsel:\d+|og_dbsel_cancel)$",
                ),
            ],
            ONGOING_UPLOAD_EPISODE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_ongoing_upload_episode,
                ),
            ],
            ONGOING_UPLOAD_MODE: [
                CallbackQueryHandler(
                    handle_ongoing_upload_mode_callback,
                    pattern=r"^(ogup_mode:(std3|multi|single)|ogup_cancel)$",
                ),
            ],
            ONGOING_UPLOAD_SINGLE_QUALITY: [
                CallbackQueryHandler(
                    ongoing_single_quality_callback,
                    pattern=f"^(ogup_q:({quality_pattern})|ogup_cancel)$",
                ),
            ],
            ONGOING_UPLOAD_SINGLE_RANGE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_ongoing_single_range,
                ),
            ],
            ONGOING_UPLOAD_MULTI_QUALITY: [
                CallbackQueryHandler(
                    ongoing_multi_quality_callback,
                    pattern=f"^(ogup_mq:({quality_pattern})|ogup_cancel)$",
                ),
            ],
            ONGOING_UPLOAD_MULTI_RANGE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_ongoing_multi_range,
                ),
            ],
            ONGOING_UPLOAD_MULTI_ASK: [
                CallbackQueryHandler(
                    ongoing_multi_ask_more_callback,
                    pattern=r"^(ogup_add_more|ogup_finish|ogup_cancel)$",
                ),
            ],
            ONGOING_UPLOAD_CONFIRM: [
                CallbackQueryHandler(
                    confirm_ongoing_upload,
                    pattern=r"^(ogup_confirm|ogup_cancel_confirm)$",
                ),
            ],
        },
        fallbacks=[
            MessageHandler(filters.Regex("^لغو$"), cancel_ongoing),
            MessageHandler(filters.Regex(
                "^بازگشت به منوی اصلی$"), cancel_ongoing),
            MessageHandler(filters.COMMAND, cancel_ongoing),
        ],
        allow_reentry=True,
    )


def _build_management_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(
                "^مدیریت فایل‌ها$"), start_management),
        ],
        states={
            # سطح ۱ اسامی + سطح ۵ جزئیات + ویرایش/جستجو (R5)
            MANAGE_LIST: [
                CallbackQueryHandler(handle_management_callback),
            ],
            MANAGE_DETAIL: [
                CallbackQueryHandler(handle_management_callback),
            ],
            # سطوح ۲-۴ سلسله‌مراتب (مرحله ۴ — R5)
            MANAGE_GROUPS: [
                CallbackQueryHandler(handle_management_callback),
            ],
            MANAGE_EPISODES: [
                CallbackQueryHandler(handle_management_callback),
            ],
            MANAGE_QUALITIES: [
                CallbackQueryHandler(handle_management_callback),
            ],
            MANAGE_EDIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND,
                               handle_edit_input),
                # رفع باگ ۵د-۲: دکمه‌ها در حالت انتظار تایپ هم بی‌پاسخ نمانند
                CallbackQueryHandler(handle_management_callback),
            ],
            MANAGE_SEARCH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND,
                               handle_search_input),
                # رفع باگ ۵د-۲: دکمه‌ها در حالت انتظار جستجو هم بی‌پاسخ نمانند
                CallbackQueryHandler(handle_management_callback),
            ],
            # R9: زنجیره «افزودن قسمت جدید» — بازاستفاده از هندلرهای آپلود
            EPISODE_RANGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND,
                               receive_episode_range),
            ],
            MULTI_QUALITY: [
                CallbackQueryHandler(
                    multiselect_callback,
                    pattern=r"^(mqs:\d+|mqs_go|mqs_cancel)$",
                ),
            ],
            MULTI_QUALITY_CHANNEL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND,
                               multi_quality_channel_range),
            ],
            CONFIRM: [
                CallbackQueryHandler(
                    confirm_upload,
                    pattern=(
                        r"^(confirm_save|next_ep|up_done"
                        r"|cancel_confirm)$"
                    ),
                ),
            ],
            # R10: انتظار متن / عکس خلاصه داستان فصل
            MANAGE_SUMMARY_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND,
                               handle_summary_text),
                CallbackQueryHandler(handle_management_callback),
            ],
            MANAGE_SUMMARY_PHOTO: [
                MessageHandler(filters.PHOTO, handle_summary_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND,
                               handle_summary_text),
                CallbackQueryHandler(handle_management_callback),
            ],
        },
        fallbacks=[
            MessageHandler(filters.Regex("^لغو$"), cancel_management),
            MessageHandler(filters.COMMAND, cancel_management),
            # لغو مخصوص فلوی آپلود (حالت R9)
            MessageHandler(filters.Regex("^لغو آپلود$"), cancel_upload),
            CallbackQueryHandler(
                cancel_from_inline,
                pattern=r"^(dbsel_cancel|cancel_multi)$",
            ),
        ],
        allow_reentry=True,
    )


def _build_stats_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^آمار$"), show_stats),
        ],
        states={
            MANAGE_STATS: [
                CallbackQueryHandler(handle_stats_callback),
            ],
        },
        fallbacks=[
            MessageHandler(filters.COMMAND, lambda u,
                           c: ConversationHandler.END),
        ],
        allow_reentry=True,
    )


def _build_broadcast_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^📢 پیام همگانی$"), start_broadcast),
        ],
        states={
            BROADCAST_INPUT: [
                MessageHandler(
                    filters.ALL & ~filters.COMMAND,
                    receive_broadcast_message,
                ),
            ],
            BROADCAST_CONFIRM: [
                CallbackQueryHandler(
                    confirm_broadcast,
                    pattern=r"^(bc_confirm|bc_cancel)$",
                ),
            ],
        },
        fallbacks=[
            MessageHandler(filters.Regex("^لغو$"), cancel_broadcast),
            MessageHandler(filters.COMMAND, cancel_broadcast),
        ],
        allow_reentry=True,
    )


def _build_post_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^📝 پست‌ها$"), start_posts),
        ],
        states={
            POST_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND,
                               post_menu_handler),
            ],
            POST_UPLOAD_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND,
                               receive_post_name),
            ],
            POST_UPLOAD_MESSAGES: [
                MessageHandler(filters.ALL & ~filters.COMMAND,
                               receive_post_messages),
            ],
            POST_MANAGE_LIST: [
                CallbackQueryHandler(handle_post_manage_callback),
            ],
            POST_MANAGE_DETAIL: [
                CallbackQueryHandler(handle_post_manage_callback),
            ],
        },
        fallbacks=[
            MessageHandler(filters.Regex("^لغو$"), cancel_posts),
            MessageHandler(filters.Regex(
                "^بازگشت به منوی اصلی$"), cancel_posts),
            MessageHandler(filters.COMMAND, cancel_posts),
        ],
        allow_reentry=True,
    )


def _build_settings_conversation() -> ConversationHandler:
    """R2 — پنل تنظیمات (فقط مالک): callbackهای st:* در همه stateها."""

    def _st_callback() -> CallbackQueryHandler:
        return CallbackQueryHandler(
            settings_callback,
            pattern=r"^st:",
        )

    return ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.Regex(f"^{re.escape(SETTINGS_BUTTON)}$"),
                open_settings,
            ),
        ],
        states={
            SETTINGS_PANEL: [
                _st_callback(),
            ],
            SETTINGS_ADMIN: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_admin_input,
                ),
                _st_callback(),
            ],
            SETTINGS_CHANNEL: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_channel_input,
                ),
                _st_callback(),
            ],
            SETTINGS_DURATION: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_duration_input,
                ),
                _st_callback(),
            ],
            SETTINGS_DB_NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_db_name_input,
                ),
                _st_callback(),
            ],
            SETTINGS_DB_CHAT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_db_chat_input,
                ),
                _st_callback(),
            ],
        },
        fallbacks=[
            MessageHandler(
                filters.Regex("^(لغو|بازگشت به منوی اصلی)$"),
                cancel_settings,
            ),
            MessageHandler(filters.COMMAND, cancel_settings),
        ],
        allow_reentry=True,
    )


def build_application() -> Application:
    application = Application.builder().token(config.BOT_TOKEN).build()

    quality_pattern = quality_pattern_string()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(
        CallbackQueryHandler(recheck_callback, pattern=r"^recheck:")
    )
    application.add_handler(
        CallbackQueryHandler(handle_report_callback, pattern=r"^report:")
    )

    application.add_handler(_build_upload_conversation())
    application.add_handler(_build_ongoing_conversation(quality_pattern))
    application.add_handler(_build_management_conversation())
    application.add_handler(_build_stats_conversation())
    application.add_handler(_build_broadcast_conversation())
    application.add_handler(_build_post_conversation())
    application.add_handler(_build_settings_conversation())

    application.add_handler(
        MessageHandler(filters.Regex("^💾 بک‌آپ$"), handle_backup)
    )

    return application
