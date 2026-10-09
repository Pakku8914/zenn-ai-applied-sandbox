"""mockllm からカセット（JSONL）を録る。録画は mockllm からだけ行う（実 API の応答は録らない）。

    docker compose exec api python -m src.session15.record

要求はアプリと同じ build_chat() で作る（指紋がアプリの要求と一致するように）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from .app import ChatIn, build_chat
from .cassette import RecordingProvider
from .providers import ProviderError
from .testkit import PROMPT, mock_provider

ROOT = Path(__file__).resolve().parents[2]
CASSETTE_DIR = Path(__file__).resolve().parent / "tests" / "cassettes"

# カセットの名前 → mockllm に付ける障害注入ヘッダ（None は正常）
CASES: dict[str, dict[str, str] | None] = {
    "chat_ok": None,
    "chat_sse_error": {"x-mock-fault": "sse-error"},
}


async def record_case(name: str, headers: dict[str, str] | None, out_dir: Path) -> Path:
    async with mock_provider(headers) as inner:
        recorder = RecordingProvider(inner)
        try:
            async for _ in recorder.stream(build_chat(ChatIn(message=PROMPT))):
                pass
        except ProviderError:
            pass  # 失敗も録画の一部（再生で同じ位置から投げ直す）
    path = out_dir / f"{name}.jsonl"
    recorder.save(path)
    return path


async def record_all(out_dir: Path = CASSETTE_DIR) -> list[Path]:
    return [await record_case(name, headers, out_dir) for name, headers in CASES.items()]


def main() -> None:
    for path in asyncio.run(record_all()):
        print(f"録画しました: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
