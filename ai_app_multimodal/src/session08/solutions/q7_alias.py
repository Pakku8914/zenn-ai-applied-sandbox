"""問題7（発展）：間引く前のローパスフィルタが「折り返し雑音」を防ぐことを、サイン波と FFT で確かめる。

    docker compose exec api python -m src.session08.solutions.q7_alias
"""

from __future__ import annotations

import numpy as np

from src.session08.audio_in import to_16k_mono
from src.session08.testaudio import tone


def naive_resample(audio: np.ndarray, rate: int, target: int = 16000) -> np.ndarray:
    """フィルタをかけずに、時刻を合わせて間を埋めるだけの変換（to_16k_mono からローパスを抜いたもの）。"""
    n_out = round(len(audio) * target / rate)
    return np.interp(np.arange(n_out) / target, np.arange(len(audio)) / rate, audio).astype(np.float32)


def level_db(audio: np.ndarray, rate: int, freq: float) -> float:
    """freq Hz の成分の大きさ（dB）。端の切れ目の影響を抑えるため、ハン窓をかけてから FFT する。"""
    spectrum = np.abs(np.fft.rfft(audio * np.hanning(len(audio))))
    k = round(freq * len(audio) / rate)
    return float(20 * np.log10(spectrum[k - 2:k + 3].max() + 1e-12))


def experiment() -> dict[str, float]:
    high = tone(10_000, 24_000, 1.0)    # 16kHz では表せない（8kHz を超える）音
    low = tone(3_000, 24_000, 1.0)      # 残したい音
    return {
        "alias_naive": level_db(naive_resample(high, 24_000), 16_000, 6_000),     # 16000 - 10000 = 6000Hz に化ける
        "alias_filtered": level_db(to_16k_mono(high, 24_000), 16_000, 6_000),
        "keep_naive": level_db(naive_resample(low, 24_000), 16_000, 3_000),
        "keep_filtered": level_db(to_16k_mono(low, 24_000), 16_000, 3_000),
    }


if __name__ == "__main__":
    r = experiment()
    print(f"10kHz が 6kHz に化けた音：フィルタなし {r['alias_naive']:.1f}dB／あり {r['alias_filtered']:.1f}dB")
    print(f"3kHz の音（残したい）　：フィルタなし {r['keep_naive']:.1f}dB／あり {r['keep_filtered']:.1f}dB")
