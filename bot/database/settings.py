"""تنظیمات کلید-مقدار (جدول settings) + import از env."""

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

class SettingsMixin:

    # ------------------------------------------------------------------
    # Settings (کلید-مقدار JSON — زیرساخت R2/R3)
    # ------------------------------------------------------------------
    def get_setting(self, key: str, default: Any = None) -> Any:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = ?",
                (key,),
            ).fetchone()

        if row is None:
            return default

        try:
            return json.loads(row["value"])
        except (TypeError, ValueError):
            logger.warning("مقدار نامعتبر در settings: %s", key)
            return default

    def set_setting(self, key: str, value: Any) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (key, json.dumps(value, ensure_ascii=False)),
            )

        self._apply_settings_to_config({key: value})

    def _import_env_settings(self, connection: sqlite3.Connection) -> None:
        env_values: Dict[str, Any] = {
            "admin_ids": config.ADMIN_IDS or None,
            "required_channels": config.REQUIRED_CHANNELS or None,
            "delete_after_seconds": config.DELETE_AFTER_SECONDS,
            "delete_after_seconds_posts": config.DELETE_AFTER_SECONDS_POSTS,
            "delete_after_seconds_panel": config.DELETE_AFTER_SECONDS_PANEL,
            "delete_after_seconds_summary": config.DELETE_AFTER_SECONDS_SUMMARY,
            "summary_photo_chat": config.SUMMARY_PHOTO_CHAT,
            "summary_photo_chats": config.SUMMARY_PHOTO_CHATS or None,
        }

        for key, value in env_values.items():
            if value is None or value == []:
                continue

            exists = connection.execute(
                "SELECT 1 FROM settings WHERE key = ?",
                (key,),
            ).fetchone()

            if exists:
                continue

            connection.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                (key, json.dumps(value, ensure_ascii=False)),
            )
            logger.info(
                "تنظیم «%s» از env به دیتابیس منتقل شد.",
                key,
            )

    def _load_settings(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT key, value FROM settings"
        ).fetchall()

        if not rows:
            return

        data: Dict[str, Any] = {}

        for row in rows:
            try:
                data[row["key"]] = json.loads(row["value"])
            except (TypeError, ValueError):
                logger.warning(
                    "مقدار JSON نامعتبر در settings: %s",
                    row["key"],
                )

        self._apply_settings_to_config(data)

    def _apply_settings_to_config(self, data: Dict[str, Any]) -> None:
        admin_ids = data.get("admin_ids")

        if isinstance(admin_ids, list):
            # R24 (P12): فیلتر عضو‌به‌عضو — یک مقدار خراب نباید کل لیست
            # ادمین‌ها را دور بریزد (قبلاً همه‌یا‌هیچی بود).
            valid_ids: List[int] = []
            invalid_ids: List[Any] = []
            for item in admin_ids:
                try:
                    value = int(str(item).strip())
                except (TypeError, ValueError):
                    invalid_ids.append(item)
                    continue
                if value > 0:
                    valid_ids.append(value)
                else:
                    invalid_ids.append(item)

            if invalid_ids:
                logger.warning(
                    "admin_ids: %s مقدار نامعتبر حذف شد (فقط آیدی عددی "
                    "مثبت معتبر است).",
                    invalid_ids,
                )
            config.ADMIN_IDS = valid_ids

        channels = data.get("required_channels")

        if isinstance(channels, list):
            config.REQUIRED_CHANNELS = channels

        # R34: لیست کانال‌های عکس خلاصه (تک‌مقدار قدیمی هم پذیرفته می‌شود)
        if "summary_photo_chats" in data:
            raw = data.get("summary_photo_chats") or []
            if isinstance(raw, (str, int)):
                raw = [raw]
            chats: List[int] = []
            for item in raw:
                try:
                    value = int(str(item).strip())
                except (TypeError, ValueError):
                    logger.warning(
                        "summary_photo_chats: مقدار نامعتبر %r حذف شد", item
                    )
                    continue
                if value not in chats:
                    chats.append(value)
            config.SUMMARY_PHOTO_CHATS = chats

        photo_chat = data.get("summary_photo_chat")
        if "summary_photo_chat" in data:
            try:
                config.SUMMARY_PHOTO_CHAT = (
                    int(photo_chat) if photo_chat not in (None, "") else None
                )
            except (TypeError, ValueError):
                logger.warning("summary_photo_chat نامعتبر — نادیده گرفته شد.")
            # سازگاری با کلید تک‌مقدار قدیمی:
            #   • مقدار ست ⇒ اگر لیست خالی است، همان یک عضو
            #   • مقدار None ⇒ کل فهرست پاک می‌شود (رفتار «حذف تنظیم»)
            if config.SUMMARY_PHOTO_CHAT:
                if not config.SUMMARY_PHOTO_CHATS:
                    config.SUMMARY_PHOTO_CHATS = [config.SUMMARY_PHOTO_CHAT]
            elif "summary_photo_chats" not in data:
                config.SUMMARY_PHOTO_CHATS = []

        delete_keys = {
            "delete_after_seconds": "DELETE_AFTER_SECONDS",
            "delete_after_seconds_posts": "DELETE_AFTER_SECONDS_POSTS",
            "delete_after_seconds_panel": "DELETE_AFTER_SECONDS_PANEL",
            "delete_after_seconds_summary": "DELETE_AFTER_SECONDS_SUMMARY",
        }

        for key, attribute in delete_keys.items():
            if key not in data:
                continue
            value = data.get(key)
            if value is None:
                setattr(config, attribute, None)
                continue
            try:
                setattr(config, attribute, int(value))
            except (TypeError, ValueError):
                logger.warning("%s نامعتبر — نادیده گرفته شد.", key)
