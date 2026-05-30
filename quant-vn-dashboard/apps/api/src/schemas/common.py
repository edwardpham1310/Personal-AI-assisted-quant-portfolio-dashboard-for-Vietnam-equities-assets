"""Common Pydantic DTOs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class NotImplementedResponse(BaseModel):
    """Standard body for placeholder/scaffold endpoints."""

    status: Literal["not_implemented"] = "not_implemented"
    module: str
    message: str = Field(default="This endpoint is a scaffold.")


class ErrorResponse(BaseModel):
    detail: str
