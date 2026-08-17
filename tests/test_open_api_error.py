"""Verify the Open API turns injected model failures into traceable 500 responses."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import httpx

from app.core.common.auth import CurrentUser, get_current_user
from app.main import app


async def main() -> None:
    async def override_user() -> CurrentUser:
        return CurrentUser(user_id="270", tenant_id=3, token="open-test")

    app.dependency_overrides[get_current_user] = override_user
    try:
        with patch(
            "app.core.common.access.require_knowledge_base_access",
            new=AsyncMock(return_value={"id": 34, "tenant_id": 3, "status": "active"}),
        ), patch(
            "app.api.open.routes.retrieval_service.search",
            new=AsyncMock(side_effect=RuntimeError("injected model failure")),
        ):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/open/search",
                    headers={"Authorization": "Bearer injected"},
                    json={"knowledge_base_id": 34, "query": "模型故障", "mode": "keyword", "top_k": 1},
                )
        assert response.status_code == 500, response.text
        body = response.json()
        assert body["code"] == "INTERNAL_ERROR"
        assert body["request_id"]
        assert body["retryable"] is True
        print("PASS open API injected model failure: HTTP 500 with request_id")
    finally:
        app.dependency_overrides.clear()


if __name__ == "__main__":
    asyncio.run(main())
