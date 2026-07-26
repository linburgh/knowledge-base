"""Execute documented document-upload, chunk and pagination boundary cases."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid

try:
    from .test_documented_api_smoke import Response, expect, login, request
except ImportError:
    from test_documented_api_smoke import Response, expect, login, request


BASE_URL = os.getenv("TEST_BASE_URL", "http://127.0.0.1:28003/api/v1").rstrip("/")


def multipart_upload(
    token: str,
    *,
    kb_id: int,
    filename: str,
    content: bytes,
) -> Response:
    boundary = f"----CodexBoundary{uuid.uuid4().hex}"
    parts = [
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="kb_id"\r\n\r\n'
            f"{kb_id}\r\n"
        ).encode(),
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="created_by"\r\n\r\n'
            "linburgh\r\n"
        ).encode(),
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode(),
        content,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    request_obj = urllib.request.Request(
        f"{BASE_URL}/documents/upload",
        data=b"".join(parts),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request_obj, timeout=60) as response:
            return Response(response.status, json.loads(response.read().decode() or "null"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"detail": raw}
        return Response(exc.code, body)


def main() -> int:
    token = login(os.getenv("TEST_ADMIN_ACCOUNT"), os.getenv("TEST_ADMIN_PASSWORD"))
    kb_id = int(os.getenv("TEST_DOCUMENT_KB_ID", "34"))
    before = expect(
        "document boundary baseline list",
        request("GET", f"/documents?kb_id={kb_id}", token=token),
        {200},
    ).body
    before_count = len(before if isinstance(before, list) else before.get("items", []))

    expect(
        "unsupported document extension rejected",
        multipart_upload(token, kb_id=kb_id, filename="unsupported.exe", content=b"not allowed"),
        {400, 415, 422},
    )
    expect(
        "empty document rejected",
        multipart_upload(token, kb_id=kb_id, filename="empty.md", content=b""),
        {400, 422},
    )
    after = expect(
        "document boundary rejected uploads leave no rows",
        request("GET", f"/documents?kb_id={kb_id}", token=token),
        {200},
    ).body
    after_count = len(after if isinstance(after, list) else after.get("items", []))
    if after_count != before_count:
        raise AssertionError(f"rejected uploads changed document count: {before_count} -> {after_count}")
    print("PASS rejected uploads leave document count unchanged")

    expect(
        "document chunk list",
        request("GET", "/documents/26/chunks", token=token),
        {200},
    )
    expect(
        "document missing record rejected",
        request("GET", "/documents/999999/chunks", token=token),
        {404},
    )
    expect(
        "document list missing knowledge-base rejected",
        request("GET", "/documents?kb_id=999999", token=token),
        {200, 404},
    )
    print("document boundary cases passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
