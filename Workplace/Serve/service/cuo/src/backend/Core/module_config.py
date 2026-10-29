'''
本文件用途：模块配置读取：只读小配置；路径相对 cuo 根目录；修改后重启生效。

配置字段：
CUO_CONFIG_ROOT    配置根目录，包含 config_index.json 与私有小配置
'''

from pathlib import Path
import os
import tomllib

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

# 唯一引导项：CUO_CONFIG_ROOT；未设置时使用应用根目录下 var/config。
APP_ROOT = Path(__file__).resolve().parents[3]


class ModuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _models_from_index():
    import json
    from pydantic import create_model
    directory = Path(os.environ.get("CUO_CONFIG_ROOT") or APP_ROOT / "var/config")
    if not directory.is_absolute(): directory = APP_ROOT / directory
    document = json.loads((directory / "config_index.json").read_text(encoding="utf-8"))
    result = {}
    for entry in document["modules"]:
        if not entry.get("model_class"): continue
        fields = {}
        for name, spec in entry["json_schema"]["properties"].items():
            kind = Path if spec.get("format") == "path" else SecretStr if spec.get("writeOnly") else {"string": str, "integer": int, "number": float, "boolean": bool}[spec["type"]]
            constraints = {target: spec[source] for source, target in (("minimum","ge"),("maximum","le"),("exclusiveMinimum","gt"),("pattern","pattern"),("minLength","min_length")) if source in spec}
            if kind in (str,int,float,bool): constraints["strict"] = True
            fields[name] = (kind, Field(repr=not spec.get("writeOnly",False), **constraints))
        result[entry["model_class"]] = create_model(entry["model_class"], __base__=ModuleConfig, **fields)
    return result


globals().update(_models_from_index())


def load_module_config(relative_path: str, schema, *, config_root=None):
    """在模块导入时调用一次；不写文件；字段结构来自总索引；不回退示例配置。"""
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
    return validate_config(config, path)


def validate_config(config, path):
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
