from __future__ import annotations

RUNTIME_RESOURCE_NAMES = {
    "api-service": "接口服务",
    "database": "数据存储",
    "llm-service": "模型服务",
    "embedding-service": "嵌入服务",
    "rerank-service": "重排服务",
    "vector-service": "向量服务",
    "storage-service": "对象存储",
    "monitor-collector": "监控采集",
    "worker-runtime": "工作节点",
    "task-backlog": "任务积压",
    "knowledge-qa-probe": "问答探针",
}

RUNTIME_RESOURCE_PRIORITY = {
    resource_code: index
    for index, resource_code in enumerate(
        (
            "api-service",
            "database",
            "llm-service",
            "embedding-service",
            "rerank-service",
            "vector-service",
            "storage-service",
            "monitor-collector",
            "worker-runtime",
            "task-backlog",
            "knowledge-qa-probe",
        )
    )
}

RUNTIME_STATUS_RISK = {
    "failed": 0,
    "error": 0,
    "stopped": 0,
    "timeout": 0,
    "warning": 1,
    "stale": 1,
    "degraded": 1,
    "empty": 2,
    "unknown": 2,
    "healthy": 3,
    "normal": 3,
    "idle": 3,
    "busy": 3,
}


def runtime_resource_name(resource_code: str | None) -> str:
    return RUNTIME_RESOURCE_NAMES.get(resource_code or "", "其他服务")


def runtime_resource_sort_key(resource: dict[str, object]) -> tuple[int, int, str]:
    status = str(resource.get("status") or "unknown")
    resource_code = str(resource.get("resource_code") or "")
    return (
        RUNTIME_STATUS_RISK.get(status, 2),
        RUNTIME_RESOURCE_PRIORITY.get(resource_code, len(RUNTIME_RESOURCE_PRIORITY)),
        resource_code,
    )
