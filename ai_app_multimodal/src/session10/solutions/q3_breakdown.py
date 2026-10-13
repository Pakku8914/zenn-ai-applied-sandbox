"""問題3：turn_end の latency_ms から、どこが支配的かを示す。

    docker compose exec api python -m src.session10.solutions.q3_breakdown
"""

from __future__ import annotations

PARTS = ("vad", "stt", "llm_first_sentence", "tts_first")
OTHER = "other"                    # first_audio から4つを引いた残り（WAV の送信と、タスクの切り替えの待ち）

ADVICE = {
    "vad": "終端の無音（END_SILENCE_MS）を短くする。短すぎると、読点の間で発話が切れる",
    "stt": "認識の設定（モデルの大きさ・beam・スレッド数）を見直す。発話の後ろの無音を削って、認識する長さを減らす",
    "llm_first_sentence": "最初の文を短くさせる（システムプロンプト・読点で早めに区切る）。速いモデルにする",
    "tts_first": "最初の文を短くする。合成の CPU を確保する（VV_CPU_NUM_THREADS）",
    OTHER: "送る WAV を小さくする。イベントループを止めている処理がないか確かめる",
}

EXAMPLES = {
    "A": {"vad": 612, "stt": 1840, "llm_first_sentence": 35, "tts_first": 1210, "first_audio": 3702},
    "B": {"vad": 605, "stt": 420, "llm_first_sentence": 2380, "tts_first": 690, "first_audio": 4101},
    "C": {"vad": 2010, "stt": 1650, "llm_first_sentence": 30, "tts_first": 1180, "first_audio": 4875},
    "D": {"vad": 600, "stt": 380, "llm_first_sentence": None, "tts_first": None, "first_audio": None},
}


def breakdown(lat: dict) -> list[tuple[str, int]] | None:
    """大きい順の (名前, ミリ秒)。返答しなかったターン（first_audio が None）は None。"""
    if lat["first_audio"] is None:
        return None
    parts = [(k, lat[k]) for k in PARTS]
    parts.append((OTHER, max(lat["first_audio"] - sum(v for _, v in parts), 0)))
    return sorted(parts, key=lambda p: p[1], reverse=True)


def dominant(lat: dict) -> tuple[str, float] | None:
    """最も長い部分と、first_audio に占める割合（％・小数第1位）。"""
    parts = breakdown(lat)
    if parts is None:
        return None
    name, ms = parts[0]
    return name, round(ms / lat["first_audio"] * 100, 1)


def main() -> int:
    for label, lat in EXAMPLES.items():
        top = dominant(lat)
        if top is None:
            print(f"{label}: 返答なし（内訳を比べない）")
            continue
        print(f"{label}: {top[0]} が {top[1]}% → {ADVICE[top[0]]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
