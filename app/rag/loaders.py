from __future__ import annotations

from pathlib import Path
from typing import Any

import docx2txt
from pypdf import PdfReader

from app.core.common.exception import BusiException


def _load_text(path: Path) -> list[dict[str, Any]]:
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise BusiException("文件内容不合法") from exc
    return [
        {
            "content": content,
            "metadata": {"source": path.as_posix()},
        }
    ]


def _load_pdf(path: Path) -> list[dict[str, Any]]:
    try:
        reader = PdfReader(path.as_posix())
    except Exception as exc:
        raise BusiException("文件内容不合法") from exc
    docs = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            content = page.extract_text() or ""
        except Exception as exc:
            raise BusiException("文件内容不合法") from exc
        if not content.strip():
            continue
        docs.append(
            {
                "content": content,
                "metadata": {
                    "source": path.as_posix(),
                    "page": index,
                },
                "page": index,
            }
        )
    return docs


def _load_docx(path: Path) -> list[dict[str, Any]]:
    try:
        content = docx2txt.process(path.as_posix()) or ""
    except Exception as exc:
        raise BusiException("文件内容不合法") from exc
    return [
        {
            "content": content,
            "metadata": {"source": path.as_posix()},
        }
    ]


def load_document(document: dict[str, Any]) -> list[dict[str, Any]]:
    path = Path(document["object_path"])
    if not path.exists():
        raise BusiException("文档文件不存在")

    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".markdown"}:
        return _load_text(path)
    if suffix == ".pdf":
        return _load_pdf(path)
    if suffix == ".docx":
        return _load_docx(path)

    raise BusiException("不支持的文档解析类型")


__all__ = ("load_document",)
