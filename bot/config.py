import logging
import os
from typing import Any, Dict, List, Optional, Union

from dotenv import load_dotenv


# ریشه پروژه (پوشه‌ای که main.py در آن است) — مستقل از CWD اجرا
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

logger = logging.getLogger(__name__)


class Config:
    DB_PATH: str = os.path.join(_PROJECT_ROOT, "uploads.db")
    PAGE_SIZE: int = 5
    USERS_PAGE_SIZE: int = 10
    REPORTS_PAGE_SIZE: int = 5

    def __init__(self) -> None:
        self.BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

        self.OWNER_ID: Optional[int] = self._parse_optional_id(
            os.getenv("OWNER_ID")
        )

        raw_admins = os.getenv("ADMIN_IDS", "")
        self.ADMIN_IDS: List[int] = self._parse_admin_ids(raw_admins)
        # R24 (P12): توکن‌های نامعتبر env دور ریخته نمی‌شوند بی‌صدا —
        # در validate() هشدار داده می‌شوند.
        self.INVALID_ADMIN_IDS: List[str] = self._invalid_admin_tokens(
            raw_admins
        )

        self.DATABASES: List[Dict[str, Any]] = self._parse_databases(
            os.getenv("DATABASES", "")
        )

        # None ⇒ در db.init() از دیتابیس پر می‌شود؛ اگر هیچ‌جا نبود
        # main() خطای زیبا گزارش می‌کند (به‌جای traceback در import — P6)
        self.DELETE_AFTER_SECONDS: Optional[int] = self._parse_optional_int(
            os.getenv("DELETE_AFTER_SECONDS")
        )

        self.REQUIRED_CHANNELS: List[Union[int, str]] = (
            self._parse_required_channels(
                os.getenv("REQUIRED_CHANNELS", "")
            )
        )

    @staticmethod
    def _invalid_admin_tokens(raw: str) -> List[str]:
        """R24: بخش‌های ADMIN_IDS که عدد نیستند (تایپو/فاصله/حرف)."""
        return [
            part.strip()
            for part in (raw or "").split(",")
            if part.strip() and not part.strip().isdigit()
        ]

    @staticmethod
    def _parse_admin_ids(raw: str) -> List[int]:
        return [
            int(part.strip())
            for part in raw.split(",")
            if part.strip().isdigit()
        ]

    @staticmethod
    def _parse_optional_id(raw: Optional[str]) -> Optional[int]:
        value = (raw or "").strip()

        if value.isdigit():
            return int(value)

        return None

    @staticmethod
    def _parse_optional_int(raw: Optional[str]) -> Optional[int]:
        if raw is None or not raw.strip():
            return None

        try:
            return int(raw.strip())
        except ValueError:
            return None

    @staticmethod
    def _parse_databases(raw: str) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []

        for part in (raw or "").split(","):
            part = part.strip()
            if not part:
                continue

            if ":" in part:
                name, chat_id = part.split(":", 1)
                name = name.strip()
                chat_id = chat_id.strip()
            else:
                name = "دیتابیس"
                chat_id = part.strip()

            if chat_id.lstrip("-").isdigit():
                result.append(
                    {
                        "name": name or "دیتابیس",
                        "chat_id": int(chat_id),
                    }
                )

        return result

    @staticmethod
    def _normalize_channel(
        raw: str,
    ) -> Optional[Union[int, str]]:
        value = (raw or "").strip()

        if not value:
            return None

        if value.lstrip("-").isdigit():
            return int(value)

        if value.endswith("@") and not value.startswith("@"):
            value = "@" + value[:-1].strip()

        if not value.startswith("@"):
            value = "@" + value

        return value if len(value) > 1 else None

    @classmethod
    def _parse_required_channels(
        cls,
        raw: str,
    ) -> List[Union[int, str]]:
        result: List[Union[int, str]] = []

        for part in (raw or "").split(","):
            channel = cls._normalize_channel(part)

            if channel is not None:
                result.append(channel)

        return result

    def validate(self) -> None:
        # R24 (P12): آیدی‌های نامعتبر ADMIN_IDS بی‌صدا نادیده گرفته نشوند
        if self.INVALID_ADMIN_IDS:
            logger.warning(
                "⚠️ ADMIN_IDS شامل مقدار نامعتبر بود و این مقادیر حذف "
                "شدند: %s — فقط آیدی عددی تلگرام معتبر است (بقیهٔ آیدی‌ها "
                "سالم هستند).",
                ", ".join(self.INVALID_ADMIN_IDS),
            )

        if (
            not self.BOT_TOKEN
            or self.BOT_TOKEN == "YOUR_BOT_TOKEN_HERE"
        ):
            raise ValueError(
                "لطفاً BOT_TOKEN را در فایل .env تنظیم کنید."
            )

        if self.OWNER_ID is None:
            raise ValueError(
                "لطفاً OWNER_ID (آیدی عددی تلگرام مالک) را "
                "در فایل .env تنظیم کنید."
            )

        if not self.DATABASES:
            raise ValueError(
                "حداقل یک دیتابیس در متغیر DATABASES لازم است."
            )


config = Config()
