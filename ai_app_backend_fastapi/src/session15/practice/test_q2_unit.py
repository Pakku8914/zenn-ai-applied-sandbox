"""前半・練習問題2の解答：Fake の単体テストを2つ足す（上流の 400 と、max_tokens で止まった応答）。"""

from __future__ import annotations

from ..providers import FakeProvider, ProviderError, Usage, fake_script
from ..store import MemoryStore
from ..testkit import chat_once


async def test_bad_request_is_502_without_retry_after(memory_store: MemoryStore) -> None:
    fake = FakeProvider([ProviderError("bad_request", provider="fake", status_code=400)])
    run = await chat_once(fake, memory_store)
    assert (run.status, run.body["error"]["type"]) == (502, "upstream_error")
    assert "retry-after" not in run.headers  # 待っても直らない失敗に、待ち時間は付けない
    assert len(fake.requests) == 1  # 上流は1回だけ呼ばれた（アプリは再試行していない）
    assert memory_store.turns == []


async def test_max_tokens_is_passed_through(memory_store: MemoryStore) -> None:
    fake = FakeProvider(fake_script("鶏むね肉を", usage=Usage(34, 3), stop_reason="max_tokens"))
    run = await chat_once(fake, memory_store)
    assert run.shape() == "start → delta → usage → done"
    assert run.data_of("done") == [{"stop_reason": "max_tokens"}]
    assert [t.answer for t in memory_store.turns] == ["鶏むね肉を"]  # 途中で切れた回答も、完了した往復として残る
