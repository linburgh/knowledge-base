from __future__ import annotations

from typing import Any

from langchain.tools import ToolRuntime, tool

from ..state import MonitoringHarnessContext


async def _query(
    name: str,
    *,
    runtime: ToolRuntime[MonitoringHarnessContext],
) -> dict[str, Any]:
    session = runtime.context.session
    selected_range = session.require_time_range()
    try:
        result, trace = await session.runtime.invoke_tool(
            registry=session.registry,
            name=name,
            arguments={
                "window_start": selected_range.start,
                "window_end": selected_range.end,
                "scope_key": str(session.trusted_context.get("scope_key") or "platform"),
            },
            context=session.trusted_context,
        )
    except Exception as exc:
        session.failed_tools.append(name)
        session.tool_calls.append(session.runtime.failed_trace(name, exc))
        raise
    session.failed_tools = [item for item in session.failed_tools if item != name]
    result = await session.store_fact(name, result)
    session.tool_calls.append(trace)
    return result


@tool
async def query_health_snapshots(
    *,
    runtime: ToolRuntime[MonitoringHarnessContext],
) -> dict[str, Any]:
    """Query health snapshots in the server-authorized time range."""
    return await _query(
        "query_health_snapshots",
        runtime=runtime,
    )


@tool
async def query_alerts(
    *,
    runtime: ToolRuntime[MonitoringHarnessContext],
) -> dict[str, Any]:
    """Query alert facts in the server-authorized time range."""
    return await _query(
        "query_alerts",
        runtime=runtime,
    )


@tool
async def query_metrics(
    *,
    runtime: ToolRuntime[MonitoringHarnessContext],
) -> dict[str, Any]:
    """Query metric facts in the server-authorized time range."""
    return await _query(
        "query_metrics",
        runtime=runtime,
    )


@tool
async def query_events(
    *,
    runtime: ToolRuntime[MonitoringHarnessContext],
) -> dict[str, Any]:
    """Query event facts in the server-authorized time range."""
    return await _query(
        "query_events",
        runtime=runtime,
    )


@tool
async def query_tasks(
    *,
    runtime: ToolRuntime[MonitoringHarnessContext],
) -> dict[str, Any]:
    """Query task facts in the server-authorized time range."""
    return await _query(
        "query_tasks",
        runtime=runtime,
    )


MONITORING_ANALYSIS_TOOLS = (
    query_health_snapshots,
    query_alerts,
    query_metrics,
    query_events,
    query_tasks,
)

__all__ = (
    "MONITORING_ANALYSIS_TOOLS",
    "query_alerts",
    "query_events",
    "query_health_snapshots",
    "query_metrics",
    "query_tasks",
)
