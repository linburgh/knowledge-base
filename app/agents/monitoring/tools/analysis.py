"""供 Deep Agent 调用的监控事实工具包装层。"""

from __future__ import annotations

from typing import Any

from langchain.tools import ToolRuntime, tool

from ..state import MonitoringHarnessContext


async def _query(
    name: str,
    *,
    runtime: ToolRuntime[MonitoringHarnessContext],
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """注入可信时间和范围、调用注册工具并保存授权事实。"""
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
                **(arguments or {}),
            },
            context={**session.trusted_context, "_monitoring_session": session},
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


@tool
async def get_alert_details(
    fact_ids: list[str],
    *,
    runtime: ToolRuntime[MonitoringHarnessContext],
) -> dict[str, Any]:
    """Query complete alert facts for previously observed alert fact IDs."""
    return await _query(
        "get_alert_details",
        runtime=runtime,
        arguments={"fact_ids": fact_ids},
    )


@tool
async def correlate_alerts(
    fact_ids: list[str],
    *,
    runtime: ToolRuntime[MonitoringHarnessContext],
) -> dict[str, Any]:
    """Compare alert metric, resource, scope, rule and trigger time to find related groups."""
    return await _query(
        "correlate_alerts",
        runtime=runtime,
        arguments={"fact_ids": fact_ids},
    )


@tool
async def query_metric_series(
    metric_codes: list[str],
    resource_codes: list[str] | None = None,
    *,
    runtime: ToolRuntime[MonitoringHarnessContext],
) -> dict[str, Any]:
    """Query time-series facts for selected metrics and optional resources."""
    return await _query(
        "query_metric_series",
        runtime=runtime,
        arguments={
            "metric_codes": metric_codes,
            "resource_codes": resource_codes or [],
        },
    )


@tool
async def query_resource_timeline(
    resource_codes: list[str] | None = None,
    trace_ids: list[str] | None = None,
    *,
    runtime: ToolRuntime[MonitoringHarnessContext],
) -> dict[str, Any]:
    """Query an authorized resource or trace timeline from monitoring events."""
    return await _query(
        "query_resource_timeline",
        runtime=runtime,
        arguments={
            "resource_codes": resource_codes or [],
            "trace_ids": trace_ids or [],
        },
    )


MONITORING_ANALYSIS_TOOLS = (
    query_health_snapshots,
    query_alerts,
    query_metrics,
    query_events,
    query_tasks,
    get_alert_details,
    correlate_alerts,
    query_metric_series,
    query_resource_timeline,
)

__all__ = (
    "MONITORING_ANALYSIS_TOOLS",
    "query_alerts",
    "query_events",
    "query_health_snapshots",
    "query_metrics",
    "query_tasks",
    "get_alert_details",
    "correlate_alerts",
    "query_metric_series",
    "query_resource_timeline",
)
