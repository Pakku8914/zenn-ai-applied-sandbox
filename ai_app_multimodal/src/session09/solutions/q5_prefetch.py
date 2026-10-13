"""問題5：先読みしない（前の文が鳴り終わってから次を合成する）場合と比べる。

    docker compose exec api python -m src.session09.solutions.q5_prefetch
"""

from __future__ import annotations

from src.session09.timeline import Timeline, plan_sentences, plan_whole


def plan_no_prefetch(synth: list[float], audio: list[float]) -> Timeline:
    """i 文目の合成は、i-1 文目が鳴り終わってから始める。"""
    now = 0.0
    first = 0.0
    gaps: list[float] = []
    for i, (s, a) in enumerate(zip(synth, audio, strict=True)):
        start = now + s                   # 合成のあいだは無音
        if i == 0:
            first = start
        else:
            gaps.append(round(s, 3))
        now = start + a
    return Timeline(round(first, 3), tuple(gaps), round(now, 3))


def compare(audio: list[float], rtf: float) -> dict[str, Timeline]:
    synth = [round(a * rtf, 3) for a in audio]
    return {
        "全文": plan_whole(sum(synth), sum(audio)),
        "文ごと・先読みなし": plan_no_prefetch(synth, audio),
        "文ごと・先読みあり": plan_sentences(synth, audio),
    }


def main() -> int:
    for label, audio, rtf in [("5文×3秒", [3.0] * 5, 0.5), ("5文×3秒", [3.0] * 5, 1.2), ("短い文→長い文", [1.0, 6.0], 0.5)]:
        print(f"{label}・RTF {rtf}")
        for name, t in compare(audio, rtf).items():
            print(f"  {name}: 最初の音 {t.first_audio} 秒・途切れ {list(t.gaps)}・最後 {t.finished} 秒")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
