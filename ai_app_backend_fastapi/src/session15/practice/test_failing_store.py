"""前半・練習問題4の解答：保存に失敗する保存先を差し込み、done を送らずに error で終えることを確かめる。"""

from __future__ import annotations

import json

from kondate.clock import FixedClock

from ..errors import MESSAGES
from ..providers import FakeProvider, Usage, fake_script
from ..store import MemoryStore, Turn
from ..testkit import FAKE_ANSWER, chat_once


class FailingStore(MemoryStore):
    """save_turn() が必ず失敗する保存先（DB が落ちた状況の代わり）。"""

    async def save_turn(self, turn: Turn) -> None:
        raise RuntimeError("DB に接続できません（host=postgres）")


async def test_save_failure_ends_with_error_not_done(clock: FixedClock) -> None:
    store = FailingStore(clock)
    fake = FakeProvider(fake_script(FAKE_ANSWER, usage=Usage(34, 20)))
    run = await chat_once(fake, store, stop_at_terminal=False)
    assert run.shape() == "start → delta×4 → usage → error"  # 保存できなかったので done は送らない
    err = run.data_of("error")[0]
    assert (err["type"], err["message"]) == ("internal_error", MESSAGES["internal_error"])
    assert err["request_id"] == run.headers["x-request-id"]
    assert "postgres" not in json.dumps(err, ensure_ascii=False)  # 例外の文（接続先など）は外へ出さない
    assert store.turns == []
