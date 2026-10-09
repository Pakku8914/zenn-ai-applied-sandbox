"""前半・練習問題5の解答：complete()（ストリーミングでない呼び出し）も録画・再生できるようにする。

カセットの1行：{"call": "complete", "fingerprint", "request", "result": {...}} か、失敗なら "error": {...}
"""

from __future__ import annotations

from dataclasses import asdict

from ..cassette import RecordingProvider, ReplayProvider, event_from_json, event_to_json, fingerprint, request_json
from ..providers import ChatRequest, ChatResult, ProviderError, ToolCall, Usage


def result_to_json(r: ChatResult) -> dict:
    # request_id（上流の ID）は実行ごとに変わるので録らない
    return {"text": r.text, "tool_calls": [asdict(c) for c in r.tool_calls], "stop_reason": r.stop_reason,
            "usage": asdict(r.usage)}


def complete_entry(req: ChatRequest, **outcome: dict) -> dict:
    return {"call": "complete", "fingerprint": fingerprint(req), "request": request_json(req), **outcome}


class RecordingProviderQ5(RecordingProvider):
    async def complete(self, req: ChatRequest) -> ChatResult:
        try:
            result = await self.inner.complete(req)
        except ProviderError as e:
            self.entries.append(complete_entry(req, error=event_to_json(e)))
            raise
        self.entries.append(complete_entry(req, result=result_to_json(result)))
        return result


class ReplayProviderQ5(ReplayProvider):
    async def complete(self, req: ChatRequest) -> ChatResult:
        rec = self._next(req, "complete")
        if "error" in rec:
            raise event_from_json(rec["error"])  # type: ignore[misc]
        d = rec["result"]
        return ChatResult(d["text"], [ToolCall(**c) for c in d["tool_calls"]], d["stop_reason"],
                          Usage(**d["usage"]), request_id=f"req_replay_{self.used:06d}")
