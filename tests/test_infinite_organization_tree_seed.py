from __future__ import annotations

import pytest

from tests.performance.seed_infinite_organization_tree import (
    CHILDREN_PER_LEVEL,
    EXPECTED_NODE_COUNT,
    MAX_DEPTH,
    ROOT_NAME,
    TENANT_CODE,
    chain_code,
    validate_existing_count,
)


def test_infinite_tree_seed_has_confirmed_scale_and_identity() -> None:
    assert TENANT_CODE == "infinite-tree-demo"
    assert ROOT_NAME == "无极树演示节点"
    assert MAX_DEPTH == 10
    assert CHILDREN_PER_LEVEL == 100_000
    assert EXPECTED_NODE_COUNT == 1_000_001


def test_infinite_tree_chain_codes_are_stable_and_unique() -> None:
    codes = [chain_code(depth) for depth in range(1, MAX_DEPTH + 1)]

    assert len(codes) == len(set(codes)) == MAX_DEPTH
    assert codes[0] == "infinite-tree-demo-l01-000000"
    assert codes[-1] == "infinite-tree-demo-l10-000000"


def test_infinite_tree_seed_rejects_partial_data() -> None:
    validate_existing_count(0)
    validate_existing_count(EXPECTED_NODE_COUNT)

    with pytest.raises(RuntimeError, match="--reset"):
        validate_existing_count(EXPECTED_NODE_COUNT - 1)
