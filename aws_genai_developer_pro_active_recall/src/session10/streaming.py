#!/usr/bin/env python3
"""セッション10: ストリーミングで受け取り、体感を数字にする。

    docker compose exec app python src/session10/streaming.py

ConverseStream は「1回の HTTP 応答の中に、イベントを順番に流す」API です。
boto3（botocore）が AWS 独自のバイナリフレームを解いてくれるので、
アプリから見えるのは **キーが1つだけの辞書** が次々に届くイテレータです。
そのキーがイベント名です。

    messageStart → contentBlockDelta（複数）→ contentBlockStop
                 → messageStop（stopReason）→ metadata（usage / metrics）

差分（delta）を順に連結すると、非ストリーミングの Converse が返す本文と
**完全に一致**します。これが「ストリーミングにしても答えは変わらない」ことの証拠です。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session01")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from awskit import clients  # noqa: E402

import poc_probe  # noqa: E402

DEFAULT_MODEL = "amazon.nova-lite-v1:0"
NATIVE_MODEL = "anthropic.claude-3-5-haiku-20241022-v1:0"
MAX_TOKENS = 300


def prompt_text(question: str, source: str | None) -> str:
    """資料を渡す場合は <context> で囲む（セッション1から同じ形）。"""
    return question if source is None else f"{question}\n<context>{source}</context>"


def event_name(event: dict) -> str:
    """イベントは「キーが1つの辞書」。そのキーがイベント名になる。"""
    return next(iter(event))


# ---------------------------------------------------------------------------
# 同期（全文が揃うまで待つ）
# ---------------------------------------------------------------------------


def sync_answer(
    runtime, question: str, source: str | None = None, *, model_id: str = DEFAULT_MODEL
) -> dict:
    """Converse を1回呼ぶ。比較の基準になるので呼び方は下の stream_answer と揃える。"""
    started = time.perf_counter()
    response = runtime.converse(
        modelId=model_id,
        system=[{"text": poc_probe.SYSTEM_PROMPT}],
        messages=[
            {"role": "user", "content": [{"text": prompt_text(question, source)}]}
        ],
        inferenceConfig={"maxTokens": MAX_TOKENS, "temperature": 0.0},
    )
    wall_ms = (time.perf_counter() - started) * 1000
    return {
        "mode": "sync",
        "modelId": model_id,
        "text": response["output"]["message"]["content"][0]["text"],
        "stopReason": response["stopReason"],
        "usage": response["usage"],
        # サービスが申告するレイテンシ。**利用者の体感（wallMs）とは別物**
        "reportedLatencyMs": response["metrics"]["latencyMs"],
        "wallMs": wall_ms,
    }


# ---------------------------------------------------------------------------
# ストリーミング（届いたぶんから出す）
# ---------------------------------------------------------------------------


def stream_answer(
    runtime,
    question: str,
    source: str | None = None,
    *,
    model_id: str = DEFAULT_MODEL,
    on_delta=None,
) -> dict:
    """ConverseStream のイベントを順に処理し、時間を2つに分けて測る。

    測るのは次の2つです。混ぜて1つの「レイテンシ」にすると体感の話ができません。

      firstDeltaMs … 最初の差分が届くまで（＝画面に1文字目を出せるまで）
      totalMs      … metadata まで届いて完了するまで
    """
    started = time.perf_counter()
    stream = runtime.converse_stream(
        modelId=model_id,
        system=[{"text": poc_probe.SYSTEM_PROMPT}],
        messages=[
            {"role": "user", "content": [{"text": prompt_text(question, source)}]}
        ],
        inferenceConfig={"maxTokens": MAX_TOKENS, "temperature": 0.0},
    )

    names: list[str] = []
    deltas: list[str] = []
    first_delta_ms: float | None = None
    last_delta_ms: float | None = None
    stop_reason: str | None = None
    usage: dict | None = None
    reported_latency_ms: int | None = None

    for event in stream["stream"]:
        name = event_name(event)
        names.append(name)
        if name == "contentBlockDelta":
            piece = event["contentBlockDelta"]["delta"].get("text")
            if piece is None:
                # ツール利用の差分（toolUse.input）。本章では扱わない
                continue
            elapsed = (time.perf_counter() - started) * 1000
            if first_delta_ms is None:
                first_delta_ms = elapsed
            last_delta_ms = elapsed
            deltas.append(piece)
            if on_delta is not None:
                on_delta(piece)
        elif name == "messageStop":
            stop_reason = event["messageStop"]["stopReason"]
        elif name == "metadata":
            metadata = event["metadata"]
            usage = metadata["usage"]
            reported_latency_ms = metadata["metrics"]["latencyMs"]

    total_ms = (time.perf_counter() - started) * 1000
    return {
        "mode": "stream",
        "modelId": model_id,
        "text": "".join(deltas),
        "deltas": deltas,
        "eventNames": names,
        "stopReason": stop_reason,
        "usage": usage,
        "reportedLatencyMs": reported_latency_ms,
        "firstDeltaMs": first_delta_ms,
        "lastDeltaMs": last_delta_ms,
        "totalMs": total_ms,
    }


def native_stream(
    runtime, question: str, source: str | None = None, *, model_id: str = NATIVE_MODEL
) -> dict:
    """InvokeModelWithResponseStream（モデル固有の形）で受け取る。

    ConverseStream との違いは**二重構造**です。イベントの中身が
    `chunk.bytes`（ワイヤ上は base64。boto3 が外してくれる）に入っていて、
    その JSON の形はモデル系統ごとに違います。
    Converse 系に寄せると、この分岐がアプリから消えます。
    """
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": MAX_TOKENS,
        "system": poc_probe.SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt_text(question, source)}],
    }
    response = runtime.invoke_model_with_response_stream(
        modelId=model_id, body=json.dumps(body)
    )

    types: list[str] = []
    pieces: list[str] = []
    stop_reason: str | None = None
    for event in response["body"]:
        chunk = json.loads(event["chunk"]["bytes"])
        types.append(chunk["type"])
        if chunk["type"] == "content_block_delta":
            pieces.append(chunk["delta"]["text"])
        elif chunk["type"] == "message_delta":
            stop_reason = chunk["delta"].get("stop_reason")
    return {
        "mode": "native-stream",
        "modelId": model_id,
        "types": types,
        "text": "".join(pieces),
        "stopReason": stop_reason,
    }


# ---------------------------------------------------------------------------
# ブラウザまで届ける（Server-Sent Events の整形）
# ---------------------------------------------------------------------------


def to_sse(event_type: str, data: dict) -> str:
    """SSE の1フレームに整形する。

    SSE は **空行（\\n\\n）がフレームの区切り**です。本文をそのまま
    `data:` に流すと、答えに改行が含まれた瞬間にフレームが割れます。
    JSON にして1行へ畳むのが定石です（改行は \\n へエスケープされる）。
    """
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def sse_frames(deltas: list[str], *, stop_reason: str = "end_turn") -> list[str]:
    """差分の列を SSE のフレーム列にする。最後に終了フレームを必ず付ける。"""
    frames = [to_sse("delta", {"text": piece}) for piece in deltas]
    frames.append(to_sse("done", {"stopReason": stop_reason}))
    return frames


def text_from_sse(frames: list[str]) -> str:
    """受け取り側（ブラウザ）の処理を再現する。delta フレームだけを連結する。"""
    out: list[str] = []
    for frame in frames:
        head, _, payload = frame.partition("data: ")
        if not head.startswith("event: delta"):
            continue
        out.append(json.loads(payload.strip())["text"])
    return "".join(out)


# ---------------------------------------------------------------------------
# 演習の本体
# ---------------------------------------------------------------------------


def main() -> None:
    runtime = clients.bedrock_runtime()
    question, source = poc_probe.QUESTIONS[0]

    print("=== 1. 同期（全文が揃うまで待つ） ===")
    sync = sync_answer(runtime, question, source)
    print(f"stopReason={sync['stopReason']} / 出力{sync['usage']['outputTokens']}tok")
    print(f"申告レイテンシ {sync['reportedLatencyMs']} ms / 体感 {sync['wallMs']:.1f} ms")

    print()
    print("=== 2. ストリーミング（届いたぶんから出す） ===")
    printed: list[str] = []
    streamed = stream_answer(runtime, question, source, on_delta=printed.append)
    print("差分: " + " | ".join(streamed["deltas"]))
    print(f"イベント: {' -> '.join(streamed['eventNames'])}")
    print(f"初回差分まで {streamed['firstDeltaMs']:.1f} ms / 完了まで {streamed['totalMs']:.1f} ms")
    print(f"差分{len(streamed['deltas'])}個を連結した本文が同期と一致: "
          f"{streamed['text'] == sync['text']}")

    print()
    print("=== 3. ネイティブのストリーミング（二重構造） ===")
    native = native_stream(runtime, question, source)
    print(" -> ".join(native["types"]))
    print(f"stop_reason={native['stopReason']}（Converse 系は stopReason。名前も形も違う）")

    print()
    print("=== 4. Server-Sent Events へ整形する ===")
    frames = sse_frames(streamed["deltas"], stop_reason=streamed["stopReason"])
    print(frames[0].replace("\n", "\\n"))
    print(f"フレーム数 {len(frames)}（差分{len(streamed['deltas'])}＋終了1）")
    print(f"受け取り側で復元した本文が一致: {text_from_sse(frames) == sync['text']}")


if __name__ == "__main__":
    main()
