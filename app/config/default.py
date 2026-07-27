from __future__ import annotations

from pydantic import StrictBool, StrictInt, StrictStr

from app.config.base import Opt

environment = Opt(
    name="environment",
    description="Runtime environment",
    schema=StrictStr,
    default="development",
)

debug = Opt(
    name="debug",
    description="Enable debug mode",
    schema=StrictBool,
    default=False,
)

log_dir = Opt(
    name="log_dir",
    description="Log directory",
    schema=StrictStr,
    default="./log",
)

log_file = Opt(
    name="log_file",
    description="Log file",
    schema=StrictStr,
    default="app.log",
)

log_level = Opt(
    name="log_level",
    description="Log level",
    schema=StrictStr,
    default="INFO",
)

database_url = Opt(
    name="database_url",
    description="Database URL",
    schema=StrictStr,
    default="sqlite:///./data/app.db",
)

http_trust_env = Opt(
    name="http_trust_env",
    description="Whether outbound HTTP clients should trust proxy environment variables",
    schema=StrictBool,
    default=False,
)

request_id_header = Opt(
    name="request_id_header",
    description="Request id header name",
    schema=StrictStr,
    default="X-Request-ID",
)

db_connect_on_startup = Opt(
    name="db_connect_on_startup",
    description="Connect database during application startup",
    schema=StrictBool,
    default=True,
)

allowed_file_extensions = Opt(
    name="allowed_file_extensions",
    description="Allowed upload file extensions",
    schema=list[StrictStr],
    default=[".pdf", ".md", ".markdown", ".txt", ".docx"],
)

max_upload_size_mb = Opt(
    name="max_upload_size_mb",
    description="Max upload file size in MiB",
    schema=StrictInt,
    default=100,
)

indexing_task_timeout_seconds = Opt(
    name="indexing_task_timeout_seconds",
    description="Maximum document indexing task duration",
    schema=StrictInt,
    default=1800,
)

scheduler_enabled = Opt(
    name="scheduler_enabled",
    description="Enable backend-managed APScheduler workers",
    schema=StrictBool,
    default=True,
)

indexing_scheduler_batch_size = Opt(
    name="indexing_scheduler_batch_size",
    description="Maximum indexing tasks handled by one scheduler run",
    schema=StrictInt,
    default=1,
)

indexing_stale_after_seconds = Opt(
    name="indexing_stale_after_seconds",
    description="Age after which a running indexing task is recoverable",
    schema=StrictInt,
    default=300,
)

evaluation_worker_poll_seconds = Opt(
    name="evaluation_worker_poll_seconds",
    description="Autonomous evaluation worker polling interval",
    schema=StrictInt,
    default=2,
)

GROUP_NAME = __name__.split(".")[-1]
ALL_OPTS = (
    environment,
    debug,
    log_dir,
    log_file,
    log_level,
    database_url,
    http_trust_env,
    request_id_header,
    db_connect_on_startup,
    allowed_file_extensions,
    max_upload_size_mb,
    indexing_task_timeout_seconds,
    scheduler_enabled,
    indexing_scheduler_batch_size,
    indexing_stale_after_seconds,
    evaluation_worker_poll_seconds,
)

__all__ = ("GROUP_NAME", "ALL_OPTS")
