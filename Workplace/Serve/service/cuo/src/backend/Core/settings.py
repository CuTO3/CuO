'''
本文件用途：从各模块私有小配置装配共享运行设置。

配置字段：
postgresql_*    数据库连接、连接池及群映射
napcat_*        机器人账号、接入凭据、超时及上传目录
workflow_*      数据目录与接收队列容量
sender_*        消息长度上限
console_*       控制台登录凭据
archive_*       首次业务日期
'''

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
    data_root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[3] / "var/data")
    config_directory: Path | None = None
    @property
    def var_root(self):return self.data_root.parent
    @property
    def config_root(self):return self.config_directory or self.var_root / "config"
    @property
    def cache_root(self):return self.var_root / "cache"
    model_base_url: str = ""
    model_api_key: str = field(default="", repr=False)
    model_name: str = ""
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
        from Core.configuration import read, resource, config_root
        database = read("database")
        registered = read("groups")["postgresql_registered_groups"]
        napcat = read("napcat")
        runtime = read("runtime")
        sender = read("sender")
        console = read("console")
        archive = read("archive")
        if not isinstance(registered, dict) or any(not isinstance(c, dict) for c in registered.values()):
            raise ValueError("invalid registered group configuration")
        groups = {str(g): GroupSettings(str(c.get("schema", g))) for g, c in registered.items() if c.get("enabled", True)}
        if not groups or any(not g.isascii() or not g.isdecimal() or not c.schema.isascii() or not c.schema.isdecimal() for g, c in groups.items()):
            raise ValueError("registered decimal groups are required")
        if len({c.schema for c in groups.values()}) != len(groups):
            raise ValueError("group schemas must be unique")
        if not database["postgresql_connection_url"].strip():
            raise ValueError("postgresql_connection_url required")
        if database["postgresql_pool_min_connections"] > database["postgresql_pool_max_connections"]:
            raise ValueError("invalid PostgreSQL pool bounds")
        if archive["archive_first_business_date"]:
            from datetime import date
            date.fromisoformat(archive["archive_first_business_date"])
        return cls(
            database_url=database["postgresql_connection_url"], groups=groups,
            database_pool_min=database["postgresql_pool_min_connections"],
            database_pool_max=database["postgresql_pool_max_connections"],
            data_root=resource(runtime["workflow_data_directory"]), config_directory=config_root(),
            inbound_queue_size=runtime["workflow_inbound_queue_capacity"],
            self_id=napcat["napcat_bot_self_id"], napcat_token=napcat["napcat_access_token"],
            onebot_timeout=napcat["napcat_request_timeout_seconds"],
            napcat_upload_root=resource(napcat["napcat_upload_directory"]) if napcat["napcat_upload_directory"] else None,
            admin_token=console["console_admin_token"],
            max_message_length=sender["sender_message_character_limit"],
            first_business_date=archive["archive_first_business_date"] or None,
        )
