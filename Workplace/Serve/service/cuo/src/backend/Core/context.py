'''
本文件用途：Core/context.py 的后端实现。

配置字段：
未检测到直接读取共享 Settings 或环境变量；局部参数与间接依赖仍需逐项核查。
'''

from dataclasses import dataclass
from typing import Any
@dataclass
class RuntimeContext:
    settings: Any
    db: Any
    model: Any
    onebot: Any
    cache: Any = None
    queue: Any = None
    ready: bool = False
