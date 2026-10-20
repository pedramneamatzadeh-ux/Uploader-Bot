import logging

from bot.application import build_application
from bot.config import config
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


def main() -> None:
    try:
        config.validate()
    except ValueError as err:
        logger.error("⚠️ خطای پیکربندی: %s", err)
        return

    db.init()

    # چک‌های وابسته به دیتابیس (بعد از انتقال env به settings در init)
    if not config.ADMIN_IDS:
        logger.error(
            "⚠️ هیچ ادمینی تنظیم نشده است: هم در .env (ADMIN_IDS) "
            "و هم در settings دیتابیس خالی است.",
        )
        return

    if config.DELETE_AFTER_SECONDS is None:
        logger.error(
            "⚠️ مدت حذف پیام (DELETE_AFTER_SECONDS) نه در .env "
            "و نه در settings دیتابیس تنظیم نشده است.",
        )
        return

    logger.info(
        "دیتابیس‌های ذخیره‌سازی: %s",
        ", ".join(
            f"{database['name']}({database['chat_id']})"
            for database in config.DATABASES
        ),
    )
    logger.info("مالک ربات: %s", config.OWNER_ID)
    logger.info("ادمین‌ها: %s", ", ".join(map(str, config.ADMIN_IDS)))

    if config.REQUIRED_CHANNELS:
        logger.info(
            "کانال‌های اجباری عضویت: %s",
            ", ".join(str(channel) for channel in config.REQUIRED_CHANNELS),
        )

    application = build_application()
    logger.info("ربات در حال اجراست...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
