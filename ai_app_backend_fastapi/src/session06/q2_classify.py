"""練習問題2：SDK の生の例外を「開始前／途中の error／途中切断／その他」に分ける。

    docker compose exec api python -m src.session06.q2_classify
"""

from __future__ import annotations

import asyncio
from typing import Literal

import anthropic
import httpx2

from .faults import FAULTS, raw_fault

Kind = Literal["before_start", "mid_error", "mid_disconnect", "other"]


def classify(exc: BaseException) -> Kind:
    # 1. 途中切断：anthropic の例外階層の外にある。APIError で受けると素通りする
    if isinstance(exc, httpx2.RemoteProtocolError):
        return "mid_disconnect"
    # 2. ステータス付きの例外：200 なら「200 で始まったストリームの途中の error イベント」
    if isinstance(exc, anthropic.APIStatusError):
        return "mid_error" if exc.status_code == 200 else "before_start"
    # 3. 応答が来る前に接続できなかった・時間切れ（APITimeoutError は APIConnectionError の派生）
    if isinstance(exc, anthropic.APIConnectionError):
        return "before_start"
    return "other"


async def main() -> None:
    for fault in FAULTS:
        r = await raw_fault(fault)
        print(f"{fault}: {r.label} → {classify(r.error)}")
    print(f"RuntimeError: {classify(RuntimeError('x'))}")


if __name__ == "__main__":
    asyncio.run(main())
