"""模块配置读取：只读小配置；路径相对 cuo 根目录；修改后重启生效。"""
from pathlib import Path
import os
import tomllib

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

# 唯一引导项：CUO_CONFIG_ROOT；未设置时使用应用根目录下 var/config。
APP_ROOT = Path(__file__).resolve().parents[3]


class ModuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DivineConfig(ModuleConfig):
    divine_candidate_keyword_rules_file: Path
    divine_repeat_fortune_cost: int = Field(strict=True, ge=0)
    divine_candidate_keyword_limit: int = Field(strict=True, gt=0)
    divine_candidate_excerpt_count_limit: int = Field(strict=True, gt=0)
    divine_candidate_excerpt_character_limit: int = Field(strict=True, gt=0)


class DivineAIConfig(ModuleConfig):
    divine_ai_enabled: bool = Field(strict=True, description="启用应事 AI；关闭时使用固定应事内容")
    divine_ai_api_key: SecretStr = Field(repr=False, description="此调用点专用的 LiteLLM 虚拟 Key")
    divine_ai_base_url: str = Field(strict=True, description="LiteLLM 接口地址")
    divine_ai_model_name: str = Field(strict=True, description="LiteLLM 中配置的模型名称")
    divine_ai_evidence_prompt_file: Path
    divine_ai_request_attempt_limit: int = Field(strict=True, ge=1, le=10)
    divine_ai_request_timeout_seconds: float = Field(strict=True, gt=0)
    divine_ai_response_max_tokens: int = Field(strict=True, gt=0)
    divine_ai_advice_min_characters: int = Field(strict=True, ge=0)
    divine_ai_advice_max_characters: int = Field(strict=True, gt=0)


class ReadingsConfig(ModuleConfig):
    divine_fixed_readings_file: Path


class ZhouYiConfig(ModuleConfig):
    divine_zhou_yi_hexagrams_file: Path


class TarotImageConfig(ModuleConfig):
    divine_tarot_picture_directory: Path
    divine_tarot_version: str = Field(strict=True, pattern=r"^[A-Za-z0-9_-]+$")


def load_module_config(relative_path: str, schema, *, config_root=None):
    """在模块导入时调用一次；不写文件、不读取总索引、不回退示例配置。"""
    root = Path(config_root or os.environ.get("CUO_CONFIG_ROOT") or APP_ROOT / "var/config")
    if not root.is_absolute():
        root = APP_ROOT / root
    path = root / relative_path
    try:
        with path.open("rb") as stream:
            values = tomllib.load(stream)
    except (OSError, ValueError):
        raise ValueError(f"无法读取模块配置：{path}") from None
    try:
        config = schema.model_validate(values)
    except ValidationError as error:
        fields = ", ".join(".".join(map(str, item["loc"])) for item in error.errors())
        raise ValueError(f"模块配置字段无效：{path} [{fields}]") from None
    for name in type(config).model_fields:
        value = getattr(config, name)
        if isinstance(value, Path):
            resolved = (value if value.is_absolute() else APP_ROOT / value).resolve()
            valid = resolved.is_dir() if name.endswith("_directory") else resolved.is_file()
            if not valid:
                raise ValueError(f"模块配置资源不存在：{path} [{name}]")
            config = config.model_copy(update={name: resolved})
    if isinstance(config, DivineAIConfig) and config.divine_ai_advice_min_characters > config.divine_ai_advice_max_characters:
        raise ValueError(f"模块配置长度范围无效：{path}")
    if isinstance(config, DivineAIConfig) and config.divine_ai_enabled:
        from urllib.parse import urlsplit
        try:
            url = urlsplit(config.divine_ai_base_url)
            valid_url = url.scheme in ("http", "https") and bool(url.hostname) and not (url.username or url.password or url.query or url.fragment)
        except ValueError:
            valid_url = False
        if not valid_url or not config.divine_ai_api_key.get_secret_value().strip() or not config.divine_ai_model_name.strip():
            raise ValueError(f"模块配置缺少有效的 LiteLLM 地址、专用密钥或模型名称：{path}")
    if isinstance(config, TarotImageConfig):
        deck = config.divine_tarot_picture_directory / ("Tarot -version-" + config.divine_tarot_version)
        if not deck.is_dir() or deck.is_symlink():
            raise ValueError(f"模块配置牌组目录不存在或无效：{path} [divine_tarot_version]")
    return config
