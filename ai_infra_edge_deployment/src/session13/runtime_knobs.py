#!/usr/bin/env python3
"""ランタイムの「つまみ」を1か所にまとめる（セッション13の共通部品）。

セッション12で使った `infrakit.edge.make_session` は**スレッド数だけ**を受け取る形で
凍結してある。本章はそれ以外のつまみ（メモリアリーナ・メモリパターン・グラフ最適化
レベル・実行プロバイダ・並列実行モード）も回すので、ここに入口を1つ作る。

つまみを散らさないのが目的である。設定がコードのあちこちに散ると、
**「どの設定で測った数字なのか」**が分からなくなり、測定が引き継げなくなる。

このファイル単体では何も測らない。実行するのは同じディレクトリの各スクリプト。
"""

from __future__ import annotations

import os
import platform
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

SANDBOX = Path(__file__).resolve().parents[2]
if str(SANDBOX) not in sys.path:
    sys.path.insert(0, str(SANDBOX))

from infrakit.edge import file_size_mb  # noqa: E402  セッション12から再利用する

ONNX_DIR = SANDBOX / "models" / "onnx"
REPORTS = SANDBOX / "reports"
SEED = 20260815
INPUT_DIM = 384
N_CLASSES = 6
OPT_LEVELS = ("disable", "basic", "extended", "all")


# --- 設定（つまみ）----------------------------------------------------------
@dataclass(frozen=True)
class Knobs:
    """1回の測定で使った設定の全部。**レポートにそのまま載せる前提**の入れ物。

    intra        : 1つの演算子の中の並列度（行列積を何分割して回すか）
    inter        : 演算子と演算子の並列度。ORT_PARALLEL のときだけ効く
    parallel     : True で ORT_PARALLEL（既定は逐次実行の ORT_SEQUENTIAL）
    arena        : CPU メモリアリーナ（確保したメモリを使い回す仕組み）
    mem_pattern  : 形状が固定のとき、必要な中間バッファを先に計画する仕組み
    opt          : グラフ最適化レベル（disable / basic / extended / all）
    providers    : 使いたい実行プロバイダの**優先順**。実在しないものは落とされる
    """

    intra: int = 1
    inter: int = 1
    parallel: bool = False
    arena: bool = True
    mem_pattern: bool = True
    opt: str = "all"
    providers: tuple[str, ...] = ("CPUExecutionProvider",)

    def label(self) -> str:
        return (f"intra={self.intra} inter={self.inter} "
                f"{'parallel' if self.parallel else 'sequential'} "
                f"arena={'on' if self.arena else 'off'} "
                f"pattern={'on' if self.mem_pattern else 'off'} opt={self.opt}")

    def as_dict(self) -> dict:
        return {"intra": self.intra, "inter": self.inter, "parallel": self.parallel,
                "arena": self.arena, "mem_pattern": self.mem_pattern, "opt": self.opt,
                "providers": list(self.providers)}


def _opt_level(name: str):
    import onnxruntime as ort

    table = {"disable": ort.GraphOptimizationLevel.ORT_DISABLE_ALL,
             "basic": ort.GraphOptimizationLevel.ORT_ENABLE_BASIC,
             "extended": ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED,
             "all": ort.GraphOptimizationLevel.ORT_ENABLE_ALL}
    if name not in table:
        raise ValueError(f"opt は {OPT_LEVELS} のいずれかです: {name!r}")
    return table[name]


# --- 実行プロバイダ ---------------------------------------------------------
def available_providers() -> list[str]:
    """このビルドで実際に使える実行プロバイダの一覧（環境で変わる）。"""
    import onnxruntime as ort

    return list(ort.get_available_providers())


def select_providers(wanted: list[str] | tuple[str, ...] | None) -> list[str]:
    """使いたい順に並べた要求から、**この環境に実在するものだけ**を残す。

    最後には必ず CPUExecutionProvider を置く（フォールバック）。実在しない名前を
    そのまま InferenceSession に渡すと例外になるので、その手前で落とすのがこの関数。
    「アクセラレータがあれば使い、無ければ CPU で動く」を1行で表現する。
    """
    have = available_providers()
    picked = [p for p in (wanted or []) if p in have]
    if "CPUExecutionProvider" not in picked:
        picked.append("CPUExecutionProvider")
    return picked


def build_session(model_path: Path | str, knobs: Knobs = Knobs()):
    """つまみを反映したセッションを作る。**作るのは1回だけ**が原則（使い回す）。"""
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = knobs.intra
    options.inter_op_num_threads = knobs.inter
    options.execution_mode = (ort.ExecutionMode.ORT_PARALLEL if knobs.parallel
                              else ort.ExecutionMode.ORT_SEQUENTIAL)
    options.enable_cpu_mem_arena = knobs.arena
    options.enable_mem_pattern = knobs.mem_pattern
    options.graph_optimization_level = _opt_level(knobs.opt)
    return ort.InferenceSession(str(model_path), sess_options=options,
                                providers=select_providers(knobs.providers))


# --- 測る -------------------------------------------------------------------
def fixed_input(batch: int = 1) -> dict[str, np.ndarray]:
    """毎回同じ入力を使う（セッション2の測定規約）。float32 に必ず落とす。"""
    rng = np.random.default_rng(SEED)
    return {"input": rng.normal(size=(batch, INPUT_DIM)).astype(np.float32)}


def measure(session, feeds: dict, repeats: int = 50, warmup: int = 5) -> dict[str, float]:
    """ウォームアップしてから repeats 回測り、分布を返す（単位はミリ秒）。"""
    for _ in range(warmup):
        session.run(None, feeds)
    lat: list[float] = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        session.run(None, feeds)
        lat.append((time.perf_counter() - t0) * 1000)
    lat.sort()
    return {"p50": statistics.median(lat),
            "p95": lat[max(int(len(lat) * 0.95) - 1, 0)],
            "min": lat[0], "max": lat[-1]}


def measure_median_of_runs(session, feeds: dict, runs: int = 3,
                           repeats: int = 50) -> dict[str, float]:
    """**3回測って中央値を採る**（本書の測定規約）。1回の測定で決めない。"""
    got = [measure(session, feeds, repeats=repeats) for _ in range(runs)]
    return {key: statistics.median(g[key] for g in got) for key in ("p50", "p95", "min", "max")}


def run_once(session, feeds: dict) -> np.ndarray:
    """出力を1回だけ取る（つまみを変えても答えが変わらないことの確認用）。"""
    return session.run(None, feeds)[0]


# --- 環境とメモリ -----------------------------------------------------------
def cpu_count() -> int:
    return os.cpu_count() or 1


def _proc_status_mb(key: str) -> float | None:
    """/proc/self/status から KB 単位の項目を読む。Linux 以外では None。"""
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith(key):
                return int(line.split()[1]) / 1024
    except OSError:
        return None
    return None


def rss_mb() -> float | None:
    """いまの実メモリ使用量（MB）。コンテナは Linux なので取れる。"""
    return _proc_status_mb("VmRSS:")


def peak_rss_mb() -> float | None:
    """プロセスが到達した実メモリの最大値（MB）。**比較に使うのはこちら**。

    RSS は解放しても下がらないことがあるので、同じプロセスで複数条件を測ると
    差が見えない。条件ごとに別プロセスで起動し、この値を比べる。
    """
    return _proc_status_mb("VmHWM:")


def env_line(repeats: int | None = None) -> str:
    """測定条件の1行。**数字を出すときは必ずこれを添える。**"""
    import onnxruntime as ort

    parts = [str(date.today()), platform.machine(), f"CPU {cpu_count()}コア",
             f"Python {platform.python_version()}", f"onnxruntime {ort.__version__}"]
    if repeats is not None:
        parts.append(f"{repeats}回の中央値")
    parts.append(f"入力は seed {SEED} の固定値")
    return " / ".join(parts)


# --- モデルの用意（外部からダウンロードしない）------------------------------
def ensure_model(hidden: int = 4096) -> Path:
    """その規模の fp32 モデルを用意する（無ければ固定シードで作る）。"""
    name = "classifier_fp32" if hidden == 4096 else f"classifier_h{hidden}"
    path = ONNX_DIR / f"{name}.onnx"
    if not path.exists():
        from tools.make_edge_model import build

        build(hidden, name)
    return path


def int8_path(fp32: Path) -> Path:
    stem = fp32.stem[:-5] if fp32.stem.endswith("_fp32") else fp32.stem
    return fp32.with_name(f"{stem}_int8.onnx")


def ensure_int8(fp32: Path) -> Path:
    """動的量子化した int8 モデルを用意する（作り方は前章で扱った）。"""
    out = int8_path(fp32)
    if not out.exists():
        from onnxruntime.quantization import QuantType, quantize_dynamic

        quantize_dynamic(str(fp32), str(out), weight_type=QuantType.QInt8)
    return out


def ensure_dynamic_batch(fp32: Path) -> Path:
    """バッチ次元だけを動的にしたコピーを作る（重みはまったく同じ）。

    形状は**宣言**なので、重みを触らずに書き換えられる。前章で「形状は契約」と
    書いた、その契約の文言だけを差し替える操作である。
    """
    out = fp32.with_name(f"{fp32.stem}_dynbatch.onnx")
    if not out.exists():
        import onnx

        model = onnx.load(str(fp32))
        for value_info in list(model.graph.input) + list(model.graph.output):
            value_info.type.tensor_type.shape.dim[0].dim_param = "batch"
        onnx.checker.check_model(model)
        onnx.save(model, out)
    return out


def model_pair(hidden: int = 4096) -> tuple[Path, Path]:
    """(fp32, int8) の組を返す。本章のほとんどのスクリプトはこれで始まる。"""
    fp32 = ensure_model(hidden)
    return fp32, ensure_int8(fp32)


def size_mb(path: Path) -> float:
    return file_size_mb(path)
