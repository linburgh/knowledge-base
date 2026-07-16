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

dev_user_id = Opt(
    name="dev_user_id",
    description="Development-only fallback user id",
    schema=StrictStr,
    default="dev-user",
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
    default=20,
)

local_storage_dir = Opt(
    name="local_storage_dir",
    description="Local storage directory",
    schema=StrictStr,
    default="./storage",
)

GROUP_NAME = __name__.split(".")[-1]
ALL_OPTS = (
    environment,
    debug,
    log_dir,
    log_file,
    log_level,
    database_url,
    dev_user_id,
    http_trust_env,
    request_id_header,
    db_connect_on_startup,
    allowed_file_extensions,
    max_upload_size_mb,
    local_storage_dir,
)

__all__ = ("GROUP_NAME", "ALL_OPTS")
