from __future__ import annotations

from typing import Any

from app.core.common import utils as common_utils
from app.core.common.exception import BusiException
from app.db import conversation as conversation_db
from app.db import conversation_message as conversation_message_db
from app.db import knowledge_base as knowledge_base_db
from app.db import message_citation as message_citation_db
from app.db.api import check_db_connected
from app.db.base import DB
from app.schemas.conversation import ConversationDto, ConversationMessageDto, MessageCitationDto

STATUS_ACTIVE = "active"
STATUS_ARCHIVED = "archived"
STATUS_DELETED = "deleted"
ALLOWED_STATUSES = {STATUS_ACTIVE, STATUS_ARCHIVED, STATUS_DELETED}
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_SYSTEM = "system"
ALLOWED_ROLES = {ROLE_USER, ROLE_ASSISTANT, ROLE_SYSTEM}
MAX_TITLE_LENGTH = 255
MAX_SOURCE_NAME_LENGTH = 512


def validate(dto: ConversationDto, is_create: bool = False) -> None:
    if dto is None:
        raise BusiException("会话参数不能为空")

    if is_create:
        if not dto.kb_id:
            raise BusiException("kb_id 不能为空")
        if not dto.user_id:
            raise BusiException("user_id 不能为空")

    if dto.title is not None and len(dto.title) > MAX_TITLE_LENGTH:
        raise BusiException("title 不能超过 255 个字符")
    if dto.status is not None and dto.status not in ALLOWED_STATUSES:
        raise BusiException("status 不合法")


def validate_message(dto: ConversationMessageDto, is_create: bool = False) -> None:
    if dto is None:
        raise BusiException("消息参数不能为空")

    if is_create:
        if not dto.conversation_id:
            raise BusiException("conversation_id 不能为空")
        if not dto.role:
            raise BusiException("role 不能为空")
        if not dto.content:
            raise BusiException("content 不能为空")

    if dto.role is not None and dto.role not in ALLOWED_ROLES:
        raise BusiException("role 不合法")
    if dto.content is not None and not dto.content.strip():
        raise BusiException("content 不能为空")


def validate_citation(dto: MessageCitationDto, is_create: bool = False) -> None:
    if dto is None:
        raise BusiException("引用参数不能为空")

    if is_create:
        if not dto.message_id:
            raise BusiException("message_id 不能为空")
        if not dto.kb_id:
            raise BusiException("kb_id 不能为空")
        if not dto.document_id:
            raise BusiException("document_id 不能为空")
        if not dto.chunk_id:
            raise BusiException("chunk_id 不能为空")
        if not dto.source_name:
            raise BusiException("source_name 不能为空")
        if not dto.snippet:
            raise BusiException("snippet 不能为空")
        if dto.rank is None:
            raise BusiException("rank 不能为空")

    if dto.source_name is not None and len(dto.source_name) > MAX_SOURCE_NAME_LENGTH:
        raise BusiException("source_name 不能超过 512 个字符")
    if dto.snippet is not None and not dto.snippet.strip():
        raise BusiException("snippet 不能为空")
    if dto.rank is not None and dto.rank <= 0:
        raise BusiException("rank 必须大于 0")


@check_db_connected
async def add(dto: ConversationDto) -> Any:
    rd = None

    validate(dto, is_create=True)
    values = common_utils.clear_field_nv(dto)
    values.setdefault("title", "")
    values.setdefault("status", STATUS_ACTIVE)

    db = DB.get()
    async with db.transaction():
        knowledge_base = await knowledge_base_db.get(db, id=dto.kb_id)
        if knowledge_base is None:
            raise BusiException("知识库不存在", status_code=404)

        conversation_id = await conversation_db.insert_(db, **values)
        rd = await conversation_db.get(db, id=conversation_id)
    if rd is None:
        raise BusiException("会话创建失败")
    return rd


@check_db_connected
async def modify(id: int, dto: ConversationDto) -> Any:
    rd = None

    if not id:
        raise BusiException("conversation_id 不能为空")
    validate(dto)

    values = common_utils.clear_field_nv(dto)
    if not values:
        raise BusiException("修改内容不能为空")

    values["updated_at"] = common_utils.utc_now()
    db = DB.get()
    async with db.transaction():
        old = await conversation_db.get(db, id=id)
        if old is None:
            raise BusiException("会话不存在", status_code=404)

        await conversation_db.update_(db, values, id=id)
        rd = await conversation_db.get(db, id=id)
    return rd


@check_db_connected
async def remove(id: int) -> Any:
    rd = None

    if not id:
        raise BusiException("conversation_id 不能为空")

    db = DB.get()
    async with db.transaction():
        old = await conversation_db.get(db, id=id)
        if old is None:
            raise BusiException("会话不存在", status_code=404)

        await conversation_db.update_(
            db,
            {
                "status": STATUS_DELETED,
                "updated_at": common_utils.utc_now(),
            },
            id=id,
        )
        rd = await conversation_db.get(db, id=id)
    return rd


@check_db_connected
async def get(id: int) -> dict[str, Any]:
    if not id:
        raise BusiException("conversation_id 不能为空")

    row = await conversation_db.get(DB.get(), id=id)
    if row is None:
        raise BusiException("会话不存在", status_code=404)
    return row


@check_db_connected
async def list(
    kb_id: int | None = None,
    user_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    if status is not None and status not in ALLOWED_STATUSES:
        raise BusiException("status 不合法")

    filters: dict[str, Any] = {"kb_id": kb_id, "user_id": user_id}
    if status is None:
        filters["status__ne"] = STATUS_DELETED
    else:
        filters["status"] = status
    return await conversation_db.list(DB.get(), **filters)


@check_db_connected
async def add_message(conversation_id: int, dto: ConversationMessageDto) -> Any:
    rd = None

    if not conversation_id:
        raise BusiException("conversation_id 不能为空")
    dto.conversation_id = conversation_id
    validate_message(dto, is_create=True)

    values = common_utils.clear_field_nv(dto)
    values.setdefault("metadata", {})

    db = DB.get()
    async with db.transaction():
        conversation = await conversation_db.get(db, id=conversation_id)
        if conversation is None:
            raise BusiException("会话不存在", status_code=404)

        values["kb_id"] = conversation["kb_id"]
        values["user_id"] = conversation["user_id"]
        message_id = await conversation_message_db.insert_(db, **values)
        rd = await conversation_message_db.get(db, id=message_id)
    if rd is None:
        raise BusiException("消息创建失败")
    return rd


@check_db_connected
async def modify_message(id: int, dto: ConversationMessageDto) -> Any:
    rd = None

    if not id:
        raise BusiException("message_id 不能为空")
    validate_message(dto)

    values = common_utils.clear_field_nv(dto)
    if not values:
        raise BusiException("修改内容不能为空")

    db = DB.get()
    async with db.transaction():
        old = await conversation_message_db.get(db, id=id)
        if old is None:
            raise BusiException("消息不存在", status_code=404)

        await conversation_message_db.update_(db, values, id=id)
        rd = await conversation_message_db.get(db, id=id)
    return rd


@check_db_connected
async def remove_message(id: int) -> Any:
    if not id:
        raise BusiException("message_id 不能为空")

    db = DB.get()
    async with db.transaction():
        old = await conversation_message_db.get(db, id=id)
        if old is None:
            raise BusiException("消息不存在", status_code=404)

        await message_citation_db.delete_(db, message_id=id)
        await conversation_message_db.delete_(db, id=id)
    return old


@check_db_connected
async def get_message(id: int) -> dict[str, Any]:
    if not id:
        raise BusiException("message_id 不能为空")

    row = await conversation_message_db.get(DB.get(), id=id)
    if row is None:
        raise BusiException("消息不存在", status_code=404)
    return row


@check_db_connected
async def list_messages(conversation_id: int) -> list[dict[str, Any]]:
    if not conversation_id:
        raise BusiException("conversation_id 不能为空")

    return await conversation_message_db.list(DB.get(), conversation_id=conversation_id)


@check_db_connected
async def add_citation(message_id: int, dto: MessageCitationDto) -> Any:
    rd = None

    if not message_id:
        raise BusiException("message_id 不能为空")
    dto.message_id = message_id
    validate_citation(dto, is_create=True)

    values = common_utils.clear_field_nv(dto)

    db = DB.get()
    async with db.transaction():
        message = await conversation_message_db.get(db, id=message_id)
        if message is None:
            raise BusiException("消息不存在", status_code=404)
        if message["kb_id"] != dto.kb_id:
            raise BusiException("引用与消息不匹配")

        citation_id = await message_citation_db.insert_(db, **values)
        rd = await message_citation_db.get(db, id=citation_id)
    if rd is None:
        raise BusiException("引用创建失败")
    return rd


@check_db_connected
async def modify_citation(id: int, dto: MessageCitationDto) -> Any:
    rd = None

    if not id:
        raise BusiException("citation_id 不能为空")
    validate_citation(dto)

    values = common_utils.clear_field_nv(dto)
    if not values:
        raise BusiException("修改内容不能为空")

    db = DB.get()
    async with db.transaction():
        old = await message_citation_db.get(db, id=id)
        if old is None:
            raise BusiException("引用不存在", status_code=404)

        await message_citation_db.update_(db, values, id=id)
        rd = await message_citation_db.get(db, id=id)
    return rd


@check_db_connected
async def remove_citation(id: int) -> Any:
    if not id:
        raise BusiException("citation_id 不能为空")

    db = DB.get()
    async with db.transaction():
        old = await message_citation_db.get(db, id=id)
        if old is None:
            raise BusiException("引用不存在", status_code=404)

        await message_citation_db.delete_(db, id=id)
    return old


@check_db_connected
async def get_citation(id: int) -> dict[str, Any]:
    if not id:
        raise BusiException("citation_id 不能为空")

    row = await message_citation_db.get(DB.get(), id=id)
    if row is None:
        raise BusiException("引用不存在", status_code=404)
    return row


@check_db_connected
async def list_citations(message_id: int) -> list[dict[str, Any]]:
    if not message_id:
        raise BusiException("message_id 不能为空")

    return await message_citation_db.list(DB.get(), message_id=message_id)


__all__ = (
    "validate",
    "validate_message",
    "validate_citation",
    "add",
    "modify",
    "remove",
    "get",
    "list",
    "add_message",
    "modify_message",
    "remove_message",
    "get_message",
    "list_messages",
    "add_citation",
    "modify_citation",
    "remove_citation",
    "get_citation",
    "list_citations",
)
