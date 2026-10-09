"""mockllm：Anthropic Messages API / OpenAI Chat Completions API 互換のモックサーバ。

仕様は README.md（と series-contract.md）が正。ここを変えたら両方を直す。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from . import tokens as tk
from .scenarios import RequestFeatures, Resolved, ScenarioBook, ScenarioError

VERSION = "1.0.0"
FIXTURES_DIR = Path(os.environ.get("MOCKLLM_FIXTURES_DIR", Path(__file__).resolve().parent.parent / "fixtures"))
DEFAULT_TTFT_MS = float(os.environ.get("MOCKLLM_TTFT_MS", "0"))
DEFAULT_TPS = float(os.environ.get("MOCKLLM_TPS", "0"))
TEXT_CHUNK_CHARS = int(os.environ.get("MOCKLLM_TEXT_CHUNK_CHARS", "6"))
JSON_CHUNK_CHARS = int(os.environ.get("MOCKLLM_JSON_CHUNK_CHARS", "16"))
MODEL_RULES = os.environ.get("MOCKLLM_MODEL_RULES", "on") == "on"
REQUIRE_API_KEY = os.environ.get("MOCKLLM_REQUIRE_API_KEY", "on") == "on"
MAX_BODY_BYTES = 32 * 1024 * 1024
OPENAI_CREATED = 1790899200  # 2026-10-02T00:00:00Z（決定的にするため固定）

STRICT_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5")
SAMPLING_REJECT_MODELS = ("claude-opus-5-5",)

app = FastAPI(title="mockllm", version=VERSION)
book = ScenarioBook(FIXTURES_DIR)


# ---------------------------------------------------------------- 統計

class Stats:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.seq = 0
        self.by_path: Counter[str] = Counter()
        self.by_status: Counter[str] = Counter()
        self.by_scenario: Counter[str] = Counter()
        self.fault_calls: dict[str, dict] = {}
        self.requests: deque[dict] = deque(maxlen=200)
        self.cache: dict[str, float] = {}

    def next_seq(self) -> int:
        with self.lock:
            self.seq += 1
            return self.seq

    def record(self, entry: dict) -> None:
        with self.lock:
            self.by_path[entry["path"]] += 1
            self.by_status[str(entry["status"])] += 1
            if entry.get("scenario"):
                self.by_scenario[entry["scenario"]] += 1
            self.requests.append(entry)

    def fault_hit(self, key: str, fault: str, times: int | None, retry_count: str | None) -> bool:
        with self.lock:
            slot = self.fault_calls.setdefault(key, {"fault": fault, "calls": 0, "injected": 0, "retry_counts": []})
            slot["calls"] += 1
            slot["retry_counts"].append(retry_count)
            inject = times is None or slot["calls"] <= times
            if inject:
                slot["injected"] += 1
            return inject

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "total": self.seq,
                "by_path": dict(self.by_path),
                "by_status": dict(self.by_status),
                "by_scenario": dict(self.by_scenario),
                "faults": {k: dict(v) for k, v in self.fault_calls.items()},
                "requests": list(self.requests),
            }


stats = Stats()


# ---------------------------------------------------------------- 共通

@dataclass
class Fault:
    kind: str | None
    key: str
    times: int | None
    after: int
    retry_after: str
    error_type: str
    ttft_s: float
    tps: float


def parse_fault(request: Request, body_hash: str) -> Fault:
    h = request.headers
    kind = h.get("x-mock-fault")
    if kind is not None:
        kind = kind.strip().lower()
        if kind not in {"429", "529", "500", "disconnect", "sse-error"}:
            raise ValueError(f"x-mock-fault '{kind}' は未対応です（429 / 529 / 500 / disconnect / sse-error）")
    times = h.get("x-mock-fault-times")
    return Fault(
        kind=kind,
        key=h.get("x-mock-fault-key") or f"{kind}:{request.url.path}:{body_hash[:16]}",
        times=int(times) if times is not None else None,
        after=int(h.get("x-mock-fault-after", "2")),
        retry_after=h.get("x-mock-retry-after", "1"),
        error_type=h.get("x-mock-error-type", "overloaded_error"),
        ttft_s=float(h.get("x-mock-ttft-ms", DEFAULT_TTFT_MS)) / 1000,
        tps=float(h.get("x-mock-tps", DEFAULT_TPS)),
    )


def chunk_text(text: str, size: int) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)] or [""]


class SSEStream(StreamingResponse):
    """イベント列を SSE で送る。障害注入（途中切断・error イベント）と遅延に対応する。

    events の各要素は {"event": str | None, "data": dict | str, "delta_tokens": int | None}。
    delta_tokens が None でないものを「コンテンツの差分」として数え、TTFT・TPS・切断位置の基準にする。
    """

    def __init__(self, events: list[dict], *, fault: Fault, error_event: dict | None,
                 trailer: str | None, headers: dict[str, str]):
        super().__init__(iter(()), media_type="text/event-stream", headers=headers)
        self.events = events
        self.fault = fault
        self.error_event = error_event
        self.trailer = trailer

    @staticmethod
    def encode(ev: dict) -> bytes:
        data = ev["data"] if isinstance(ev["data"], str) else json.dumps(ev["data"], ensure_ascii=False)
        prefix = f"event: {ev['event']}\n" if ev.get("event") else ""
        return f"{prefix}data: {data}\n\n".encode("utf-8")

    async def __call__(self, scope, receive, send) -> None:  # type: ignore[override]
        await send({"type": "http.response.start", "status": 200, "headers": self.raw_headers})
        deltas = 0
        cut = self.fault.kind in ("disconnect", "sse-error")
        for ev in self.events:
            if ev.get("delta_tokens") is not None:
                if cut and deltas >= self.fault.after:
                    if self.fault.kind == "disconnect":
                        return  # 終端チャンクを送らずに戻る → uvicorn が接続を閉じる
                    await send({"type": "http.response.body", "body": self.encode(self.error_event), "more_body": True})
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
                    return
                if deltas == 0 and self.fault.ttft_s > 0:
                    await asyncio.sleep(self.fault.ttft_s)
                elif deltas > 0 and self.fault.tps > 0:
                    await asyncio.sleep(ev["delta_tokens"] / self.fault.tps)
                deltas += 1
            await send({"type": "http.response.body", "body": self.encode(ev), "more_body": True})
        if self.trailer:
            await send({"type": "http.response.body", "body": self.trailer.encode(), "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})


def base_entry(seq: int, request: Request, stream: bool) -> dict:
    return {
        "seq": seq,
        "path": request.url.path,
        "stream": stream,
        "retry_count": request.headers.get("x-stainless-retry-count"),
        "user_agent": (request.headers.get("user-agent") or "")[:60],
    }


# ---------------------------------------------------------------- Anthropic 互換

def anthropic_error(status: int, etype: str, message: str, request_id: str,
                    extra_headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"type": "error", "error": {"type": etype, "message": message}, "request_id": request_id},
        headers={"request-id": request_id, **(extra_headers or {})},
    )


def _blocks(content) -> list[dict]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return content
    raise tk.InvalidContent("messages[].content は文字列かブロックの配列です")


def validate_anthropic(body: dict) -> str | None:
    if not isinstance(body.get("model"), str) or not body["model"]:
        return "model: Field required"
    mt = body.get("max_tokens")
    if not isinstance(mt, int) or isinstance(mt, bool) or mt < 1:
        return "max_tokens: Field required (整数 1 以上)"
    msgs = body.get("messages")
    if not isinstance(msgs, list) or not msgs:
        return "messages: Field required (1 件以上)"
    for i, m in enumerate(msgs):
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant", "system"):
            return f"messages.{i}.role: 'user' か 'assistant' を指定してください"
    if msgs[0]["role"] != "user":
        return "messages: 最初のメッセージは user ロールにしてください"
    if not MODEL_RULES:
        return None
    model = body["model"]
    if model.startswith(STRICT_MODELS):
        thinking = body.get("thinking") or {}
        if thinking.get("type") == "disabled":
            return f"thinking.type 'disabled' は {model} では使えません（mockllm は実 API の 400 を模倣しています）"
        if (body.get("tool_choice") or {}).get("type") in ("any", "tool"):
            return f"tool_choice の強制（any / tool）は {model} では使えません（mockllm は実 API の 400 を模倣しています）"
        if msgs[-1]["role"] == "assistant":
            return f"assistant メッセージでの prefill は {model} では使えません（mockllm は実 API の 400 を模倣しています）"
    if model.startswith(SAMPLING_REJECT_MODELS):
        for p in ("temperature", "top_p", "top_k"):
            if p in body:
                return f"{p} は {model} では使えません（mockllm は実 API の 400 を模倣しています）"
    return None


def analyze_anthropic(body: dict) -> tuple[RequestFeatures, list[tuple[str, int, dict | None]]]:
    """特徴量と、キャッシュ計算用のセグメント列（正規化 JSON, トークン数, cache_control）を返す。"""
    media = tk.MediaSummary()
    segments: list[tuple[str, int, dict | None]] = []

    def seg(obj: dict, tokens: int) -> None:
        cc = obj.get("cache_control") if isinstance(obj, dict) else None
        clean = {k: v for k, v in obj.items() if k != "cache_control"} if isinstance(obj, dict) else obj
        segments.append((json.dumps(clean, ensure_ascii=False, sort_keys=True), tokens, cc))

    for tool in body.get("tools") or []:
        seg(tool, tk.json_tokens({k: v for k, v in tool.items() if k != "cache_control"}))
    system = body.get("system")
    if isinstance(system, str) and system:
        seg({"type": "text", "text": system}, tk.text_tokens(system))
    elif isinstance(system, list):
        for b in system:
            seg(b, tk.text_tokens(b.get("text", "")))

    messages = body["messages"]
    norm = [(m["role"], _blocks(m.get("content", ""))) for m in messages]
    for role, blocks in norm:
        for j, b in enumerate(blocks):
            seg({"role": role, **b} if j == 0 else b, tk.anthropic_block_tokens(b, media) + (tk.MESSAGE_OVERHEAD if j == 0 else 0))
        if not blocks:
            seg({"role": role}, tk.MESSAGE_OVERHEAD)

    if body.get("cache_control") and segments:
        last = segments[-1]
        segments[-1] = (last[0], last[1], body["cache_control"])

    last_text_idx = -1
    for i, (role, blocks) in enumerate(norm):
        types = {b.get("type") for b in blocks}
        if role == "user" and "text" in types and "tool_result" not in types:
            last_text_idx = i
    last_user_text = ""
    if last_text_idx >= 0:
        last_user_text = "\n".join(b.get("text", "") for b in norm[last_text_idx][1] if b.get("type") == "text")
    after = norm[last_text_idx + 1:] if last_text_idx >= 0 else norm
    step = sum(1 for role, _ in after if role == "assistant")
    last_tool_result = ""
    for role, blocks in after:
        for b in blocks:
            if b.get("type") == "tool_result":
                c = b.get("content", "")
                last_tool_result = c if isinstance(c, str) else "\n".join(x.get("text", "") for x in c if x.get("type") == "text")

    fmt = (body.get("output_config") or {}).get("format") or body.get("output_format")
    schema = fmt.get("schema") if isinstance(fmt, dict) and fmt.get("type") == "json_schema" else None

    features = RequestFeatures(
        model=body["model"],
        last_user_text=last_user_text,
        step=step,
        tool_names={t.get("name") for t in body.get("tools") or [] if t.get("name")},
        image_sizes=media.image_sizes,
        pdf_pages=media.pdf_pages,
        text_documents=media.text_documents,
        output_schema=schema,
        last_tool_result_text=last_tool_result,
    )
    return features, segments


def compute_usage(segments: list[tuple[str, int, dict | None]], *, consult_cache: bool) -> dict:
    total = tk.BASE_OVERHEAD + sum(t for _, t, _ in segments)
    usage = {"input_tokens": total, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    marks = [i for i, (_, _, cc) in enumerate(segments) if cc]
    if not consult_cache or not marks:
        return usage
    k = marks[-1]
    prefix_tokens = tk.BASE_OVERHEAD + sum(t for _, t, _ in segments[:k + 1])
    if prefix_tokens < tk.CACHE_MIN_TOKENS:
        return usage
    digest = hashlib.sha256("\n".join(s for s, _, _ in segments[:k + 1]).encode()).hexdigest()
    ttl = 3600 if (segments[k][2] or {}).get("ttl") == "1h" else 300
    now = time.monotonic()
    with stats.lock:
        hit = stats.cache.get(digest, 0) > now
        stats.cache[digest] = now + ttl
    usage["input_tokens"] = total - prefix_tokens
    usage["cache_read_input_tokens" if hit else "cache_creation_input_tokens"] = prefix_tokens
    return usage


def truncate(content: list[dict], max_tokens: int) -> tuple[list[dict], bool]:
    out: list[dict] = []
    budget = max_tokens
    for block in content:
        cost = tk.output_tokens([block])
        if cost <= budget:
            out.append(block)
            budget -= cost
            continue
        if block["type"] == "text" and budget > 0:
            text = block["text"]
            while text and tk.text_tokens(text) > budget:
                text = text[:-1]
            out.append({"type": "text", "text": text})
        return out, True
    return out, False


def anthropic_events(msg_id: str, model: str, content: list[dict], stop_reason: str, usage: dict, out_tokens: int) -> list[dict]:
    start_usage = {**usage, "output_tokens": 1}
    events = [
        {"event": "message_start", "data": {"type": "message_start", "message": {
            "id": msg_id, "type": "message", "role": "assistant", "model": model, "content": [],
            "stop_reason": None, "stop_sequence": None, "usage": start_usage}}},
        {"event": "ping", "data": {"type": "ping"}},
    ]
    for i, block in enumerate(content):
        if block["type"] == "text":
            events.append({"event": "content_block_start", "data": {"type": "content_block_start", "index": i,
                           "content_block": {"type": "text", "text": ""}}})
            for piece in chunk_text(block["text"], TEXT_CHUNK_CHARS):
                events.append({"event": "content_block_delta", "delta_tokens": tk.text_tokens(piece),
                               "data": {"type": "content_block_delta", "index": i,
                                        "delta": {"type": "text_delta", "text": piece}}})
        else:
            events.append({"event": "content_block_start", "data": {"type": "content_block_start", "index": i,
                           "content_block": {"type": "tool_use", "id": block["id"], "name": block["name"], "input": {}}}})
            raw = json.dumps(block["input"], ensure_ascii=False)
            for piece in chunk_text(raw, JSON_CHUNK_CHARS):
                events.append({"event": "content_block_delta", "delta_tokens": tk.text_tokens(piece),
                               "data": {"type": "content_block_delta", "index": i,
                                        "delta": {"type": "input_json_delta", "partial_json": piece}}})
        events.append({"event": "content_block_stop", "data": {"type": "content_block_stop", "index": i}})
    events.append({"event": "message_delta", "data": {"type": "message_delta",
                   "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                   "usage": {**usage, "output_tokens": out_tokens}}})
    events.append({"event": "message_stop", "data": {"type": "message_stop"}})
    return events


async def read_json(request: Request) -> tuple[dict | None, bytes, str | None]:
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        return None, raw, "request_too_large"
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, raw, f"JSON として解析できません: {e}"
    if not isinstance(body, dict):
        return None, raw, "リクエストボディは JSON オブジェクトにしてください"
    return body, raw, None


def has_anthropic_auth(request: Request) -> bool:
    return bool(request.headers.get("x-api-key") or request.headers.get("authorization"))


@app.post("/v1/messages")
async def messages(request: Request):
    seq = stats.next_seq()
    request_id = f"req_mock_{seq:06d}"
    body, raw, err = await read_json(request)
    stream = bool(body.get("stream")) if body else False
    entry = base_entry(seq, request, stream)

    def fail(status: int, etype: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
        stats.record({**entry, "status": status, "error": etype})
        return anthropic_error(status, etype, message, request_id, headers)

    if err == "request_too_large":
        return fail(413, "request_too_large", "リクエストが 32MB を超えています")
    if err:
        return fail(400, "invalid_request_error", err)
    if REQUIRE_API_KEY and not has_anthropic_auth(request):
        return fail(401, "authentication_error", "x-api-key ヘッダがありません（値は何でもよい）")
    body_hash = hashlib.sha256(raw).hexdigest()
    try:
        fault = parse_fault(request, body_hash)
    except ValueError as e:
        return fail(400, "invalid_request_error", str(e))
    if fault.kind:
        entry["fault"] = fault.kind
        entry["fault_key"] = fault.key
        if stats.fault_hit(fault.key, fault.kind, fault.times, entry["retry_count"]):
            if fault.kind == "429":
                return fail(429, "rate_limit_error", "mockllm: レート制限を模擬しています",
                            {"retry-after": fault.retry_after})
            if fault.kind == "529":
                return fail(529, "overloaded_error", "mockllm: 過負荷（Overloaded）を模擬しています")
            if fault.kind == "500":
                return fail(500, "api_error", "mockllm: 内部エラーを模擬しています")
        else:
            fault.kind = None
            entry["fault"] = None
    invalid = validate_anthropic(body)
    if invalid:
        return fail(400, "invalid_request_error", invalid)
    try:
        features, segments = analyze_anthropic(body)
        resolved: Resolved = book.resolve(features, request.headers.get("x-mock-scenario"))
    except (tk.InvalidContent, ScenarioError) as e:
        return fail(400, "invalid_request_error", str(e))

    content, cut = truncate(resolved.content, body["max_tokens"])
    stop_reason = "max_tokens" if cut else resolved.stop_reason
    usage = compute_usage(segments, consult_cache=True)
    out_tokens = tk.output_tokens(content) if content else 0
    msg_id = "msg_mock_" + body_hash[:24]
    headers = {"request-id": request_id, "x-mock-scenario-resolved": resolved.scenario, "x-mock-step": str(resolved.step)}
    entry.update(status=200, scenario=resolved.scenario, step=resolved.step, stop_reason=stop_reason,
                 input_tokens=usage["input_tokens"], output_tokens=out_tokens,
                 cache_read_input_tokens=usage["cache_read_input_tokens"],
                 cache_creation_input_tokens=usage["cache_creation_input_tokens"])
    stats.record(entry)

    if stream:
        events = anthropic_events(msg_id, body["model"], content, stop_reason, usage, out_tokens)
        error_event = {"event": "error", "data": {"type": "error", "error": {
            "type": fault.error_type, "message": f"mockllm: ストリーム途中の {fault.error_type} を模擬しています"}}}
        return SSEStream(events, fault=fault, error_event=error_event, trailer=None,
                         headers={"cache-control": "no-cache", **headers})

    if fault.kind in ("disconnect", "sse-error"):
        return fail(500, "api_error", f"mockllm: 非ストリーミングでは {fault.kind} を 500 として返します")
    delay = fault.ttft_s + (out_tokens / fault.tps if fault.tps > 0 else 0)
    if delay > 0:
        await asyncio.sleep(delay)
    return JSONResponse(headers=headers, content={
        "id": msg_id, "type": "message", "role": "assistant", "model": body["model"],
        "content": content, "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {**usage, "output_tokens": out_tokens},
    })


@app.post("/v1/messages/count_tokens")
async def count_tokens(request: Request):
    seq = stats.next_seq()
    request_id = f"req_mock_{seq:06d}"
    body, _, err = await read_json(request)
    entry = base_entry(seq, request, False)
    if err or body is None:
        stats.record({**entry, "status": 400})
        return anthropic_error(400, "invalid_request_error", err or "invalid", request_id)
    body.setdefault("max_tokens", 1)
    invalid = validate_anthropic(body)
    if invalid:
        stats.record({**entry, "status": 400})
        return anthropic_error(400, "invalid_request_error", invalid, request_id)
    try:
        _, segments = analyze_anthropic(body)
    except tk.InvalidContent as e:
        stats.record({**entry, "status": 400})
        return anthropic_error(400, "invalid_request_error", str(e), request_id)
    usage = compute_usage(segments, consult_cache=False)
    stats.record({**entry, "status": 200, "input_tokens": usage["input_tokens"]})
    return JSONResponse({"input_tokens": usage["input_tokens"]}, headers={"request-id": request_id})


# ---------------------------------------------------------------- OpenAI 互換

def openai_error(status: int, etype: str, code: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, headers=headers or {},
                        content={"error": {"message": message, "type": etype, "param": None, "code": code}})


def analyze_openai(body: dict) -> tuple[RequestFeatures, int]:
    media = tk.MediaSummary()
    input_tokens = tk.BASE_OVERHEAD + tk.json_tokens(body.get("tools") or []) if body.get("tools") else tk.BASE_OVERHEAD
    msgs = body["messages"]
    last_user = -1
    for i, m in enumerate(msgs):
        content = m.get("content")
        input_tokens += tk.MESSAGE_OVERHEAD
        if isinstance(content, str):
            input_tokens += tk.text_tokens(content)
        elif isinstance(content, list):
            for part in content:
                ptype = part.get("type")
                if ptype == "text":
                    input_tokens += tk.text_tokens(part.get("text", ""))
                elif ptype == "image_url":
                    url = (part.get("image_url") or {}).get("url", "")
                    if url.startswith("data:") and ";base64," in url:
                        mtype, data = url[5:].split(";base64,", 1)
                        w, h = tk.inspect_image(mtype, data)
                        media.image_sizes.append((w, h))
                        input_tokens += tk.image_tokens(w, h)
                    else:
                        media.image_sizes.append(None)
                        input_tokens += tk.IMAGE_UNKNOWN_SIZE_TOKENS
                elif ptype == "file":
                    data_url = (part.get("file") or {}).get("file_data", "")
                    if data_url.startswith("data:application/pdf;base64,"):
                        pages = tk.inspect_pdf(data_url.split(",", 1)[1])
                        media.pdf_pages.append(pages)
                        input_tokens += pages * tk.PDF_TOKENS_PER_PAGE
                    else:
                        media.pdf_pages.append(None)
                        input_tokens += tk.PDF_TOKENS_PER_PAGE
        for call in m.get("tool_calls") or []:
            input_tokens += tk.text_tokens(json.dumps(call, ensure_ascii=False))
        if m.get("role") == "user":
            last_user = i
    text = ""
    if last_user >= 0:
        c = msgs[last_user].get("content")
        text = c if isinstance(c, str) else "\n".join(p.get("text", "") for p in c or [] if p.get("type") == "text")
    after = msgs[last_user + 1:]
    step = sum(1 for m in after if m.get("role") == "assistant")
    last_tool = next((m.get("content") or "" for m in reversed(after) if m.get("role") == "tool"), "")
    if isinstance(last_tool, list):
        last_tool = "\n".join(p.get("text", "") for p in last_tool if p.get("type") == "text")
    rf = body.get("response_format") or {}
    schema = None
    if rf.get("type") == "json_schema":
        schema = (rf.get("json_schema") or {}).get("schema") or {"type": "object"}
    elif rf.get("type") == "json_object":
        schema = {"type": "object"}
    features = RequestFeatures(
        model=body["model"], last_user_text=text, step=step,
        tool_names={(t.get("function") or {}).get("name") for t in body.get("tools") or []},
        image_sizes=media.image_sizes, pdf_pages=media.pdf_pages, output_schema=schema,
        last_tool_result_text=last_tool,
    )
    return features, input_tokens


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    seq = stats.next_seq()
    body, raw, err = await read_json(request)
    stream = bool(body.get("stream")) if body else False
    entry = base_entry(seq, request, stream)

    def fail(status: int, etype: str, code: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
        stats.record({**entry, "status": status, "error": etype})
        return openai_error(status, etype, code, message, headers)

    if err:
        return fail(400, "invalid_request_error", "invalid_json", err)
    if REQUIRE_API_KEY and not request.headers.get("authorization"):
        return fail(401, "invalid_request_error", "invalid_api_key", "Authorization: Bearer ヘッダがありません（値は何でもよい）")
    body_hash = hashlib.sha256(raw).hexdigest()
    try:
        fault = parse_fault(request, body_hash)
    except ValueError as e:
        return fail(400, "invalid_request_error", "invalid_fault", str(e))
    if fault.kind:
        entry["fault"] = fault.kind
        entry["fault_key"] = fault.key
        if stats.fault_hit(fault.key, fault.kind, fault.times, entry["retry_count"]):
            if fault.kind == "429":
                return fail(429, "requests", "rate_limit_exceeded", "mockllm: レート制限を模擬しています",
                            {"retry-after": fault.retry_after})
            if fault.kind in ("529", "500"):
                return fail(int(fault.kind), "server_error", "server_error", "mockllm: サーバエラーを模擬しています")
        else:
            fault.kind = None
            entry["fault"] = None
    if not isinstance(body.get("model"), str) or not isinstance(body.get("messages"), list) or not body["messages"]:
        return fail(400, "invalid_request_error", "missing_required_parameter", "model と messages は必須です")
    try:
        features, input_tokens = analyze_openai(body)
        resolved = book.resolve(features, request.headers.get("x-mock-scenario"))
    except (tk.InvalidContent, ScenarioError) as e:
        return fail(400, "invalid_request_error", "invalid_value", str(e))

    limit = body.get("max_completion_tokens") or body.get("max_tokens")
    content, cut = truncate(resolved.content, limit) if isinstance(limit, int) else (resolved.content, False)
    text = "".join(b["text"] for b in content if b["type"] == "text")
    calls = [{"id": "call_" + b["id"].removeprefix("toolu_mock_"), "type": "function",
              "function": {"name": b["name"], "arguments": json.dumps(b["input"], ensure_ascii=False)}}
             for b in content if b["type"] == "tool_use"]
    finish = "length" if cut else ("tool_calls" if calls else "stop")
    out_tokens = tk.output_tokens(content) if content else 0
    usage = {"prompt_tokens": input_tokens, "completion_tokens": out_tokens, "total_tokens": input_tokens + out_tokens}
    cid = "chatcmpl-mock" + body_hash[:20]
    model = body["model"]
    headers = {"x-request-id": f"req_mock_{seq:06d}", "x-mock-scenario-resolved": resolved.scenario,
               "x-mock-step": str(resolved.step)}
    entry.update(status=200, scenario=resolved.scenario, step=resolved.step, stop_reason=finish,
                 input_tokens=input_tokens, output_tokens=out_tokens)
    stats.record(entry)

    if stream:
        def chunk(delta: dict, finish_reason: str | None = None) -> dict:
            return {"id": cid, "object": "chat.completion.chunk", "created": OPENAI_CREATED, "model": model,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason, "logprobs": None}]}
        events = [{"data": chunk({"role": "assistant", "content": ""})}]
        for piece in (chunk_text(text, TEXT_CHUNK_CHARS) if text else []):
            events.append({"data": chunk({"content": piece}), "delta_tokens": tk.text_tokens(piece)})
        for idx, call in enumerate(calls):
            events.append({"data": chunk({"tool_calls": [{"index": idx, "id": call["id"], "type": "function",
                                                          "function": {"name": call["function"]["name"], "arguments": ""}}]})})
            for piece in chunk_text(call["function"]["arguments"], JSON_CHUNK_CHARS):
                events.append({"data": chunk({"tool_calls": [{"index": idx, "function": {"arguments": piece}}]}),
                               "delta_tokens": tk.text_tokens(piece)})
        events.append({"data": chunk({}, finish)})
        if (body.get("stream_options") or {}).get("include_usage"):
            events.append({"data": {"id": cid, "object": "chat.completion.chunk", "created": OPENAI_CREATED,
                                    "model": model, "choices": [], "usage": usage}})
        error_event = {"data": {"error": {"message": "mockllm: ストリーム途中のエラーを模擬しています",
                                          "type": "server_error", "code": fault.error_type}}}
        return SSEStream(events, fault=fault, error_event=error_event, trailer="data: [DONE]\n\n",
                         headers={"cache-control": "no-cache", **headers})

    if fault.kind in ("disconnect", "sse-error"):
        return fail(500, "server_error", "server_error", f"mockllm: 非ストリーミングでは {fault.kind} を 500 として返します")
    delay = fault.ttft_s + (out_tokens / fault.tps if fault.tps > 0 else 0)
    if delay > 0:
        await asyncio.sleep(delay)
    message: dict = {"role": "assistant", "content": text if text or not calls else None, "refusal": None}
    if calls:
        message["tool_calls"] = calls
    return JSONResponse(headers=headers, content={
        "id": cid, "object": "chat.completion", "created": OPENAI_CREATED, "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish, "logprobs": None}],
        "usage": usage,
    })


# ---------------------------------------------------------------- 管理 API

@app.get("/_mock/health")
async def health():
    return {"status": "ok", "version": VERSION, "scenarios": len(book.scenarios)}


@app.get("/_mock/stats")
async def get_stats():
    return stats.snapshot()


@app.post("/_mock/reset")
async def reset():
    with stats.lock:
        stats.reset()
    return {"status": "reset"}


@app.get("/_mock/scenarios")
async def scenarios():
    return {"default": "default", "scenarios": book.summary()}


@app.post("/_mock/reload")
async def reload_fixtures():
    try:
        book.reload()
    except (ScenarioError, json.JSONDecodeError) as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    return {"status": "reloaded", "scenarios": len(book.scenarios)}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def not_found(path: str):
    hint = ""
    if path in ("messages", "chat/completions"):
        hint = "（base URL に /v1 が付いていない可能性があります。AI SDK の baseURL は http://mockllm:8080/v1）"
    elif path.startswith("v1/v1/"):
        hint = "（/v1 が二重です。Python SDK の base_url は http://mockllm:8080 のように /v1 を付けません）"
    return JSONResponse(status_code=404, content={
        "type": "error", "error": {"type": "not_found_error", "message": f"mockllm: /{path} はありません{hint}"}})
