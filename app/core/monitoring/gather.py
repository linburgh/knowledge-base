from __future__ import annotations

import asyncio
import inspect
import random
from collections import deque
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from time import monotonic
from typing import Any, TypeVar, cast

from app.core.common import utils
from app.core.common.log import LOG
from app.db import evaluation_run as evaluation_run_db
from app.db import evaluation_task as evaluation_task_db
from app.db import indexing_task as indexing_task_db
from app.db import knowledge_base as knowledge_base_db
from app.db import monitor_event as event_db
from app.db import monitor_gather_action as action_db
from app.db import monitor_gather_target as target_db
from app.db.base import DB, inject_db

F = TypeVar("F", bound=Callable[..., Any])
_EMITTING: ContextVar[bool] = ContextVar("monitor_gather_emitting", default=False)
_FAILED_EMITS: deque[dict[str, str]] = deque(maxlen=128)
_DROPPED_FAILED_EMITS = 0
_SENSITIVE_TOKENS = {
    "answer",
    "api_key",
    "content",
    "document",
    "password",
    "prompt",
    "question",
    "secret",
    "snippet",
    "token",
}
_STANDARD_FIELDS = {
    "tenant_id",
    "kb_id",
    "task_id",
    "run_id",
    "trace_id",
    "request_id",
    "duration_ms",
    "stage",
    "source_code",
    "status",
    "data_status",
    "event_id",
}
_ALLOWED_COLLECTORS = {
    "collector_self_collector",
    "document_indexing_collector",
    "document_ingestion_collector",
    "evaluation_run_collector",
    "http_request_collector",
    "knowledge_qa_collector",
    "sql_operation_collector",
    "status_probe_collector",
    "worker_lifecycle_collector",
}


@dataclass(frozen=True, slots=True)
class GatherRegistration:
    target_code: str
    module: str
    qualname: str


class MonitorGatherRegistry:
    def __init__(self) -> None:
        self._targets: dict[str, GatherRegistration] = {}

    def register(self, target_code: str, function: Callable[..., Any]) -> None:
        registration = GatherRegistration(
            target_code=target_code,
            module=function.__module__,
            qualname=function.__qualname__,
        )
        existing = self._targets.get(target_code)
        if existing is not None and existing != registration:
            raise ValueError(f"monitor_gather target_code 重复登记: {target_code}")
        self._targets[target_code] = registration

    def get(self, target_code: str) -> GatherRegistration | None:
        return self._targets.get(target_code)

    def list(self) -> tuple[GatherRegistration, ...]:
        return tuple(self._targets.values())


MONITOR_GATHER_REGISTRY = MonitorGatherRegistry()


def _path_value(root: Any, path: str) -> Any:
    current = root
    for part in path.split("."):
        if current is None:
            return None
        if part == "length":
            try:
                return len(current)
            except TypeError:
                return None
        if isinstance(current, (list, tuple)) and part.isdigit():
            index = int(part)
            current = current[index] if index < len(current) else None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
    return current


def _safe_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)[:256]


def _safe_payload(values: dict[str, Any], allowlist: list[str]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in allowlist:
        normalized = key.lower()
        if any(token in normalized for token in _SENSITIVE_TOKENS):
            continue
        if key in values:
            payload[key] = _safe_scalar(values[key])
    return payload


def _positive_id(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _record_emit_failure(
    target_code: str,
    event_type: str,
    error: BaseException,
) -> None:
    global _DROPPED_FAILED_EMITS
    if len(_FAILED_EMITS) == _FAILED_EMITS.maxlen:
        _DROPPED_FAILED_EMITS += 1
    _FAILED_EMITS.append(
        {
            "target_code": target_code[:128],
            "event_type": event_type[:96],
            "error_category": type(error).__name__[:64],
            "failed_at": utils.utc_now().isoformat(),
        }
    )


def _should_sample(
    mapping: dict[str, Any],
    sampling_rate: float,
    values: dict[str, Any],
    error: BaseException | None,
) -> bool:
    if sampling_rate <= 0:
        return False
    strategy = mapping.get("sampling") or {"mode": "all"}
    if not isinstance(strategy, dict):
        return False
    mode = str(strategy.get("mode") or "all")
    status = str(values.get("status") or mapping.get("status") or "")
    is_error = error is not None or status in {
        "cancelled",
        "degraded",
        "failed",
        "timeout",
    }
    tenant_ids = {
        item
        for item in strategy.get("tenant_ids") or []
        if isinstance(item, int) and not isinstance(item, bool) and item > 0
    }
    if mode == "errors_only" and not is_error:
        return False
    if mode == "tenant" and values.get("tenant_id") not in tenant_ids:
        return False
    if mode == "composite":
        if strategy.get("errors_only") is True and not is_error:
            return False
        if tenant_ids and values.get("tenant_id") not in tenant_ids:
            return False
    if mode not in {"all", "composite", "errors_only", "tenant"}:
        return False
    return sampling_rate >= 1 or random.random() <= sampling_rate


async def _database() -> Any:
    try:
        return DB.get()
    except LookupError:
        await inject_db()
        return DB.get()


async def _configuration(
    target_code: str,
    *,
    event_type: str | None = None,
    hook: str | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    db = await _database()
    now = utils.utc_now()
    targets = await target_db.list(db, target_code=target_code, enabled=True)
    candidates = [
        row for row in targets if row.get("effective_at") is None or row["effective_at"] <= now
    ]
    if not candidates:
        return None, []
    target = max(candidates, key=lambda row: int(row.get("version") or 0))
    collector = str((target.get("target_locator") or {}).get("collector") or "")
    if collector and collector not in _ALLOWED_COLLECTORS:
        LOG.error(
            "monitor_gather collector rejected target_code={} collector={}",
            target_code,
            collector,
        )
        return None, []
    actions = await action_db.list(
        db,
        target_code=target_code,
        enabled=True,
        version=target["version"],
    )
    if event_type is not None:
        actions = [row for row in actions if row.get("event_type") == event_type]
    if hook is not None:
        actions = [row for row in actions if (row.get("field_mapping") or {}).get("hook") == hook]
    return target, actions


def _mapped_values(
    target: dict[str, Any],
    *,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    result: Any,
    fields: dict[str, Any],
) -> dict[str, Any]:
    values = dict(fields)
    locator = target.get("target_locator") or {}
    root = {
        "args": args,
        "kwargs": kwargs,
        "result": result,
        "context": args[1] if len(args) > 1 else kwargs.get("context"),
    }
    for mapping_name in ("input_mapping", "output_mapping"):
        for key, path in (locator.get(mapping_name) or {}).items():
            if key not in values:
                values[key] = _path_value(root, str(path))
    return values


async def _enrich_scope(
    target_code: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    result = dict(values)
    db = await _database()
    kb_id = _positive_id(result.get("kb_id"))
    if target_code == "document.indexing" and kb_id is None:
        task_id = _positive_id(result.get("task_id"))
        task = await indexing_task_db.get(db, id=task_id) if task_id else None
        kb_id = _positive_id((task or {}).get("kb_id"))
        if task:
            result.setdefault("document_id", task.get("document_id"))
    if target_code == "evaluation.run" and kb_id is None:
        run_id = _positive_id(result.get("run_id"))
        run = await evaluation_run_db.get(db, id=run_id) if run_id else None
        evaluation_task = (
            await evaluation_task_db.get(db, id=run.get("task_id"))
            if run and _positive_id(run.get("task_id"))
            else None
        )
        if evaluation_task:
            kb_id = _positive_id(evaluation_task.get("kb_id"))
            result.setdefault("tenant_id", evaluation_task.get("tenant_id"))
            result.setdefault("task_id", evaluation_task.get("id"))
    if target_code == "knowledge.qa" and result.get("purpose") == "monitor_probe":
        result["source_code"] = "knowledge.qa.monitor_probe"
    if kb_id is not None:
        result["kb_id"] = kb_id
        if _positive_id(result.get("tenant_id")) is None:
            knowledge_base = await knowledge_base_db.get(db, id=kb_id)
            if knowledge_base:
                result["tenant_id"] = knowledge_base.get("tenant_id")
    result["tenant_id"] = _positive_id(result.get("tenant_id"))
    result["kb_id"] = _positive_id(result.get("kb_id"))
    result["task_id"] = _positive_id(result.get("task_id"))
    result["run_id"] = _positive_id(result.get("run_id"))
    return result


async def _persist(
    target: dict[str, Any],
    action: dict[str, Any],
    *,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    result: Any,
    fields: dict[str, Any],
    error: BaseException | None,
) -> None:
    sampling_rate = float(action.get("sampling_rate") or 0)
    mapping = action.get("field_mapping") or {}
    values = await _enrich_scope(
        str(target["target_code"]),
        _mapped_values(
            target,
            args=args,
            kwargs=kwargs,
            result=result,
            fields=fields,
        ),
    )
    if not _should_sample(mapping, sampling_rate, values, error):
        return
    event_type = str(action["event_type"])
    status = str(values.get("status") or mapping.get("status") or "completed")
    duration_ms = values.get("duration_ms")
    if duration_ms is not None:
        duration_ms = max(0, int(duration_ms))
    event_id = str(values.get("event_id") or f"{target['target_code']}:{utils.new_request_id()}")
    payload_allowlist = [str(item) for item in mapping.get("payload_allowlist") or []]
    payload = _safe_payload(values, payload_allowlist)
    db = await _database()
    if await event_db.get(db, event_id=event_id):
        return
    event_values = {
        "event_id": event_id[:128],
        "event_type": event_type,
        "source_type": str(mapping.get("source_type") or target["target_type"])[:32],
        "source_code": str(values.get("source_code") or target["target_code"])[:128],
        "tenant_id": values.get("tenant_id"),
        "kb_id": values.get("kb_id"),
        "task_id": values.get("task_id"),
        "run_id": values.get("run_id"),
        "trace_id": str(values["trace_id"])[:128] if values.get("trace_id") else None,
        "request_id": str(values["request_id"])[:128] if values.get("request_id") else None,
        "status": status[:32],
        "stage": str(values["stage"])[:64] if values.get("stage") else None,
        "occurred_at": values.get("occurred_at") or utils.utc_now(),
        "duration_ms": duration_ms,
        "error_category": type(error).__name__[:64] if error is not None else None,
        "payload": payload,
        "data_status": str(values.get("data_status") or "ready")[:32],
    }
    async with db.transaction():
        await event_db.insert_(db, **event_values)


async def emit_gather_event(
    target_code: str,
    event_type: str | None = None,
    *,
    hook: str | None = None,
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
    result: Any = None,
    error: BaseException | None = None,
    **fields: Any,
) -> int:
    if _EMITTING.get():
        return 0
    token = _EMITTING.set(True)
    try:
        async with asyncio.timeout(1):
            target, actions = await _configuration(
                target_code,
                event_type=event_type,
                hook=hook,
            )
            if target is None:
                return 0
            count = 0
            for action in actions:
                action_collector = str((action.get("field_mapping") or {}).get("collector") or "")
                if action_collector not in _ALLOWED_COLLECTORS:
                    LOG.error(
                        "monitor_gather action collector rejected target_code={} event_type={}",
                        target_code,
                        action.get("event_type"),
                    )
                    continue
                await _persist(
                    target,
                    action,
                    args=args,
                    kwargs=kwargs or {},
                    result=result,
                    fields=fields,
                    error=error,
                )
                count += 1
            return count
    except Exception as exc:
        failure_event_type = event_type or hook or "unknown"
        _record_emit_failure(target_code, failure_event_type, exc)
        LOG.opt(exception=exc).error(
            "monitor_gather emit failed target_code={} event_type={}",
            target_code,
            failure_event_type,
        )
        return 0
    finally:
        _EMITTING.reset(token)


def monitor_gather(target_code: str) -> Callable[[F], F]:
    if not target_code or len(target_code) > 128:
        raise ValueError("monitor_gather target_code 无效")

    def decorator(function: F) -> F:
        MONITOR_GATHER_REGISTRY.register(target_code, function)
        if not inspect.iscoroutinefunction(function):
            raise TypeError("monitor_gather 当前仅支持 async 目标方法")

        @wraps(function)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            started = monotonic()
            await emit_gather_event(
                target_code,
                hook="before",
                args=args,
                kwargs=kwargs,
            )
            try:
                result = await function(*args, **kwargs)
            except BaseException as exc:
                await emit_gather_event(
                    target_code,
                    hook="exception",
                    args=args,
                    kwargs=kwargs,
                    error=exc,
                    duration_ms=int((monotonic() - started) * 1000),
                )
                raise
            await emit_gather_event(
                target_code,
                hook="after",
                args=args,
                kwargs=kwargs,
                result=result,
                duration_ms=int((monotonic() - started) * 1000),
            )
            return result

        return cast(F, wrapper)

    return decorator


def monitoring_emit_in_progress() -> bool:
    return _EMITTING.get()


async def flush_gather_failures() -> int:
    global _DROPPED_FAILED_EMITS
    if not _FAILED_EMITS and _DROPPED_FAILED_EMITS == 0:
        return 0
    failures = list(_FAILED_EMITS)
    dropped_count = _DROPPED_FAILED_EMITS
    _FAILED_EMITS.clear()
    _DROPPED_FAILED_EMITS = 0
    target_count = len({item["target_code"] for item in failures})
    written = await emit_gather_event(
        "collector.self",
        "collector_recovery_completed",
        source_code="monitor-collector",
        failure_count=len(failures),
        dropped_count=dropped_count,
        target_count=target_count,
        last_failure_at=failures[-1]["failed_at"] if failures else None,
    )
    if written:
        return len(failures) + dropped_count
    for failure in failures:
        _FAILED_EMITS.append(failure)
    _DROPPED_FAILED_EMITS += dropped_count
    return 0


__all__ = (
    "MONITOR_GATHER_REGISTRY",
    "MonitorGatherRegistry",
    "emit_gather_event",
    "flush_gather_failures",
    "monitor_gather",
    "monitoring_emit_in_progress",
)
