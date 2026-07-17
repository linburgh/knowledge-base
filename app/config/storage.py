from __future__ import annotations

from pydantic import StrictBool, StrictStr

from app.config.base import Opt

backend = Opt(
    name="backend",
    description="Storage backend",
    schema=StrictStr,
    default="minio",
)

local_dir = Opt(
    name="local_dir",
    description="Local storage directory",
    schema=StrictStr,
    default="./storage",
)

minio_endpoint = Opt(
    name="minio_endpoint",
    description="MinIO endpoint",
    schema=StrictStr,
    default="http://127.0.0.1:9000",
)

minio_access_key = Opt(
    name="minio_access_key",
    description="MinIO access key",
    schema=StrictStr,
    default="linburgh",
)

minio_secret_key = Opt(
    name="minio_secret_key",
    description="MinIO secret key",
    schema=StrictStr,
    default="linburgh",
)

minio_bucket = Opt(
    name="minio_bucket",
    description="MinIO bucket",
    schema=StrictStr,
    default="knowledge-base",
)

minio_secure = Opt(
    name="minio_secure",
    description="Whether MinIO endpoint uses HTTPS",
    schema=StrictBool,
    default=False,
)

GROUP_NAME = __name__.split(".")[-1]
ALL_OPTS = (
    backend,
    local_dir,
    minio_endpoint,
    minio_access_key,
    minio_secret_key,
    minio_bucket,
    minio_secure,
)

__all__ = ("GROUP_NAME", "ALL_OPTS")
