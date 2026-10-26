from dataclasses import dataclass
from typing import Any


@dataclass
class RuntimeContext:
    settings: Any
    db: Any
    model: Any
    onebot: Any
    cache: Any
    queue: Any = None
    ready: bool = False
