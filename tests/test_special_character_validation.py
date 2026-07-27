import unittest

from app.core.common.exception import BusiException
from app.core.common.validation import (
    validate_free_text,
    validate_identifier,
    validate_mainland_mobile,
    validate_text,
)
from app.core.services.evaluation import _validate_text_fields
from app.core.services.organization import validate as validate_organization
from app.core.services.tenant import validate as validate_tenant
from app.core.services.user import validate as validate_user
from app.schemas.evaluation import EvaluationTaskRequest
from app.schemas.organization import OrganizationDto
from app.schemas.tenant import TenantDto
from app.schemas.user import UserDto


class SpecialCharacterValidationTest(unittest.TestCase):
    def assertRejected(self, callback):
        with self.assertRaises(BusiException):
            callback()

    def test_identifier_accepts_chinese_and_model_punctuation(self):
        validate_identifier("医疗-Embedding_v2.1", "模型", required=True)

    def test_identifier_rejects_path_and_whitespace_characters(self):
        self.assertRejected(lambda: validate_identifier("model/name", "模型"))
        self.assertRejected(lambda: validate_identifier("model name", "模型"))

    def test_text_rejects_control_zero_width_and_bidi_characters(self):
        for value in ("名称\x00", "名称\u200b", "名称\u202e"):
            self.assertRejected(lambda value=value: validate_text(value, "名称"))

    def test_free_text_allows_normal_punctuation_and_newlines(self):
        validate_free_text("请用中文回答。\n允许使用：括号、引号、/ 和 ?。", "提示词")

    def test_name_rejects_path_characters_and_parent_traversal(self):
        self.assertRejected(lambda: validate_text("知识库/内部", "名称", forbid_path=True))
        self.assertRejected(lambda: validate_text("知识库..备份", "名称", forbid_path=True))

    def test_required_and_length_rules_are_enforced(self):
        self.assertRejected(lambda: validate_text("  ", "名称", required=True))
        self.assertRejected(lambda: validate_text("abcd", "名称", max_length=3))

    def test_evaluation_text_fields_use_the_same_rules(self):
        payload = EvaluationTaskRequest(name="评测\u200b", kb_id=1)
        self.assertRejected(lambda: _validate_text_fields(payload))

        valid = EvaluationTaskRequest(
            name="仓储系统评测",
            kb_id=1,
            business_description="允许括号（和换行）。\n",
            questions_instruction="请避免重复问题。",
        )
        _validate_text_fields(valid)

    def test_platform_crud_services_reject_invisible_text(self):
        self.assertRejected(
            lambda: validate_user(UserDto(username="admin\u200b"), creating=True)
        )
        self.assertRejected(
            lambda: validate_tenant(TenantDto(code="tenant_ok", name="租户\u202e"), creating=True)
        )
        self.assertRejected(
            lambda: validate_organization(
                OrganizationDto(tenant_id=1, code="org_ok", name="组织\u0000"),
                creating=True,
            )
        )

    def test_mainland_mobile_is_exactly_eleven_digits(self):
        validate_mainland_mobile("13800138000")
        self.assertRejected(lambda: validate_mainland_mobile("+8613800138000"))
        self.assertRejected(lambda: validate_mainland_mobile("1380013800"))


if __name__ == "__main__":
    unittest.main()
