"""問題1：AudioWorklet（static/pcm-worklet.js）の変換を Python に写し、送る量と値を確かめる。

    docker compose exec api python -m src.session10.solutions.q1_worklet_port
"""

from __future__ import annotations

import math

import numpy as np

OUT_RATE = 16000
CHUNK = 320                     # 20ms
BLOCK = 128                     # AudioWorklet の process() が1回に受け取るサンプル数


class PcmSender:
    """pcm-worklet.js の PcmSender と同じ計算。process() に 1 ブロックを渡すと、できた 640 バイトの塊を返す。"""

    def __init__(self, in_rate: int) -> None:
        self.step = in_rate / OUT_RATE
        self.t = 0.0
        self.prev = 0.0
        self.buf: list[int] = []

    def process(self, block: np.ndarray) -> list[bytes]:
        out: list[bytes] = []
        n = len(block)
        while self.t < n - 1:
            i = math.floor(self.t)
            f = self.t - i
            a = self.prev if i < 0 else float(block[i])
            v = max(-1.0, min(1.0, a * (1 - f) + float(block[i + 1]) * f))
            self.buf.append(int(v * 0x8000) if v < 0 else int(v * 0x7FFF))   # int() は 0 に向けて切り捨て（Int16Array と同じ）
            if len(self.buf) == CHUNK:
                out.append(np.array(self.buf, dtype="<i2").tobytes())
                self.buf = []
            self.t += self.step
        self.t -= n
        self.prev = float(block[-1])
        return out


def to_int16(x: np.ndarray) -> np.ndarray:
    """worklet と同じ規則で -1.0〜1.0 を整数にする（負は ×32768、正は ×32767、0 に向けて切り捨て）。"""
    x = np.asarray(x, dtype=np.float64)              # JavaScript の数値と同じ 64bit で掛け算する
    return np.trunc(np.where(x < 0, x * 0x8000, x * 0x7FFF)).astype("<i2")


def run(in_rate: int, seconds: float = 1.0, hz: float = 440.0) -> tuple[list[bytes], np.ndarray]:
    """hz の正弦波（振幅 0.5）を in_rate で作り、128 サンプルずつ流す。(できた塊, 入力) を返す。"""
    x = (0.5 * np.sin(2 * np.pi * hz * np.arange(round(in_rate * seconds)) / in_rate)).astype(np.float32)
    sender = PcmSender(in_rate)
    chunks: list[bytes] = []
    for i in range(0, len(x), BLOCK):
        chunks += sender.process(x[i:i + BLOCK])
    return chunks, x


def main() -> int:
    for rate in (48000, 44100):
        chunks, _ = run(rate)
        sizes = {len(c) for c in chunks}
        print(f"{rate}Hz・1秒 → {len(chunks)} 個（各 {sizes} バイト）＝ {len(chunks) * 20}ms ぶん")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
