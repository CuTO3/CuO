from dataclasses import dataclass, field
from pathlib import Path
import json
import os

@dataclass(frozen=True)
class GroupSettings:
    schema: str
    enabled: bool = True

@dataclass
class Settings:
    database_url: str = field(default="", repr=False)
    groups: dict = field(default_factory=dict)
    backend_root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[1])
    data_root: Path = Path("/serve/data/cuo")
    model_base_url: str = "https://api.deepseek.com/v1"
    model_api_key: str = field(default="", repr=False)
    model_name: str = "deepseek-chat"
    model_protocol: str = "openai"
    model_timeout: float = 60
    vision_base_url: str = ""
    vision_api_key: str = field(default="", repr=False)
    vision_model_name: str = ""
    self_id: str = ""
    napcat_token: str = field(default="", repr=False)
    admin_token: str = field(default="", repr=False)
    onebot_timeout: float = 20
    max_message_length: int = 1500
    inbound_queue_size: int = 1000
    napcat_upload_root: Path | None = None
    first_business_date: str | None = None
    database_pool_min: int = 1
    database_pool_max: int = 8

    @classmethod
    def load(cls):
        from dotenv import load_dotenv
        if os.getenv("CUO_ENV_FILE"):
            load_dotenv(os.environ["CUO_ENV_FILE"], override=False)
        path = Path(os.getenv("CUO_GROUPS_FILE", "/serve/config/cuo/groups.json"))
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw = raw.get("groups", raw)
        groups = {str(g): GroupSettings(str(c.get("schema", g))) for g,c in raw.items() if c.get("enabled", True)}
        if not groups or any(not g.isascii() or not g.isdecimal() or not c.schema.isascii() or not c.schema.isdecimal() for g,c in groups.items()):
            raise ValueError("registered decimal groups are required")
        if len({c.schema for c in groups.values()}) != len(groups):
            raise ValueError("group schemas must be unique")
        result = cls(database_url=os.getenv("DATABASE_URL",""), groups=groups,
            data_root=Path(os.getenv("CUO_DATA_ROOT","/serve/data/cuo")),
            model_base_url=os.getenv("MODEL_BASE_URL","https://api.deepseek.com/v1"),
            model_api_key=os.getenv("MODEL_API_KEY",""), model_name=os.getenv("MODEL_NAME","deepseek-chat"),
            model_protocol=os.getenv("MODEL_PROTOCOL","openai"), model_timeout=float(os.getenv("MODEL_TIMEOUT","60")),
            vision_base_url=os.getenv("VISION_BASE_URL",""), vision_api_key=os.getenv("VISION_API_KEY",""),
            vision_model_name=os.getenv("VISION_MODEL_NAME",""), self_id=os.getenv("ONEBOT_SELF_ID",""),
            napcat_token=os.getenv("ONEBOT_TOKEN",""), admin_token=os.getenv("ADMIN_TOKEN",""),
            first_business_date=os.getenv("CUO_FIRST_BUSINESS_DATE") or None,
            napcat_upload_root=Path(os.environ["NAPCAT_UPLOAD_ROOT"]) if os.getenv("NAPCAT_UPLOAD_ROOT") else None)
        if not result.database_url:
            raise ValueError("DATABASE_URL required")
        if result.model_protocol not in ("openai","anthropic") or result.model_timeout <= 0:
            raise ValueError("invalid model settings")
        return result
