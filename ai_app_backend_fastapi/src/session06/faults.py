"""上流の失敗を SDK の生の例外のまま観察する（差し替え層を通さない）。

    docker compose exec api python -m src.session06.faults
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import anthropic

from kondate.settings import get_settings

PROMPT = "冷蔵庫に鶏むね肉とキャベツがある。20分で作れるものは？"
FAULTS = ["429", "529", "sse-error", "disconnect"]


@dataclass
class RawOutcome:
    fault: str
    stage: str  # create（ストリームを開く前に失敗）/ stream（反復の途中で失敗）
    error: BaseException
    deltas: int  # 失敗までに受け取った text_delta の数

    @property
    def label(self) -> str:
        return f"{type(self.error).__module__.split('.')[0]}.{type(self.error).__name__}"

    @property
    def status(self) -> int | None:
        return getattr(self.error, "status_code", None)


async def raw_fault(fault: str) -> RawOutcome:
    s = get_settings()
    client = anthropic.AsyncAnthropic(base_url=s.mockllm_url, api_key="mock-key", max_retries=0,
                                      default_headers={"x-mock-fault": fault})
    stage, deltas = "create", 0
    try:
        stream = await client.messages.create(model=s.llm_model, max_tokens=1024, stream=True,
                                              messages=[{"role": "user", "content": PROMPT}])
        stage = "stream"
        async with stream:
            async for ev in stream:
                if ev.type == "content_block_delta":
                    deltas += 1
    except Exception as e:  # 観察が目的なので、何でも受け止めて種類を記録する
        return RawOutcome(fault, stage, e, deltas)
    finally:
        await client.close()
    raise AssertionError(f"{fault}: 例外が出ませんでした")


async def main() -> None:
    print(f"{'fault':<11}{'stage':<8}{'例外':<29}{'status':<8}{'delta':<7}anthropic.APIError か")
    for fault in FAULTS:
        r = await raw_fault(fault)
        print(f"{r.fault:<11}{r.stage:<8}{r.label:<29}{str(r.status):<8}{r.deltas:<7}"
              f"{isinstance(r.error, anthropic.APIError)}")


if __name__ == "__main__":
    asyncio.run(main())
