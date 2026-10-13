"""問題2：声のあり・なしの並びを決めて VAD に流し、いつ・どれだけの長さで切り出すかを確かめる。

    docker compose exec api python -m src.session10.solutions.q2_vad_cases
"""

from __future__ import annotations

from src.session10.vad import FRAME_BYTES, FRAME_MS, UtteranceDetector

VOICED, SILENT = b"\x01" * FRAME_BYTES, bytes(FRAME_BYTES)
UPLINK = 640

CASES = {
    "雑音（0.09 秒）": [(False, 300), (True, 90), (False, 900)],
    "読点の間（0.45 秒）": [(False, 300), (True, 1200), (False, 450), (True, 900), (False, 900)],
    "鳴りっぱなし（16 秒）": [(True, 16000)],
}


def simulate(pattern: list[tuple[bool, int]], end_silence_ms: int = 600) -> list[str]:
    """(声ありか, ミリ秒) の並びを 20ms ずつ流し、判定を「種類@時刻ms（切り出した秒数）」の文字列で返す。"""
    det = UtteranceDetector(is_speech=lambda frame: frame[0] == 1, end_silence_ms=end_silence_ms)
    pcm = b"".join((VOICED if voiced else SILENT) * (ms // FRAME_MS) for voiced, ms in pattern)
    out: list[str] = []
    for i in range(0, len(pcm), UPLINK):
        for e in det.push(pcm[i:i + UPLINK]):
            label = f"{e.kind}@{(e.frame + 1) * FRAME_MS}ms"
            if e.kind == "speech_end":
                label += f"（{len(e.audio) / 32000:.2f}秒）"
            out.append(label)
    return out


def main() -> int:
    for name, pattern in CASES.items():
        for end in (600, 300):
            print(f"{name}・無音 {end}ms で終了: {simulate(pattern, end) or '判定なし'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
