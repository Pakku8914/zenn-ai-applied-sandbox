"""後半・練習問題4の解答：障害注入ヘッダの組み合わせで、異常系の結合テストを足す。"""

from __future__ import annotations

from uuid import uuid4

import pytest

from ..store import MemoryStore
from ..testkit import chat_via_mock, mock_stats

pytestmark = pytest.mark.usefixtures("mock")


@pytest.fixture
def fault_key(request: pytest.FixtureRequest) -> str:
    """障害の回数を数える単位。テストの名前と乱数で、ほかのテスト・前回の実行と混ざらないようにする。"""
    return f"s15-{request.node.name}-{uuid4().hex[:8]}"


async def test_disconnect_after_five_deltas(memory_store: MemoryStore) -> None:
    run = await chat_via_mock({"x-mock-fault": "disconnect", "x-mock-fault-after": "5"}, memory_store)
    assert run.shape() == "start → delta×5 → error"
    assert run.data_of("error")[0]["type"] == "upstream_unavailable"
    assert memory_store.turns == []


async def test_error_type_after_200_does_not_change_the_type(memory_store: MemoryStore) -> None:
    headers = {"x-mock-fault": "sse-error", "x-mock-error-type": "rate_limit_error"}
    run = await chat_via_mock(headers, memory_store)
    assert run.shape() == "start → delta×2 → error"
    assert run.data_of("error")[0]["type"] == "upstream_error"  # 200 のあとの error は、種別にかかわらず stream_error


async def test_529_twice_then_ok(fault_key: str, memory_store: MemoryStore) -> None:
    headers = {"x-mock-fault": "529", "x-mock-fault-times": "2", "x-mock-fault-key": fault_key}
    statuses = [(await chat_via_mock(headers, memory_store)).status for _ in range(3)]
    assert statuses == [503, 503, 200]
    slot = (await mock_stats())["faults"][fault_key]
    assert (slot["calls"], slot["injected"]) == (3, 2)
    assert len(memory_store.turns) == 1
