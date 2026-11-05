import io
import logging
import os
import shutil
import tempfile

from telegram import Update
from telegram.ext import ContextTypes

from ..config import config
from ..database import Database
from ..decorators import owner_only
from ..keyboards import main_menu_for


logger = logging.getLogger(__name__)


@owner_only
async def handle_backup(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    chat_id = update.message.chat_id
    await update.message.reply_text("💾 در حال تهیه بک‌آپ...")

    db_path = os.path.abspath(config.DB_PATH)
    if not os.path.exists(db_path):
        await update.message.reply_text(
            "❌ فایل دیتابیس پیدا نشد!",
            reply_markup=main_menu_for(update.effective_user.id),
        )
        return

    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp()
        # نام فایل مقصد فقط basename است (مسیر مطلق ⇒ ساخت پوشه میانی شکست می‌خورد)
        backup_path = os.path.join(
            tmp_dir,
            f"backup_{os.path.basename(db_path)}",
        )
        # R14: با WAL، اول نوشتن‌های در جریان را از فایل جانبی به
        # فایل اصلی منتقل کن تا کپیِ خام کامل باشد.
        Database(db_path).wal_checkpoint()
        shutil.copy2(db_path, backup_path)

        with open(backup_path, "rb") as backup_file:
            await context.bot.send_document(
                chat_id=chat_id,
                document=backup_file,
                filename=f"backup_{os.path.basename(db_path)}",
                caption="💾 بک‌آپ دیتابیس با موفقیت تهیه شد.",
            )
    except Exception as err:
        logger.exception("خطا در تهیه بک‌آپ: %s", err)
        await update.message.reply_text(
            f"❌ خطا در تهیه بک‌آپ: {err}",
            reply_markup=main_menu_for(update.effective_user.id),
        )
    finally:
        if tmp_dir:
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

    # P4: ارسال .env بدون خطوط BOT_TOKEN (توکن از حساس‌ترین خطوط است)
    env_path = os.path.join(os.path.dirname(db_path), ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "rb") as env_file:
                raw = env_file.read()

            lines = raw.splitlines(keepends=True)
            filtered = b"".join(
                line
                for line in lines
                if not line.strip().upper().startswith(b"BOT_TOKEN")
            )

            await context.bot.send_document(
                chat_id=chat_id,
                document=io.BytesIO(filtered),
                filename="backup_.env",
                caption=(
                    "📄 بک‌آپ فایل تنظیمات (.env) — بدون خط BOT_TOKEN"
                ),
            )
        except Exception as err:
            logger.warning("ارسال .env ناموفق: %s", err)

    await update.message.reply_text(
        "✅ بک‌آپ کامل شد.",
        reply_markup=main_menu_for(update.effective_user.id),
    )
