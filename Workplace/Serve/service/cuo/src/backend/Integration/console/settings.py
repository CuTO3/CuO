'''
本文件用途：Validated operator-editable settings schema.

配置字段：
未检测到直接读取共享 Settings 或环境变量；局部参数与间接依赖仍需逐项核查。
'''

from pydantic import BaseModel, Field, ConfigDict

class ConsoleSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model_name: str = Field(min_length=1, max_length=120, pattern=r"^[\w./:@-]+$")
    model_timeout: float = Field(ge=10, le=300)
    max_message_length: int = Field(ge=200, le=4000)
    onebot_timeout: float = Field(ge=5, le=120)
