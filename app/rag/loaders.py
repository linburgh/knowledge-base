from __future__ import annotations

from pathlib import Path
from typing import Any

import docx2txt
from pypdf import PdfReader

from app.core.common.exception import BusiException


def _load_text(path: Path) -> list[dict[str, Any]]:
    return [
        {
            "content": path.read_text(encoding="utf-8"),
            "metadata": {"source": path.as_posix()},
        }
    ]


def _load_pdf(path: Path) -> list[dict[str, Any]]:
    reader = PdfReader(path.as_posix())
    docs = []
    for index, page in enumerate(reader.pages, start=1):
        content = page.extract_text() or ""
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
    content = docx2txt.process(path.as_posix()) or ""
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
