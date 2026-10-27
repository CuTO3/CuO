"""Validated operator-editable settings schema."""
from pydantic import BaseModel, Field, ConfigDict

class ConsoleSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model_name: str = Field(min_length=1, max_length=120, pattern=r"^[\w./:@-]+$")
    model_timeout: float = Field(ge=10, le=300)
    max_message_length: int = Field(ge=200, le=4000)
    onebot_timeout: float = Field(ge=5, le=120)

