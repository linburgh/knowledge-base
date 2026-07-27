import unittest

from app.core.common.exception import BusiException
from app.core.services import conversation
from app.schemas.conversation import ConversationDto, ConversationMessageDto, MessageCitationDto


class ConversationTest(unittest.TestCase):
    def test_validate_create_requires_kb_id(self):
        dto = ConversationDto(user_id="user-1")

        with self.assertRaises(BusiException) as context:
            conversation.validate(dto, is_create=True)

        self.assertEqual(context.exception.message, "kb_id 不能为空")

    def test_validate_create_requires_user_id(self):
        dto = ConversationDto(kb_id=1)

        with self.assertRaises(BusiException) as context:
            conversation.validate(dto, is_create=True)

        self.assertEqual(context.exception.message, "user_id 不能为空")

    def test_validate_status(self):
        dto = ConversationDto(kb_id=1, user_id="user-1", status="invalid")

        with self.assertRaises(BusiException) as context:
            conversation.validate(dto, is_create=True)

        self.assertEqual(context.exception.message, "status 不合法")

    def test_validate_title_length(self):
        dto = ConversationDto(kb_id=1, user_id="user-1", title="a" * 256)

        with self.assertRaises(BusiException) as context:
            conversation.validate(dto, is_create=True)

        self.assertEqual(context.exception.message, "title 不能超过 50 个字符")

    def test_validate_message_role(self):
        dto = ConversationMessageDto(
            conversation_id=1,
            role="invalid",
            content="hello",
        )

        with self.assertRaises(BusiException) as context:
            conversation.validate_message(dto, is_create=True)

        self.assertEqual(context.exception.message, "role 不合法")

    def test_validate_message_content(self):
        dto = ConversationMessageDto(
            conversation_id=1,
            role="user",
            content=" ",
        )

        with self.assertRaises(BusiException) as context:
            conversation.validate_message(dto, is_create=True)

        self.assertEqual(context.exception.message, "content 不能为空")

    def test_validate_citation_rank(self):
        dto = MessageCitationDto(
            message_id=1,
            kb_id=1,
            document_id=1,
            chunk_id=1,
            source_name="source.md",
            snippet="snippet",
            rank=0,
        )

        with self.assertRaises(BusiException) as context:
            conversation.validate_citation(dto, is_create=True)

        self.assertEqual(context.exception.message, "rank 必须大于 0")
