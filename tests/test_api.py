import unittest

import httpx

from app.main import app


class ApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_health_check(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
