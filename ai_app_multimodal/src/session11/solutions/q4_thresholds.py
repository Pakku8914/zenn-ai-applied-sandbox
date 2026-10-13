"""問題4：割り込みのしきい値（声ありの長さ）を変えて、咳・物音で止まりすぎず、短い返事では止まるかを比べる。

    docker compose exec api python -m src.session11.solutions.q4_thresholds
"""

from __future__ import annotations

from src.session11.testkit import fake_detector, pattern
from src.session11.vad import FRAME_BYTES, FRAME_MS

CASES: dict[str, list[tuple[bool, int]]] = {
    "物音（120ms）": [(True, 120)],
    "咳（240ms）": [(True, 240)],
    "咳2回（210ms＋間300ms＋210ms）": [(True, 210), (False, 300), (True, 210)],
    "「はい」（360ms）": [(True, 360)],
    "「ちょっと待って」（750ms）": [(True, 750)],
}
THRESHOLDS = (150, 300, 500)


def would_interrupt(parts: list[tuple[bool, int]], barge_in_ms: int, *, consecutive: bool = False) -> bool:
    """前後に無音を付けた音を 30ms ずつ流し、割り込みの条件に届くか。consecutive なら「続けて声あり」の長さで数える。"""
    det = fake_detector()
    need = barge_in_ms // FRAME_MS
    run = 0
    pcm = pattern((False, 300), *parts, (False, 750))
    for i in range(0, len(pcm), FRAME_BYTES):
        frame = pcm[i:i + FRAME_BYTES]
        det.push(frame)
        run = run + 1 if frame[0] == 1 else 0
        if det.in_speech and (run if consecutive else det.voiced_frames) >= need:
            return True
    return False


def table() -> dict[str, list[bool]]:
    return {name: [would_interrupt(parts, ms) for ms in THRESHOLDS] for name, parts in CASES.items()}


def main() -> int:
    mark = {True: "止まる", False: "止まらない"}
    print("| 音 | " + " | ".join(f"{ms}ms" for ms in THRESHOLDS) + " |")
    print("| :-- | :-- | :-- | :-- |")
    for name, row in table().items():
        print(f"| {name} | " + " | ".join(mark[x] for x in row) + " |")
    two = would_interrupt(CASES["咳2回（210ms＋間300ms＋210ms）"], 300, consecutive=True)
    print(f"続けて数える版（300ms）: 咳2回 → {mark[two]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
