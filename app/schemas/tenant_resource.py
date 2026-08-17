from __future__ import annotations

from pydantic import BaseModel, Field


class ResourceBatchRequest(BaseModel):
    resource_ids: list[int] = Field(..., min_length=1)


__all__ = ("ResourceBatchRequest",)
