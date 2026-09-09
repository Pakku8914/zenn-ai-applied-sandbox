"""Amazon Bedrock 互換のモックエンドポイント（FastAPI）。

boto3 の `endpoint_url` をこのサーバーに向けるだけで、
`bedrock` / `bedrock-runtime` / `bedrock-agent-runtime` の主要 API が
**実 AWS と同じリクエスト・レスポンス形状** で動きます。課金は一切発生しません。

    import boto3
    rt = boto3.client("bedrock-runtime", endpoint_url="http://bedrock-mock:8080",
                      region_name="us-east-1")

実装している API:

| クライアント | API | パス |
| :--- | :--- | :--- |
| bedrock | ListFoundationModels | GET /foundation-models |
| bedrock-runtime | InvokeModel | POST /model/{modelId}/invoke |
| bedrock-runtime | InvokeModelWithResponseStream | POST /model/{modelId}/invoke-with-response-stream |
| bedrock-runtime | Converse | POST /model/{modelId}/converse |
| bedrock-runtime | ConverseStream | POST /model/{modelId}/converse-stream |
| bedrock-runtime | ApplyGuardrail | POST /guardrail/{id}/version/{version}/apply |
| bedrock-agent-runtime | Retrieve | POST /knowledgebases/{kbId}/retrieve |
| bedrock-agent-runtime | RetrieveAndGenerate | POST /retrieveAndGenerate |
| bedrock-agent-runtime | Rerank | POST /rerank |

加えて、モック専用の制御 API（`/_mock/*`）で障害注入とトークン集計を扱います。
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from typing import Any, Iterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from . import catalog, corpus, eventstream, generation, guardrails
from .behavior import STATE

app = FastAPI(title="bedrock-mock", version="1.0.0")

EVENT_STREAM_CONTENT_TYPE = "application/vnd.amazon.eventstream"


# ---------------------------------------------------------------------------
# 共通ユーティリティ
# ---------------------------------------------------------------------------


def _request_id() -> str:
    return str(uuid.uuid4())


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    """botocore が例外クラスに変換できる形のエラーを返す。

    REST-JSON プロトコルでは `x-amzn-errortype` ヘッダで例外名を伝える。
    これが無いと boto3 側は一律 `ClientError` になり、
    `except client.exceptions.ThrottlingException` が機能しない。
    """
    return JSONResponse(
        status_code=status,
        content={"message": message},
        headers={"x-amzn-errortype": error_type, "x-amzn-requestid": _request_id()},
    )


def _precheck(model_id: str) -> JSONResponse | None:
    """障害注入の設定を評価する。失敗させる場合はエラーレスポンスを返す。"""
    behavior = STATE.behavior
    if behavior.latency_ms:
        time.sleep(behavior.latency_ms / 1000)
    if behavior.force_validation_error:
        return _error(
            400,
            "ValidationException",
            "モックの force_validation_error が有効です。",
        )
    if behavior.unavailable_model and behavior.unavailable_model == model_id:
        return _error(
            503,
            "ServiceUnavailableException",
            f"{model_id} は現在このリージョンで利用できません。",
        )
    if STATE.take_throttle():
        return _error(
            429,
            "ThrottlingException",
            "Too many requests, please wait before trying again.",
        )
    return None


def _resolve_or_error(model_id: str):
    try:
        return catalog.resolve(model_id), None
    except KeyError:
        return None, _error(
            400,
            "ValidationException",
            f"The provided model identifier is invalid: {model_id}",
        )


def _family(model_id: str) -> str:
    base = model_id
    for prefix in catalog.CROSS_REGION_PREFIXES:
        if base.startswith(prefix):
            base = base[len(prefix) :]
    if base.startswith("anthropic."):
        return "anthropic"
    if base.startswith("amazon.titan-embed"):
        return "titan-embed"
    if base.startswith("amazon.nova"):
        return "nova"
    if base.startswith("meta."):
        return "meta"
    return "unknown"


def _text_of_content(content: Any) -> str:
    """Converse / ネイティブ双方の content 表現からテキストだけを取り出す。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    if isinstance(content, dict):
        content = [content]
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            if "text" in block and isinstance(block["text"], str):
                parts.append(block["text"])
            elif "toolResult" in block:
                for inner in block["toolResult"].get("content", []):
                    if "text" in inner:
                        parts.append(str(inner["text"]))
                    elif "json" in inner:
                        parts.append(json.dumps(inner["json"], ensure_ascii=False))
    return "\n".join(parts)


def _cache_accounting(model_id: str, blocks: list[dict], total_tokens: int):
    """cachePoint があればキャッシュ読み書きトークンを分離する。"""
    prefix_parts: list[str] = []
    cached_prefix: list[str] = []
    for block in blocks:
        if isinstance(block, dict) and "cachePoint" in block:
            cached_prefix = list(prefix_parts)
            continue
        prefix_parts.append(_text_of_content(block))
    if not cached_prefix:
        return total_tokens, 0, 0
    prefix_text = "\n".join(cached_prefix)
    prefix_tokens = generation.count_tokens(prefix_text)
    key = hashlib.sha256(f"{model_id}\x1f{prefix_text}".encode()).hexdigest()
    read, write = STATE.cache_lookup(key, prefix_tokens)
    return max(total_tokens - prefix_tokens, 0), read, write


# ---------------------------------------------------------------------------
# bedrock（コントロールプレーン）
# ---------------------------------------------------------------------------


@app.get("/foundation-models")
def list_foundation_models() -> JSONResponse:
    summaries = []
    for spec in catalog.MODELS.values():
        summaries.append(
            {
                "modelArn": f"arn:aws:bedrock:us-east-1::foundation-model/{spec.model_id}",
                "modelId": spec.model_id,
                "modelName": spec.model_id.split(".", 1)[-1],
                "providerName": spec.provider,
                "inputModalities": list(spec.modality),
                "outputModalities": ["EMBEDDING"]
                if spec.embedding_dimensions
                else ["TEXT"],
                "responseStreamingSupported": spec.supports_streaming,
                "customizationsSupported": [],
                "inferenceTypesSupported": ["ON_DEMAND"],
                "modelLifecycle": {"status": "ACTIVE"},
            }
        )
    return JSONResponse({"modelSummaries": summaries})


# ---------------------------------------------------------------------------
# bedrock-runtime: InvokeModel
# ---------------------------------------------------------------------------


@app.post("/model/{model_id}/invoke")
async def invoke_model(model_id: str, request: Request):
    if (err := _precheck(model_id)) is not None:
        return err
    resolved, err = _resolve_or_error(model_id)
    if err is not None:
        return err
    spec, geo = resolved

    raw = await request.body()
    try:
        body = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        return _error(400, "ValidationException", "リクエストボディが JSON ではありません。")

    family = _family(model_id)
    behavior = STATE.behavior

    if family == "titan-embed":
        text = body.get("inputText", "")
        dims = int(body.get("dimensions", 1024))
        if dims not in spec.embedding_dimensions:
            return _error(
                400,
                "ValidationException",
                f"dimensions は {list(spec.embedding_dimensions)} のいずれかです。",
            )
        vector = generation.embed(
            text, dimensions=dims, normalize=bool(body.get("normalize", True))
        )
        input_tokens = generation.count_tokens(text)
        STATE.usage.record(spec.model_id, input_tokens, 0)
        payload = {"embedding": vector, "inputTextTokenCount": input_tokens}
        return _blob_response(payload, spec.model_id, input_tokens, 0, geo)

    if family == "anthropic":
        max_tokens = int(body.get("max_tokens", 512))
        system = body.get("system", "") or ""
        if isinstance(system, list):
            system = _text_of_content(system)
        prompt = "\n".join(
            _text_of_content(m.get("content")) for m in body.get("messages", [])
        )
        temperature = float(body.get("temperature", 0.0))
    elif family == "nova":
        cfg = body.get("inferenceConfig") or {}
        max_tokens = int(cfg.get("maxTokens", 512))
        temperature = float(cfg.get("temperature", 0.0))
        system = _text_of_content(body.get("system"))
        prompt = "\n".join(
            _text_of_content(m.get("content")) for m in body.get("messages", [])
        )
    elif family == "meta":
        max_tokens = int(body.get("max_gen_len", 512))
        temperature = float(body.get("temperature", 0.0))
        system = ""
        prompt = body.get("prompt", "")
    else:
        return _error(
            400, "ValidationException", f"モックが未対応のモデルです: {model_id}"
        )

    if behavior.force_max_tokens:
        max_tokens = 8

    text, stop_reason = generation.generate_text(
        model_id=spec.model_id,
        prompt=prompt,
        system=system,
        temperature=temperature,
        max_tokens=max_tokens,
        hallucinate=behavior.hallucinate_without_context,
    )
    input_tokens = generation.count_tokens(system + prompt)
    output_tokens = generation.count_tokens(text)
    STATE.usage.record(spec.model_id, input_tokens, output_tokens)

    if family == "anthropic":
        payload = {
            "id": f"msg_mock_{_request_id()[:12]}",
            "type": "message",
            "role": "assistant",
            "model": spec.model_id,
            "content": [{"type": "text", "text": text}],
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        }
    elif family == "nova":
        payload = {
            "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
            "stopReason": stop_reason,
            "usage": {
                "inputTokens": input_tokens,
                "outputTokens": output_tokens,
                "totalTokens": input_tokens + output_tokens,
            },
        }
    else:  # meta
        payload = {
            "generation": text,
            "prompt_token_count": input_tokens,
            "generation_token_count": output_tokens,
            "stop_reason": "stop" if stop_reason == "end_turn" else "length",
        }
    return _blob_response(payload, spec.model_id, input_tokens, output_tokens, geo)


def _blob_response(
    payload: dict, model_id: str, input_tokens: int, output_tokens: int, geo: str | None
) -> JSONResponse:
    """InvokeModel のレスポンス（本体は blob）。実 Bedrock と同じ計測ヘッダも付ける。"""
    headers = {
        "x-amzn-requestid": _request_id(),
        "x-amzn-bedrock-input-token-count": str(input_tokens),
        "x-amzn-bedrock-output-token-count": str(output_tokens),
        "x-amzn-bedrock-invocation-latency": str(20 + output_tokens),
        # モック独自。クロスリージョン推論でどの地理に解決されたかを可視化する
        "x-mock-resolved-model": model_id,
        "x-mock-geo-prefix": geo or "-",
    }
    return JSONResponse(payload, headers=headers)


# ---------------------------------------------------------------------------
# bedrock-runtime: Converse
# ---------------------------------------------------------------------------


def _converse_core(model_id: str, body: dict) -> tuple[dict, dict] | JSONResponse:
    resolved, err = _resolve_or_error(model_id)
    if err is not None:
        return err
    spec, geo = resolved
    if not spec.supports_converse:
        return _error(
            400,
            "ValidationException",
            f"{spec.model_id} は Converse API をサポートしていません（埋め込みモデルです）。",
        )

    cfg = body.get("inferenceConfig") or {}
    max_tokens = int(cfg.get("maxTokens", 512))
    temperature = float(cfg.get("temperature", 0.0))
    if STATE.behavior.force_max_tokens:
        max_tokens = 8

    system_blocks = body.get("system") or []
    messages = body.get("messages") or []
    system = _text_of_content(system_blocks)
    prompt = "\n".join(_text_of_content(m.get("content")) for m in messages)

    all_blocks: list[dict] = list(system_blocks)
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            all_blocks.extend(b for b in content if isinstance(b, dict))

    total_input = generation.count_tokens(system + prompt)
    input_tokens, cache_read, cache_write = _cache_accounting(
        spec.model_id, all_blocks, total_input
    )

    tool_config = body.get("toolConfig") or {}
    tools = tool_config.get("tools") or []
    already: set[str] = set()
    for message in messages:
        for block in message.get("content") or []:
            if isinstance(block, dict) and "toolResult" in block:
                already.add(block["toolResult"].get("toolUseId", "").split("::")[0])
            if isinstance(block, dict) and "toolUse" in block:
                already.add(block["toolUse"].get("name", ""))

    if tools and not spec.supports_tool_use:
        return _error(
            400,
            "ValidationException",
            f"{spec.model_id} は toolConfig をサポートしていません。",
        )

    tool_call = (
        generation.choose_tool(tools=tools, prompt=prompt, already_called=already)
        if tools
        else None
    )

    if tool_call:
        content_blocks = [
            {
                "toolUse": {
                    "toolUseId": f"{tool_call['name']}::{_request_id()[:8]}",
                    "name": tool_call["name"],
                    "input": tool_call["input"],
                }
            }
        ]
        text = ""
        stop_reason = "tool_use"
    else:
        text, stop_reason = generation.generate_text(
            model_id=spec.model_id,
            prompt=prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            hallucinate=STATE.behavior.hallucinate_without_context,
        )
        content_blocks = [{"text": text}]

    output_tokens = generation.count_tokens(text) or 12
    STATE.usage.record(
        spec.model_id, input_tokens, output_tokens, cache_read, cache_write
    )

    usage = {
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "totalTokens": input_tokens + output_tokens,
        "cacheReadInputTokens": cache_read,
        "cacheWriteInputTokens": cache_write,
    }
    response = {
        "output": {"message": {"role": "assistant", "content": content_blocks}},
        "stopReason": stop_reason,
        "usage": usage,
        "metrics": {"latencyMs": 20 + output_tokens},
    }

    guardrail_cfg = body.get("guardrailConfig") or {}
    if guardrail_cfg.get("guardrailIdentifier") and text:
        policy = guardrails.DEFAULT_POLICIES.get(
            guardrail_cfg["guardrailIdentifier"],
            guardrails.DEFAULT_POLICIES["demo-guardrail"],
        )
        verdict = guardrails.evaluate(policy=policy, text=prompt, source="INPUT")
        if verdict["action"] == "GUARDRAIL_INTERVENED":
            response["output"]["message"]["content"] = [
                {"text": verdict["outputs"][0]["text"]}
            ]
            response["stopReason"] = "guardrail_intervened"
        if guardrail_cfg.get("trace") == "enabled":
            response["trace"] = {"guardrail": {"inputAssessment": {
                guardrail_cfg["guardrailIdentifier"]: verdict["assessments"][0]
            }}}

    return response, {"x-mock-geo-prefix": geo or "-"}


@app.post("/model/{model_id}/converse")
async def converse(model_id: str, request: Request):
    if (err := _precheck(model_id)) is not None:
        return err
    body = json.loads(await request.body() or b"{}")
    result = _converse_core(model_id, body)
    if isinstance(result, JSONResponse):
        return result
    response, headers = result
    return JSONResponse(response, headers={**headers, "x-amzn-requestid": _request_id()})


# ---------------------------------------------------------------------------
# ストリーミング
# ---------------------------------------------------------------------------


def _chunks(text: str, size: int = 12) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


@app.post("/model/{model_id}/converse-stream")
async def converse_stream(model_id: str, request: Request):
    if (err := _precheck(model_id)) is not None:
        return err
    body = json.loads(await request.body() or b"{}")
    result = _converse_core(model_id, body)
    if isinstance(result, JSONResponse):
        return result
    response, _ = result

    def gen() -> Iterator[bytes]:
        yield eventstream.event("messageStart", json.dumps({"role": "assistant"}).encode())
        blocks = response["output"]["message"]["content"]
        for index, block in enumerate(blocks):
            if "text" in block:
                for piece in _chunks(block["text"]):
                    yield eventstream.event(
                        "contentBlockDelta",
                        json.dumps(
                            {"contentBlockIndex": index, "delta": {"text": piece}},
                            ensure_ascii=False,
                        ).encode(),
                    )
            elif "toolUse" in block:
                tool = block["toolUse"]
                yield eventstream.event(
                    "contentBlockStart",
                    json.dumps(
                        {
                            "contentBlockIndex": index,
                            "start": {
                                "toolUse": {
                                    "toolUseId": tool["toolUseId"],
                                    "name": tool["name"],
                                }
                            },
                        }
                    ).encode(),
                )
                yield eventstream.event(
                    "contentBlockDelta",
                    json.dumps(
                        {
                            "contentBlockIndex": index,
                            "delta": {
                                "toolUse": {
                                    "input": json.dumps(
                                        tool["input"], ensure_ascii=False
                                    )
                                }
                            },
                        }
                    ).encode(),
                )
            yield eventstream.event(
                "contentBlockStop", json.dumps({"contentBlockIndex": index}).encode()
            )
        yield eventstream.event(
            "messageStop", json.dumps({"stopReason": response["stopReason"]}).encode()
        )
        yield eventstream.event(
            "metadata",
            json.dumps(
                {"usage": response["usage"], "metrics": response["metrics"]}
            ).encode(),
        )

    return StreamingResponse(gen(), media_type=EVENT_STREAM_CONTENT_TYPE)


@app.post("/model/{model_id}/invoke-with-response-stream")
async def invoke_model_with_response_stream(model_id: str, request: Request):
    if (err := _precheck(model_id)) is not None:
        return err
    resolved, err = _resolve_or_error(model_id)
    if err is not None:
        return err
    spec, _ = resolved
    body = json.loads(await request.body() or b"{}")
    family = _family(model_id)

    if family == "anthropic":
        prompt = "\n".join(
            _text_of_content(m.get("content")) for m in body.get("messages", [])
        )
        max_tokens = int(body.get("max_tokens", 512))
        system = _text_of_content(body.get("system"))
    elif family == "nova":
        prompt = "\n".join(
            _text_of_content(m.get("content")) for m in body.get("messages", [])
        )
        cfg = body.get("inferenceConfig") or {}
        max_tokens = int(cfg.get("maxTokens", 512))
        system = _text_of_content(body.get("system"))
    else:
        return _error(
            400,
            "ValidationException",
            f"モックのストリーミングは anthropic / nova 系のみ対応しています: {model_id}",
        )

    text, stop_reason = generation.generate_text(
        model_id=spec.model_id,
        prompt=prompt,
        system=system,
        max_tokens=max_tokens,
        hallucinate=STATE.behavior.hallucinate_without_context,
    )
    input_tokens = generation.count_tokens(system + prompt)
    output_tokens = generation.count_tokens(text)
    STATE.usage.record(spec.model_id, input_tokens, output_tokens)

    def wrap(payload: dict) -> bytes:
        # InvokeModelWithResponseStream の chunk は「base64 の bytes フィールド」に
        # モデル固有の JSON を入れる二重構造になっている
        inner = json.dumps(payload, ensure_ascii=False).encode()
        return eventstream.event(
            "chunk",
            json.dumps({"bytes": base64.b64encode(inner).decode()}).encode(),
        )

    def gen() -> Iterator[bytes]:
        if family == "anthropic":
            yield wrap(
                {
                    "type": "message_start",
                    "message": {
                        "role": "assistant",
                        "model": spec.model_id,
                        "usage": {"input_tokens": input_tokens, "output_tokens": 0},
                    },
                }
            )
            yield wrap({"type": "content_block_start", "index": 0,
                        "content_block": {"type": "text", "text": ""}})
            for piece in _chunks(text):
                yield wrap(
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": piece},
                    }
                )
            yield wrap({"type": "content_block_stop", "index": 0})
            yield wrap(
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": stop_reason},
                    "usage": {"output_tokens": output_tokens},
                }
            )
            yield wrap({"type": "message_stop"})
        else:
            for index, piece in enumerate(_chunks(text)):
                yield wrap({"contentBlockDelta": {"delta": {"text": piece},
                                                  "contentBlockIndex": index}})
            yield wrap({"messageStop": {"stopReason": stop_reason}})
            yield wrap(
                {
                    "metadata": {
                        "usage": {
                            "inputTokens": input_tokens,
                            "outputTokens": output_tokens,
                            "totalTokens": input_tokens + output_tokens,
                        }
                    }
                }
            )

    return StreamingResponse(gen(), media_type=EVENT_STREAM_CONTENT_TYPE)


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------


@app.post("/guardrail/{guardrail_id}/version/{version}/apply")
async def apply_guardrail(guardrail_id: str, version: str, request: Request):
    if (err := _precheck(guardrail_id)) is not None:
        return err
    body = json.loads(await request.body() or b"{}")
    policy = guardrails.DEFAULT_POLICIES.get(guardrail_id)
    if policy is None:
        return _error(
            404,
            "ResourceNotFoundException",
            f"Guardrail {guardrail_id} が見つかりません（モックの既定は demo-guardrail）。",
        )

    source = body.get("source", "INPUT")
    texts: list[str] = []
    grounding_sources: list[str] = []
    query = ""
    for block in body.get("content", []):
        text_block = block.get("text") or {}
        qualifiers = text_block.get("qualifiers") or []
        value = text_block.get("text", "")
        if "grounding_source" in qualifiers:
            grounding_sources.append(value)
        elif "query" in qualifiers:
            query = value
        else:
            texts.append(value)

    verdict = guardrails.evaluate(
        policy=policy,
        text="\n".join(texts),
        source=source,
        grounding_sources=grounding_sources,
        query=query,
    )
    return JSONResponse(verdict, headers={"x-amzn-requestid": _request_id()})


# ---------------------------------------------------------------------------
# Knowledge Bases（bedrock-agent-runtime）
# ---------------------------------------------------------------------------


@app.post("/knowledgebases/{kb_id}/retrieve")
async def retrieve(kb_id: str, request: Request):
    if (err := _precheck(kb_id)) is not None:
        return err
    body = json.loads(await request.body() or b"{}")
    query = (body.get("retrievalQuery") or {}).get("text", "")
    vector_cfg = (body.get("retrievalConfiguration") or {}).get(
        "vectorSearchConfiguration"
    ) or {}
    results = corpus.search(
        query,
        top_k=int(vector_cfg.get("numberOfResults", 3)),
        search_type=vector_cfg.get("overrideSearchType", "SEMANTIC"),
        metadata_filter=vector_cfg.get("filter"),
    )
    return JSONResponse({"retrievalResults": results})


@app.post("/retrieveAndGenerate")
async def retrieve_and_generate(request: Request):
    if (err := _precheck("retrieveAndGenerate")) is not None:
        return err
    body = json.loads(await request.body() or b"{}")
    query = (body.get("input") or {}).get("text", "")
    cfg = (body.get("retrieveAndGenerateConfiguration") or {}).get(
        "knowledgeBaseConfiguration"
    ) or {}
    model_arn = cfg.get("modelArn", "amazon.nova-lite-v1:0")
    model_id = model_arn.rsplit("/", 1)[-1]
    top_k = int(
        ((cfg.get("retrievalConfiguration") or {}).get("vectorSearchConfiguration") or {})
        .get("numberOfResults", 3)
    )
    results = corpus.search(query, top_k=top_k, search_type="HYBRID")
    context = "\n".join(r["content"]["text"] for r in results)
    prompt = f"{query}\n<context>\n{context}\n</context>"
    text, _ = generation.generate_text(
        model_id=model_id if model_id in catalog.MODELS else "amazon.nova-lite-v1:0",
        prompt=prompt,
        max_tokens=512,
    )
    STATE.usage.record(
        model_id if model_id in catalog.MODELS else "amazon.nova-lite-v1:0",
        generation.count_tokens(prompt),
        generation.count_tokens(text),
    )
    return JSONResponse(
        {
            "sessionId": body.get("sessionId") or _request_id(),
            "output": {"text": text},
            "citations": [
                {
                    "generatedResponsePart": {
                        "textResponsePart": {"text": text, "span": {"start": 0, "end": max(len(text) - 1, 0)}}
                    },
                    "retrievedReferences": [
                        {
                            "content": {"text": r["content"]["text"]},
                            "location": r["location"],
                            "metadata": r["metadata"],
                        }
                        for r in results
                    ],
                }
            ],
        }
    )


@app.post("/rerank")
async def rerank(request: Request):
    if (err := _precheck("rerank")) is not None:
        return err
    body = json.loads(await request.body() or b"{}")
    queries = body.get("queries") or []
    query_text = ""
    if queries:
        query_text = (queries[0].get("textQuery") or {}).get("text", "")
    query_vec = generation.embed(query_text, dimensions=1024)

    scored = []
    for index, source in enumerate(body.get("sources") or []):
        doc = (source.get("inlineDocumentSource") or {}).get("textDocument") or {}
        text = doc.get("text", "")
        score = generation.cosine(query_vec, generation.embed(text, dimensions=1024))
        # リランカは「元の順位と違う順位」を返さないと学習にならないので、
        # 語の一致に強く反応させる（実 reranker のクロスエンコーダの代替）
        boost = sum(1 for t in query_text.split() if t and t in text) * 0.1
        scored.append({"index": index, "relevanceScore": round(score + boost, 6)})
    scored.sort(key=lambda r: -r["relevanceScore"])
    top_n = int((body.get("rerankingConfiguration") or {})
                .get("bedrockRerankingConfiguration", {})
                .get("numberOfResults", len(scored)))
    return JSONResponse({"results": scored[:top_n]})


# ---------------------------------------------------------------------------
# モック専用の制御 API
# ---------------------------------------------------------------------------


@app.get("/_mock/health")
def health() -> dict:
    return {"status": "ok", "models": len(catalog.MODELS), "documents": len(corpus.documents())}


@app.get("/_mock/catalog")
def mock_catalog() -> dict:
    return {"models": catalog.summary_rows()}


@app.get("/_mock/behavior")
def get_behavior() -> dict:
    return STATE.behavior.to_api()


@app.post("/_mock/behavior")
async def set_behavior(request: Request) -> dict:
    patch = json.loads(await request.body() or b"{}")
    return STATE.update_behavior(patch).to_api()


@app.get("/_mock/usage")
def get_usage() -> dict:
    return STATE.usage.to_api()


@app.post("/_mock/reset")
def reset() -> dict:
    STATE.reset()
    return {"status": "reset"}
