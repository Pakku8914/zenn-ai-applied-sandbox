"""問題1：利用量の記録を種類ごとに集計する（UsageLog.totals() では足りない理由）。

    docker compose exec api python -m src.session14.solutions.q1_usage_summary
"""

from __future__ import annotations

import json

from kondate.clock import FixedClock
from kondate.llm import Usage
from kondate.usage import UsageLog, UsageRecord

# (利用者, 種類, 値)。hit は応答キャッシュに命中したリクエスト（LLM を呼んでいない）
EVENTS = [
    ("u001", "llm", Usage(1668, 194)),                                         # 冷蔵庫の写真（外れ）
    ("u001", "hit", None),                                                     # 同じ写真（命中）
    ("u001", "llm", Usage(12, 38, cache_read_input_tokens=0, cache_creation_input_tokens=4876)),  # PDF の質問
    ("u001", "hit", None),                                                     # 同じ質問（命中）
    ("u002", "llm", Usage(12, 38, cache_read_input_tokens=4876, cache_creation_input_tokens=0)),  # 別の人
    ("u001", "stt", (3.81, 1.905)),                                            # (音声の秒数, 処理秒数)
    ("u001", "tts", (4.2, 1.89)),
    ("u001", "stt", (2.5, 1.25)),
]


def replay(log: UsageLog) -> None:
    for user, kind, value in EVENTS:
        if kind == "hit":
            continue                                    # 命中は LLM を呼んでいないので記録しない
        if kind == "llm":
            log.add(user, "llm", "llm", input_tokens=value.input_tokens, output_tokens=value.output_tokens)
        else:
            log.add(user, kind, kind, audio_seconds=round(value[0], 3), processing_seconds=round(value[1], 3))


def summarize(records: list[UsageRecord], user_id: str) -> dict:
    mine = [r for r in records if r.user_id == user_id]

    def seconds(kind: str, field: str) -> float:
        return round(sum((getattr(r, field) for r in mine if r.kind == kind), 0.0), 3)

    return {
        "llm": {"input_tokens": sum(r.input_tokens for r in mine if r.kind == "llm"),
                "output_tokens": sum(r.output_tokens for r in mine if r.kind == "llm")},
        "stt_seconds": seconds("stt", "audio_seconds"),
        "tts_seconds": seconds("tts", "audio_seconds"),
        "stt_processing_seconds": seconds("stt", "processing_seconds"),
        "tts_processing_seconds": seconds("tts", "processing_seconds"),
    }


def run() -> list[str]:
    log = UsageLog(FixedClock())
    replay(log)
    dump = lambda d: json.dumps(d, ensure_ascii=False)  # noqa: E731
    return [
        f"totals(u001): {dump(log.totals('u001'))}",
        f"summarize(u001): {dump(summarize(log.records, 'u001'))}",
        f"summarize(u002): {dump(summarize(log.records, 'u002'))}",
        f"記録した件数：{len(log.records)}（命中の2件は記録しない）",
    ]


def main() -> None:
    print("\n".join(run()))


if __name__ == "__main__":
    main()
