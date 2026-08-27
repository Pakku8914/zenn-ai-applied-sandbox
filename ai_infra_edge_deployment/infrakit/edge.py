"""エッジ側の実行（セッション12・13の参照実装）。

ONNX Runtime を使い、モデルを端末で動かす際の設定（スレッド数・量子化）が
レイテンシとメモリにどう効くかを測る。

LLM ではなく**小さな分類モデル**を題材にする。エッジの現実は「LLM を載せる」
ではなく「小さなモデルで足りる仕事を切り出す」ことが多いため。
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from pathlib import Path

SANDBOX = Path(__file__).resolve().parent.parent
ONNX_DIR = SANDBOX / "models" / "onnx"


def file_size_mb(path: Path) -> float:
    return Path(path).stat().st_size / 1024 / 1024 if Path(path).exists() else 0.0


@dataclass(frozen=True)
class EdgeBench:
    label: str
    size_mb: float
    latency_ms: dict[str, float]
    threads: int
    output_diff: float = 0.0  # fp32 との出力の最大差（精度劣化の指標）

    def summary(self) -> str:
        return (f"{self.label:<22} {self.size_mb:>8.2f} MB  "
                f"p50 {self.latency_ms['p50']:>7.2f}ms  p95 {self.latency_ms['p95']:>7.2f}ms  "
                f"threads={self.threads}  最大差={self.output_diff:.2e}")


def make_session(model_path: Path, threads: int = 1):
    """ONNX Runtime のセッションを作る。

    intra_op_num_threads は1つの演算子内の並列度、inter_op_num_threads は
    演算子間の並列度。端末では両方を絞ることが多い（他のアプリと資源を分け合うため）。
    """
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(str(model_path), sess_options=options,
                                providers=["CPUExecutionProvider"])


def bench_session(session, feeds: dict, label: str, model_path: Path, threads: int,
                  repeats: int = 30, warmup: int = 3) -> EdgeBench:
    """初回推論は遅い（グラフの最適化とメモリ確保）。ウォームアップして定常値を測る。"""
    for _ in range(warmup):
        session.run(None, feeds)
    lat: list[float] = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        session.run(None, feeds)
        lat.append((time.perf_counter() - t0) * 1000)
    lat.sort()
    return EdgeBench(
        label=label, size_mb=file_size_mb(model_path), threads=threads,
        latency_ms={"p50": statistics.median(lat),
                    "p95": lat[max(int(len(lat) * 0.95) - 1, 0)],
                    "max": lat[-1], "min": lat[0]},
    )


def first_inference_ms(model_path: Path, feeds: dict, threads: int = 1) -> float:
    """初回推論の時間。定常値と比べてウォームアップの必要性を示す。"""
    session = make_session(model_path, threads)
    t0 = time.perf_counter()
    session.run(None, feeds)
    return (time.perf_counter() - t0) * 1000
