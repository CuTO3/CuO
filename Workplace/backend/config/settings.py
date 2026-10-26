"""Configuration is loaded once; production secrets stay outside the source tree."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class GroupSettings:
    schema: str
    enabled: bool = True


@dataclass
class Settings:
    database_url: str = field(default="", repr=False)
    groups: dict[str, GroupSettings] = field(default_factory=dict)
    backend_root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[1])
    data_root: Path = Path("/serve/data/cuo")
    config_root: Path = Path("/serve/config/cuo")
    model_base_url: str = "https://api.deepseek.com/v1"
    model_api_key: str = field(default="", repr=False)
    model_name: str = "deepseek-chat"
    model_protocol: str = "openai"
    model_timeout: float = 60.0
    context_limit: int = 32768
    vision_model_base_url: str = ""
    vision_model_api_key: str = field(default="", repr=False)
    vision_model_name: str = ""
    napcat_token: str = field(default="", repr=False)
    self_id: str = ""
    admin_token: str = field(default="", repr=False)
    onebot_timeout: float = 20.0
    inbound_queue_size: int = 1000
    napcat_upload_root: Path | None = None
    first_business_date: str | None = None
    model_concurrency: int = 1
    max_message_length: int = 1500
    timezone: str = "Asia/Shanghai"
    database_pool_min: int = 1
    database_pool_max: int = 8

    @classmethod
    def load(cls, env_file: str | Path | None = None) -> "Settings":
        if env_file:
            load_dotenv(env_file, override=False)
        elif os.environ.get("CUO_ENV_FILE"):
            load_dotenv(os.environ["CUO_ENV_FILE"], override=False)
        settings = cls(
            database_url=os.getenv("DATABASE_URL", ""),
            data_root=Path(os.getenv("CUO_DATA_ROOT", "/serve/data/cuo")),
            config_root=Path(os.getenv("CUO_CONFIG_ROOT", "/serve/config/cuo")),
            model_base_url=os.getenv("MODEL_BASE_URL", "https://api.deepseek.com/v1").rstrip("/"),
            model_api_key=os.getenv("MODEL_API_KEY", ""),
            model_name=os.getenv("MODEL_NAME", "deepseek-chat"),
            model_protocol=os.getenv("MODEL_PROTOCOL", "openai"),
            model_timeout=float(os.getenv("MODEL_TIMEOUT", "60")),
            napcat_token=os.getenv("ONEBOT_TOKEN", ""),
            self_id=os.getenv("ONEBOT_SELF_ID", ""),
            admin_token=os.getenv("ADMIN_TOKEN", ""),
            first_business_date=os.getenv("CUO_FIRST_BUSINESS_DATE") or None,
        )
        if os.getenv("CUO_BACKEND_ROOT"):
            settings.backend_root = Path(os.environ["CUO_BACKEND_ROOT"]).resolve()
        if os.getenv("NAPCAT_UPLOAD_ROOT"):
            settings.napcat_upload_root = Path(os.environ["NAPCAT_UPLOAD_ROOT"])
        groups_path = settings.config_root / "groups.json"
        if os.getenv("CUO_GROUPS_FILE"):
            groups_path = Path(os.environ["CUO_GROUPS_FILE"])
        if groups_path.is_file():
            raw = json.loads(groups_path.read_text(encoding="utf-8"))
            raw = raw.get("groups", raw)
            if not isinstance(raw, dict):
                raise ValueError("groups must be an object keyed by trusted group ID")
            settings.groups = {str(key): GroupSettings(schema=str(value.get("schema", key)), enabled=value.get("enabled", True)) for key, value in raw.items() if value.get("enabled", True)}
        elif os.getenv("CUO_GROUP_IDS"):
            settings.groups = {gid: GroupSettings(gid) for gid in os.environ["CUO_GROUP_IDS"].split(",") if gid}
        for gid, group in settings.groups.items():
            if not gid.isdecimal() or not group.schema.isdecimal():
                raise ValueError("group and schema IDs must be registered decimal strings")
        if not settings.database_url:
            raise ValueError("DATABASE_URL is required")
        return settings
