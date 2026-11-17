import logging

from bot.application import build_application
from bot.config import config
from bot.constants import BOT_VERSION, BOT_VERSION_DATE
from bot.database import db


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# P15: لاگ‌های httpx/httpcore در سطح INFO کل URL (شامل توکن ربات) را
# چاپ می‌کنند — برای جلوگیری از افشای توکن در لاگ، WARNING می‌شوند.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def preflight() -> bool:
    """R24: چک‌های پیش‌از‌راه‌اندازی — جدا شده تا قابل تست باشد.

    False یعنی ربات نباید بالا بیاید (خطا لاگ شده است).
    """
    try:
        config.validate()
    except ValueError as err:
        logger.error("⚠️ خطای پیکربندی: %s", err)
        return False

    db.init()

    # R26: لینک پایدار برای فصل/پارت‌های موجود (یک‌بار، idempotent)
    try:
        created = db.backfill_group_links()
        logger.info(
            "لینک فصل/پارت: %s کد تازه ساخته شد (مجموع %s).",
            created,
            db.count_group_links(),
        )
    except Exception as err:      # noqa: BLE001 — استارت نباید بشکند
        logger.warning("ساخت لینک فصل‌ها ناموفق بود: %s", err)

    return _post_init_checks()


def _post_init_checks() -> bool:
    """چک‌های وابسته به دیتابیس (بعد از انتقال env به settings در init)."""
    # R24: مالک خودش مجوز کامل دارد و می‌تواند از پنل تنظیمات ادمین اضافه
    # کند ⇒ نبودِ ADMIN_IDS دیگر مانع راه‌اندازی نیست (قبلاً ربات با
    # envای که فقط OWNER_ID داشت اصلاً بالا نمی‌آمد).
    if not config.ADMIN_IDS:
        if config.OWNER_ID is None:
            logger.error(
                "⚠️ هیچ ادمینی تنظیم نشده است: هم در .env (ADMIN_IDS) "
                "و هم در settings دیتابیس خالی است.",
            )
            return False
        logger.info(
            "ℹ️ ADMIN_IDS خالی است — فعلاً فقط مالک (%s) دسترسی مدیریت "
            "دارد. ادمین‌های بعدی را از «⚙️ تنظیمات» اضافه کنید.",
            config.OWNER_ID,
        )

    # R24: نبودِ مدت حذف دیگر مانع راه‌اندازی نیست — فقط حذف خودکار
    # پیام‌ها خاموش می‌ماند تا از «⚙️ تنظیمات» تعیین شود.
    if not config.DELETE_AFTER_SECONDS:
        logger.warning(
            "⚠️ مدت حذف پیام (DELETE_AFTER_SECONDS) تنظیم نشده است — "
            "حذف خودکار پیام‌ها خاموش است. از «⚙️ تنظیمات» تعیین کنید.",
        )

    logger.info(
        "دیتابیس‌های ذخیره‌سازی: %s",
        ", ".join(
            f"{database['name']}({database['chat_id']})"
            for database in config.DATABASES
        ),
    )
    return True


def main() -> None:
    if not preflight():
        return
    logger.info("مالک ربات: %s", config.OWNER_ID)
    logger.info("ادمین‌ها: %s", ", ".join(map(str, config.ADMIN_IDS)))

    if config.REQUIRED_CHANNELS:
        logger.info(
            "کانال‌های اجباری عضویت: %s",
            ", ".join(str(channel) for channel in config.REQUIRED_CHANNELS),
        )

    application = build_application()
    logger.info(
        "ربات نسخهٔ %s (%s) در حال اجراست...",
        BOT_VERSION,
        BOT_VERSION_DATE,
    )
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
