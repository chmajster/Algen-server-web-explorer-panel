from __future__ import annotations

from pydantic import BaseModel, Field


class TerminateSessionInput(BaseModel):
    session_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    confirm: bool = False
