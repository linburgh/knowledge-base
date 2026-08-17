from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from anyio import to_thread
from minio import Minio

from app.config import CONF
from app.core.common.exception import BusiException


def _get_minio_client() -> Minio:
    endpoint = CONF.storage.minio_endpoint
    parsed = urlparse(endpoint)
    if parsed.scheme:
        endpoint = parsed.netloc

    if not endpoint:
        raise BusiException("MinIO endpoint 不能为空")

    return Minio(
        endpoint,
        access_key=CONF.storage.minio_access_key,
        secret_key=CONF.storage.minio_secret_key,
        secure=CONF.storage.minio_secure,
    )


async def ensure_bucket() -> None:
    client = _get_minio_client()
    bucket = CONF.storage.minio_bucket

    def _ensure() -> None:
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)

    try:
        await to_thread.run_sync(_ensure)
    except Exception as exc:
        raise BusiException(f"MinIO bucket 初始化失败: {exc}") from exc


async def health_check() -> bool:
    client = _get_minio_client()
    bucket = CONF.storage.minio_bucket
    try:
        return await to_thread.run_sync(client.bucket_exists, bucket)
    except Exception as exc:
        raise BusiException(f"MinIO 健康检查失败: {exc}") from exc


async def bucket_usage_bytes() -> int:
    client = _get_minio_client()
    bucket = CONF.storage.minio_bucket

    def _usage() -> int:
        if not client.bucket_exists(bucket):
            raise BusiException("MinIO Bucket 不存在")
        return sum(int(item.size or 0) for item in client.list_objects(bucket, recursive=True))

    try:
        return await to_thread.run_sync(_usage)
    except Exception as exc:
        if isinstance(exc, BusiException):
            raise
        raise BusiException(f"MinIO 容量统计失败: {exc}") from exc


async def upload_file(
    object_name: str,
    file_path: Path,
    content_type: str = "application/octet-stream",
) -> None:
    client = _get_minio_client()
    bucket = CONF.storage.minio_bucket

    def _upload() -> None:
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
        client.fput_object(
            bucket,
            object_name,
            file_path.as_posix(),
            content_type=content_type,
        )

    try:
        await to_thread.run_sync(_upload)
    except Exception as exc:
        raise BusiException(f"MinIO 文件上传失败: {exc}") from exc


async def download_file(object_name: str, file_path: Path) -> None:
    client = _get_minio_client()
    bucket = CONF.storage.minio_bucket
    file_path.parent.mkdir(parents=True, exist_ok=True)

    def _download() -> None:
        client.fget_object(bucket, object_name, file_path.as_posix())

    try:
        await to_thread.run_sync(_download)
    except Exception as exc:
        raise BusiException(f"MinIO 文件下载失败: {exc}") from exc


__all__ = (
    "bucket_usage_bytes",
    "download_file",
    "ensure_bucket",
    "health_check",
    "upload_file",
)
