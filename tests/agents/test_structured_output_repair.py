from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from pydantic import BaseModel, Field

from app.core.common.structured_output import repair_structured_output


class RepairSchema(BaseModel):
    answer: str = Field(min_length=1)


class FakeRepairAgent:
    def __init__(self, result):
        self.result = result
        self.inputs = None

    async def ainvoke(self, inputs):
        self.inputs = inputs
        return self.result


@pytest.mark.asyncio
async def test_repair_uses_one_call_agent_without_business_tools() -> None:
    fake = FakeRepairAgent({"structured_response": {"answer": "已修复"}})
    with patch(
        "app.core.common.structured_output.create_agent",
        return_value=fake,
    ) as create:
        result = await repair_structured_output(
            model=object(),
            schema=RepairSchema,
            evidence_payload={"fact": "value"},
            timeout_seconds=1,
            agent_name="test_agent",
        )

    assert result.value == RepairSchema(answer="已修复")
    assert result.attempted is True
    assert create.call_args.kwargs["tools"] == []
    assert create.call_args.kwargs["middleware"][0].run_limit == 1
    assert "value" in fake.inputs["messages"][0]["content"]


@pytest.mark.asyncio
async def test_repair_reports_missing_terminal_and_unavailable_budget() -> None:
    fake = FakeRepairAgent({"messages": []})
    with patch("app.core.common.structured_output.create_agent", return_value=fake):
        missing = await repair_structured_output(
            model=object(),
            schema=RepairSchema,
            evidence_payload={},
            timeout_seconds=1,
            agent_name="test_agent",
        )
    unavailable = await repair_structured_output(
        model=object(),
        schema=RepairSchema,
        evidence_payload={},
        timeout_seconds=0,
        agent_name="test_agent",
    )

    assert missing.value is None
    assert missing.error == "StructuredOutputMissing"
    assert missing.attempted is True
    assert unavailable.error == "RepairBudgetUnavailable"
    assert unavailable.attempted is False


@pytest.mark.asyncio
async def test_repair_timeout_is_bounded() -> None:
    class SlowRepairAgent:
        async def ainvoke(self, inputs):
            del inputs
            await asyncio.sleep(1)

    with patch(
        "app.core.common.structured_output.create_agent",
        return_value=SlowRepairAgent(),
    ):
        result = await repair_structured_output(
            model=object(),
            schema=RepairSchema,
            evidence_payload={},
            timeout_seconds=0.01,
            agent_name="test_agent",
        )

    assert result.value is None
    assert result.error == "RepairTimeout"
