"""プロバイダ層の録画と再生（session15/cassette.py のコピー。録り直しの案内文だけ変えた）。

カセットの1行が、上流への呼び出し1回：{"call": "stream", "fingerprint": ..., "request": {...}, "events": [...]}
失敗（ProviderError）も1件のイベントとして録り、再生では同じ位置で投げ直す。上流の request-id は録らない。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Iterable
from dataclasses import asdict
from pathlib import Path

from .providers import (ChatRequest, ChatResult, Done, LLMProvider, ProviderError, StreamEvent, TextDelta,
                        ToolCallDelta, ToolCallDone, ToolCallStart, Usage)

EVENT_TYPES = {cls.__name__: cls for cls in (TextDelta, ToolCallStart, ToolCallDelta, ToolCallDone)}


class CassetteMismatch(AssertionError):
    """再生した要求が録画と違う。"""


def request_json(req: ChatRequest) -> dict:
    return asdict(req)


def fingerprint(req: ChatRequest) -> str:
    raw = json.dumps(request_json(req), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def event_to_json(item: StreamEvent | ProviderError) -> dict:
    if isinstance(item, ProviderError):
        return {"type": "ProviderError", "kind": item.kind, "provider": item.provider,
                "status_code": item.status_code, "retry_after": item.retry_after}
    return {"type": type(item).__name__, **asdict(item)}


def event_from_json(d: dict) -> StreamEvent | ProviderError:
    d = dict(d)
    kind = d.pop("type")
    if kind == "ProviderError":
        return ProviderError(d.pop("kind"), **d)
    if kind == "Done":
        return Done(d["stop_reason"], Usage(**d["usage"]))
    return EVENT_TYPES[kind](**d)


def stream_entry(req: ChatRequest, items: Iterable[StreamEvent | ProviderError]) -> dict:
    return {"call": "stream", "fingerprint": fingerprint(req), "request": request_json(req),
            "events": [event_to_json(x) for x in items]}


def save_cassette(path: Path, entries: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n" for e in entries]
    path.write_text("".join(lines), encoding="utf-8")


def load_cassette(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def diff_keys(recorded: dict, actual: dict) -> str:
    keys = sorted(set(recorded) | set(actual))
    return "、".join(k for k in keys if recorded.get(k) != actual.get(k)) or "なし"


class RecordingProvider:
    """本物のプロバイダを包み、stream() で流れたものをそのまま貯める（録画）。"""

    def __init__(self, inner: LLMProvider) -> None:
        self.inner = inner
        self.name = inner.name
        self.entries: list[dict] = []

    async def complete(self, req: ChatRequest) -> ChatResult:
        raise NotImplementedError("この復習の録画は stream() だけです")

    async def stream(self, req: ChatRequest) -> AsyncIterator[StreamEvent]:
        items: list[StreamEvent | ProviderError] = []
        try:
            async for ev in self.inner.stream(req):
                items.append(ev)
                yield ev
        except ProviderError as e:
            items.append(e)
            raise
        finally:
            self.entries.append(stream_entry(req, items))

    def save(self, path: Path) -> None:
        save_cassette(path, self.entries)


class ReplayProvider:
    """カセットを録った順に再生する。上流にも mockllm にも接続しない。"""

    name = "replay"

    def __init__(self, entries: Iterable[dict]) -> None:
        self._entries = list(entries)
        self.used = 0

    @classmethod
    def load(cls, path: Path) -> ReplayProvider:
        return cls(load_cassette(path))

    def _next(self, req: ChatRequest, call: str) -> dict:
        n = self.used + 1
        if self.used >= len(self._entries):
            raise CassetteMismatch(f"録画は {len(self._entries)} 件しかありません（{n} 件目の要求が来ました）")
        rec = self._entries[self.used]
        if rec["call"] != call:
            raise CassetteMismatch(f"{n} 件目の呼び出しの種類が違います（録画 {rec['call']}・要求 {call}）")
        if rec["fingerprint"] != fingerprint(req):
            raise CassetteMismatch(
                f"{n} 件目の要求が録画と違います（違う項目：{diff_keys(rec['request'], request_json(req))}）。"
                "意図した変更なら record_fallback() で録り直してください")
        self.used += 1
        return rec

    async def complete(self, req: ChatRequest) -> ChatResult:
        raise NotImplementedError("この復習の再生は stream() だけです")

    async def stream(self, req: ChatRequest) -> AsyncIterator[StreamEvent]:
        rec = self._next(req, "stream")
        for d in rec["events"]:
            item = event_from_json(d)
            if isinstance(item, ProviderError):
                raise item
            yield item

    def assert_all_used(self) -> None:
        if self.used != len(self._entries):
            raise CassetteMismatch(f"録画 {len(self._entries)} 件のうち {self.used} 件しか使われていません")
