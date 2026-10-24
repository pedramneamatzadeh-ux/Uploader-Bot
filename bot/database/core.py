"""هسته: اتصال، اسکیما و migrationها."""

import json
import logging
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

from ..config import config
from ..constants import (
    ALLOWED_ONGOING_UPDATE_FIELDS,
    ALLOWED_UPLOAD_UPDATE_FIELDS,
)

logger = logging.getLogger(__name__)

class CoreMixin:

    def __init__(self, path: str):
        self.path = path

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")

        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def init(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS uploads (
                    session_id TEXT PRIMARY KEY,
                    anime_name TEXT NOT NULL,
                    season_num TEXT,
                    part_num TEXT,
                    episode_range TEXT NOT NULL,
                    quality TEXT NOT NULL,
                    channel_msg_range TEXT NOT NULL,
                    admin_id INTEGER NOT NULL,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id)
                        REFERENCES uploads(session_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    report_text TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id)
                        REFERENCES uploads(session_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS ongoing_animes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    anime_name TEXT NOT NULL,
                    season_num TEXT,
                    part_num TEXT,
                    status TEXT DEFAULT 'active',
                    admin_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS posts (
                    post_id TEXT PRIMARY KEY,
                    post_name TEXT NOT NULL,
                    admin_id INTEGER NOT NULL,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS post_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    message_order INTEGER NOT NULL,
                    FOREIGN KEY (post_id)
                        REFERENCES posts(post_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS custom_databases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    created_by INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS anime_display_names (
                    anime_name TEXT NOT NULL,
                    season_num TEXT NOT NULL DEFAULT '',
                    part_num TEXT NOT NULL DEFAULT '',
                    display_name TEXT NOT NULL,
                    PRIMARY KEY (anime_name, season_num, part_num)
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS season_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    anime_name TEXT NOT NULL,
                    season_num TEXT NOT NULL DEFAULT '',
                    summary_text TEXT NOT NULL DEFAULT '',
                    photo_file_id TEXT,
                    created_by INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(anime_name, season_num)
                );

                CREATE INDEX IF NOT EXISTS idx_downloads_session
                    ON downloads(session_id);

                CREATE INDEX IF NOT EXISTS idx_reports_session
                    ON reports(session_id);

                CREATE INDEX IF NOT EXISTS idx_reports_status
                    ON reports(status);

                CREATE INDEX IF NOT EXISTS idx_ongoing_status
                    ON ongoing_animes(status);

                CREATE INDEX IF NOT EXISTS idx_post_messages_post
                    ON post_messages(post_id);
                """
            )

            migrations = (
                "ALTER TABLE uploads ADD COLUMN season_num TEXT",
                "ALTER TABLE uploads ADD COLUMN part_num TEXT",
                (
                    "ALTER TABLE uploads "
                    "ADD COLUMN is_ongoing INTEGER DEFAULT 0"
                ),
                (
                    "ALTER TABLE uploads "
                    "ADD COLUMN ongoing_anime_id INTEGER"
                ),
                (
                    "ALTER TABLE uploads "
                    "ADD COLUMN anime_type TEXT DEFAULT ''"
                ),
                (
                    "ALTER TABLE uploads "
                    "ADD COLUMN channel_chat_id TEXT"
                ),
                (
                    "ALTER TABLE uploads "
                    "ADD COLUMN airing_status TEXT"
                ),
                (
                    "ALTER TABLE uploads "
                    "ADD COLUMN is_finished INTEGER DEFAULT 0"
                ),
            )

            for migration in migrations:
                try:
                    connection.execute(migration)
                except sqlite3.OperationalError:
                    pass

            # --- R12-1: مهاجرت جدول نام ظاهری به سطح (نام، فصل، پارت) ---
            # ردیف‌های قدیمی (به‌ازای کل نام واقعی) با season='' و part=''
            # نگه داشته می‌شوند = «برچسب پیش‌فرض کل نام» ⇒ گروه‌بندی
            # فعلی بلافاصله بعد از مهاجرت دقیقاً مثل قبل می‌ماند.
            cols = [
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(anime_display_names)"
                ).fetchall()
            ]
            if cols and "season_num" not in cols:
                connection.execute(
                    "ALTER TABLE anime_display_names "
                    "RENAME TO anime_display_names_old"
                )
                connection.execute(
                    """
                    CREATE TABLE anime_display_names (
                        anime_name TEXT NOT NULL,
                        season_num TEXT NOT NULL DEFAULT '',
                        part_num TEXT NOT NULL DEFAULT '',
                        display_name TEXT NOT NULL,
                        PRIMARY KEY (anime_name, season_num, part_num)
                    )
                    """
                )
                connection.execute(
                    "INSERT INTO anime_display_names "
                    "    (anime_name, season_num, part_num, display_name) "
                    "SELECT anime_name, '', '', display_name "
                    "FROM anime_display_names_old"
                )
                connection.execute(
                    "DROP TABLE anime_display_names_old"
                )

            # --- مهاجرت داده: نام کیفیت x256 → x265 (idempotent) ---
            connection.execute(
                "UPDATE uploads SET quality = '720p x265' "
                "WHERE quality = '720p x256'"
            )
            connection.execute(
                "UPDATE uploads SET quality = '1080p x265' "
                "WHERE quality = '1080p x256'"
            )

            # --- مهاجرت داده: پر کردن airing_status از روی کانال ---
            # قانون: نام دیتابیس حاوی «درحال» ⇒ درحال پخش؛
            # بقیه (اتمام پخش/سینمایی) ⇒ اتمام پخش
            for db_entry in config.DATABASES:
                status = (
                    "درحال پخش"
                    if "درحال" in db_entry["name"]
                    else "اتمام پخش"
                )
                connection.execute(
                    """
                    UPDATE uploads
                    SET airing_status = ?
                    WHERE COALESCE(channel_chat_id, '') = ?
                      AND COALESCE(airing_status, '') = ''
                    """,
                    (status, str(db_entry["chat_id"])),
                )

            # ردیف‌های بدون کانال مشخص ⇒ پیش‌فرض اولین دیتابیس env
            if config.DATABASES:
                default_entry = config.DATABASES[0]
                default_status = (
                    "درحال پخش"
                    if "درحال" in default_entry["name"]
                    else "اتمام پخش"
                )
                connection.execute(
                    """
                    UPDATE uploads
                    SET airing_status = ?
                    WHERE COALESCE(channel_chat_id, '') = ''
                      AND COALESCE(airing_status, '') = ''
                    """,
                    (default_status,),
                )

            # باقی‌مانده (کانال ناشناخته) ⇒ اتمام پخش
            connection.execute(
                "UPDATE uploads SET airing_status = 'اتمام پخش' "
                "WHERE COALESCE(airing_status, '') = ''"
            )

            # --- فاز ۱ / R3: انتقال یک‌باره env به settings (فقط کلیدهای غایب) ---
            self._import_env_settings(connection)

            # --- بارگذاری settings (دیتابیس) روی config؛ دیتابیس برنده است ---
            self._load_settings(connection)

        logger.info("دیتابیس بررسی و آماده شد.")
