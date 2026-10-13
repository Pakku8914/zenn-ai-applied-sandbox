"""問題7：遅延の内訳（セッション10の latency_ms）を項目ごとに p50・p95・平均で集計し、支配的な項目を比べる。

    docker compose exec api python -m src.session12.solutions.q7_breakdown
"""

from __future__ import annotations

from src.session12.eval_latency import summarize

KEYS = ("vad", "stt", "llm_first_sentence", "tts_first", "first_audio")
PARTS = KEYS[:4]
SLOW_TURNS = {3, 10, 16}   # 0 始まり。この3ターンだけ LLM の最初の文が遅い（架空のデータ）


def sample_turns() -> list[dict]:
    turns = []
    for n in range(20):
        lat = {"vad": 640, "stt": 1500, "llm_first_sentence": 4500 if n in SLOW_TURNS else 800, "tts_first": 3400}
        lat["first_audio"] = sum(lat.values()) + 40   # 40ms は WAV を送るぶん
        turns.append(lat)
    return turns


def breakdown(turns: list[dict]) -> dict[str, dict]:
    return {key: summarize([t[key] for t in turns]) for key in KEYS}


def dominant(table: dict[str, dict], stat: str) -> str:
    return max(PARTS, key=lambda k: table[k][stat])


def main() -> int:
    table = breakdown(sample_turns())
    for key in KEYS:
        s = table[key]
        print(f"{key:<19} 平均 {s['mean_ms']}ms・p50 {s['p50_ms']}ms・p95 {s['p95_ms']}ms")
    for stat in ("mean_ms", "p50_ms", "p95_ms"):
        print(f"{stat} で最も長い項目：{dominant(table, stat)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
