"""P1 service fault-injection checks for statistics dependency failures."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app.config import configure
from app.core.common.auth import CurrentUser
from app.core.services import knowledge_base_overview, platform_overview
from app.db import base


async def main() -> None:
    configure("app")
    await base.setup()
    try:
        fixture = await base.DATABASE.fetch_one(
            "select id from t_user where username = :username",
            {"username": "e2e_eval_admin_20260726"},
        )
        if fixture is None:
            raise RuntimeError("P1 fixture admin is required")
        fixture_user_id = str(fixture["id"])
        with patch(
            "app.core.services.platform_overview.platform_overview_db.metrics",
            new=AsyncMock(side_effect=RuntimeError("injected platform metrics failure")),
        ):
            try:
                await platform_overview.get_overview()
            except RuntimeError as exc:
                assert "injected platform metrics failure" in str(exc)
                print("PASS platform overview dependency failure propagated")
            else:
                raise AssertionError("platform overview did not propagate injected dependency failure")

        with patch(
            "app.core.services.knowledge_base_overview.overview_db.metrics",
            new=AsyncMock(side_effect=RuntimeError("injected knowledge-base metrics failure")),
        ):
            try:
                await knowledge_base_overview.get_overview(
                    34,
                    current_user=CurrentUser(user_id=fixture_user_id, tenant_id=3, token="p1-fault"),
                )
            except RuntimeError as exc:
                assert "injected knowledge-base metrics failure" in str(exc)
                print("PASS knowledge-base overview dependency failure propagated")
            else:
                raise AssertionError("knowledge-base overview did not propagate injected dependency failure")
    finally:
        await base.DATABASE.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
