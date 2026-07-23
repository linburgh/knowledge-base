from __future__ import annotations

from pydantic import BaseModel, Field


class MenuNodeResponse(BaseModel):
    id: int
    code: str
    name: str
    menu_type: str
    route_path: str | None = None
    icon: str | None = None
    sort_order: int = 0
    children: list[MenuNodeResponse] = Field(default_factory=list)


class MenuTreeResponse(BaseModel):
    default_path: str | None = None
    menus: list[MenuNodeResponse] = Field(default_factory=list)


__all__ = ("MenuNodeResponse", "MenuTreeResponse")
