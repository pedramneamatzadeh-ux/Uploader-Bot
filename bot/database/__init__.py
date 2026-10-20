"""پکیج دیتابیس — کلاس Database از mixinها (API بدون تغییر)."""

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

from .core import CoreMixin
from .settings import SettingsMixin
from .users import UsersMixin
from .uploads import UploadsMixin
from .display import DisplayMixin
from .groups import GroupsMixin
from .ongoingdb import OngoingMixin
from .postsdb import PostsMixin
from .custom_db import CustomDbMixin
from .summaries import SummariesMixin


class Database(
    CoreMixin,
    SettingsMixin,
    UsersMixin,
    UploadsMixin,
    DisplayMixin,
    GroupsMixin,
    OngoingMixin,
    PostsMixin,
    CustomDbMixin,
    SummariesMixin,
):
    pass


db = Database(config.DB_PATH)
