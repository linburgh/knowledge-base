from __future__ import annotations

from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.common import utils as common_utils


def split_documents(
    documents: list[dict[str, Any]],
    chunk_size: int,
    chunk_overlap: int,
) -> list[dict[str, Any]]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        add_start_index=True,
    )

    chunks = []
    chunk_index = 0
    for document in documents:
        content = document.get("content") or ""
        if not content.strip():
            continue

        metadata = dict(document.get("metadata") or {})
        split_texts = splitter.create_documents([content], metadatas=[metadata])
        for split_doc in split_texts:
            chunk_content = split_doc.page_content
            chunk_metadata = dict(split_doc.metadata or {})
            chunks.append(
                {
                    "chunk_index": chunk_index,
                    "content": chunk_content,
                    "content_hash": common_utils.hash_text(chunk_content),
                    "page": chunk_metadata.get("page") or document.get("page"),
                    "section": chunk_metadata.get("section"),
                    "start_index": chunk_metadata.get("start_index"),
                    "token_count": len(chunk_content),
                    "metadata": chunk_metadata,
                }
            )
            chunk_index += 1
    return chunks


__all__ = ("split_documents",)
