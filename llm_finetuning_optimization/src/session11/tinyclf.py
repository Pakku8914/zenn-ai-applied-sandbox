"""セッション11の共通部品：小さな自作分類器・特徴量・ONNX 書き出し・静的量子化。

**なぜ LLM を使わないのか。** `optimum` 経由の ONNX 書き出しは 135M でも既定環境
（メモリ 5.8GB）では OOM で失敗する（requirements.md の実測）。そのため本セッションの
実行部分は「数MBの自作分類器」で組む。動的量子化・静的量子化・キャリブレーションの
違いは、モデルの大小に関係なく同じ形で観察できる。

このモジュールが提供するもの:

    make_features(seed, n, min_len, max_len) -> np.ndarray   # 問い合わせを模した特徴量
    build_model()                                            # 2.71M パラメータの分類器
    export_fp32(name) -> (Path, QuantResult)                 # torch.onnx.export で書き出す
    quantize_static_int8(src_dir, name, calibration)         # 静的量子化（キャリブレーション必須）
    predict(model_dir, X) -> np.ndarray                      # ONNX Runtime で推論する
    output_diff(p_ref, p_q) -> dict                          # 出力差（最大差・平均差・一致率）
    latency_ms(model_dir, x, repeat) -> float                # 1件あたりのレイテンシ
    op_histogram(model_path) / int8_initializer_count(model_path)

動的量子化は本書の共通ライブラリ `ftkit.quantize.quantize_onnx_dynamic` をそのまま使う
（キャリブレーションが要らないので、引数もモデルのパスだけで足りる）。
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

import numpy as np

SANDBOX = Path(__file__).resolve().parents[2]
ONNX_DIR = SANDBOX / "onnx"

sys.path.insert(0, str(SANDBOX))

from ftkit.quantize import QuantResult, dir_size_mb  # noqa: E402

SEED = 20260815
FEATURE_DIM = 512          # 文字を 512 個のバケットに数え上げた特徴量
HIDDEN = 1408              # 隠れ層の幅（fp32 で約 10.9MB になるように選んだ）
N_CLASS = 6                # ftkit.data.CATEGORIES と同じ 6 区分


def param_count() -> int:
    """パラメータ数（重み＋バイアス）。サイズの計算値を出すために使う。"""
    weights = FEATURE_DIM * HIDDEN + HIDDEN * HIDDEN + HIDDEN * N_CLASS
    biases = HIDDEN + HIDDEN + N_CLASS
    return weights + biases


def make_features(seed: int, n: int, min_len: int, max_len: int,
                  dim: int = FEATURE_DIM) -> np.ndarray:
    """問い合わせ1件を「文字を dim 個のバケットに数え上げた特徴量」に見立てて合成する。

    min_len〜max_len が文字数にあたる。**文字数が特徴量の大きさを決める**ので、
    「短い問い合わせだけ」でキャリブレーションすると活性化の範囲を読み違える。
    キャリブレーションデータの偏りを再現するための仕掛け。
    """
    rng = np.random.default_rng(seed)
    lengths = rng.integers(min_len, max_len + 1, size=n)
    features = np.zeros((n, dim), dtype=np.float32)
    for i, length in enumerate(lengths):
        idx = rng.integers(0, dim, size=int(length))
        features[i] = np.bincount(idx, minlength=dim).astype(np.float32)
    return features


def build_model():
    """6区分の分類器。学習はしない（量子化の観察に学習は不要）。

    nn.Linear ではなく torch.matmul を明示的に書く。ONNX に MatMul として現れ、
    「量子化の対象は行列積である」ことがグラフを見たときに分かるため。
    """
    import torch
    from torch import nn

    class TinyClassifier(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            gen = torch.Generator().manual_seed(SEED)   # 再現性のため乱数生成器を固定する

            def weight(rows: int, cols: int) -> nn.Parameter:
                return nn.Parameter(torch.randn(rows, cols, generator=gen) / rows ** 0.5)

            self.w1 = weight(FEATURE_DIM, HIDDEN)
            self.b1 = nn.Parameter(torch.zeros(HIDDEN))
            self.w2 = weight(HIDDEN, HIDDEN)
            self.b2 = nn.Parameter(torch.zeros(HIDDEN))
            self.w3 = weight(HIDDEN, N_CLASS)
            self.b3 = nn.Parameter(torch.zeros(N_CLASS))

        def forward(self, x):
            h = torch.relu(torch.matmul(x, self.w1) + self.b1)
            h = torch.relu(torch.matmul(h, self.w2) + self.b2)
            return torch.softmax(torch.matmul(h, self.w3) + self.b3, dim=-1)

    return TinyClassifier().eval()


def _fresh_dir(name: str) -> Path:
    out = ONNX_DIR / name
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    return out


def export_fp32(name: str = "session11-fp32") -> tuple[Path, QuantResult]:
    """自作モデルを fp32 の ONNX として書き出す。

    ftkit.quantize.export_onnx は optimum 経由で LLM を書き出す関数で、既定環境では
    OOM になる。自作モデルは torch.onnx.export で直接書き出せば数秒で終わる。
    """
    import torch

    out = _fresh_dir(name)
    model = build_model()
    dummy = torch.zeros(1, FEATURE_DIM)         # 形状を固定して書き出す（バッチ1）
    t0 = time.perf_counter()
    # dynamo=False（TorchScript 版の exporter）を明示する。torch 2.9 以降は
    # torch.export ベースの exporter が既定になったが、次の2点で本章には使えない。
    #   1. 別パッケージ onnxscript が必要（未導入なら ModuleNotFoundError）
    #   2. 書き出したグラフを onnxruntime の quantize_dynamic が扱えない
    #      （shape inference が「Inferred shape and existing shape differ」で落ちる）
    # 実際に両方試して確認した。量子化まで通すなら現時点では dynamo=False が確実。
    torch.onnx.export(
        model,
        (dummy,),
        str(out / "model.onnx"),
        input_names=["features"],
        output_names=["probs"],
        dynamic_axes={"features": {0: "n"}, "probs": {0: "n"}},
        opset_version=18,
        dynamo=False,
    )
    return out, QuantResult(f"ONNX fp32 ({name})", dir_size_mb(out), time.perf_counter() - t0)


def model_path(model_dir: Path) -> Path:
    return next(Path(model_dir).glob("*.onnx"))


def op_histogram(path: Path) -> dict[str, int]:
    """ONNX グラフのオペレータを数える。どの演算が量子化されたかを確かめるのに使う。"""
    import onnx

    graph = onnx.load(str(path)).graph
    hist: dict[str, int] = {}
    for node in graph.node:
        hist[node.op_type] = hist.get(node.op_type, 0) + 1
    return dict(sorted(hist.items()))


def int8_initializer_count(path: Path) -> int:
    """int8 で保存されている重みの本数。量子化が本当に効いたかの直接の証拠。"""
    import onnx

    model = onnx.load(str(path))
    return sum(1 for t in model.graph.initializer if t.data_type == onnx.TensorProto.INT8)


def _session(model_dir: Path):
    import onnxruntime as ort

    ort.set_default_logger_severity(3)          # 警告だけに絞る（出力を読みやすくする）
    return ort.InferenceSession(str(model_path(model_dir)),
                                providers=["CPUExecutionProvider"])


def predict(model_dir: Path, features: np.ndarray) -> np.ndarray:
    """ONNX Runtime で1件ずつ推論して確率を返す。形状を固定して書き出したのでバッチ1。"""
    sess = _session(model_dir)
    name = sess.get_inputs()[0].name
    x = np.ascontiguousarray(features, dtype=np.float32)
    rows = [sess.run(None, {name: x[i:i + 1]})[0][0] for i in range(len(x))]
    return np.asarray(rows, dtype=np.float64)


def latency_ms(model_dir: Path, one_row: np.ndarray, repeat: int = 200) -> float:
    """1件あたりのレイテンシ（ミリ秒）。**環境ごとに変わるので記録して比べる。**"""
    sess = _session(model_dir)
    name = sess.get_inputs()[0].name
    feed = {name: np.ascontiguousarray(one_row, dtype=np.float32).reshape(1, -1)}
    for _ in range(10):                         # 計測前に温める（初回は遅い）
        sess.run(None, feed)
    t0 = time.perf_counter()
    for _ in range(repeat):
        sess.run(None, feed)
    return (time.perf_counter() - t0) / repeat * 1000


def output_diff(p_ref: np.ndarray, p_quant: np.ndarray) -> dict[str, float]:
    """量子化前後の出力差。**基準は必ず fp32 の出力**（量子化後どうしを比べない）。"""
    diff = np.abs(np.asarray(p_ref) - np.asarray(p_quant))
    agree = float((np.asarray(p_ref).argmax(axis=1) == np.asarray(p_quant).argmax(axis=1)).mean())
    return {"max_abs": float(diff.max()), "mean_abs": float(diff.mean()), "argmax_agree": agree}


def quantize_static_int8(src_dir: Path, name: str, calibration: np.ndarray) -> QuantResult:
    """静的量子化（int8）。**キャリブレーションデータが必須**なのが動的量子化との違い。

    activation_type を指定している点に注目する。動的量子化は活性化のスケールを実行時に
    決めるので指定しようがないが、静的量子化は事前に決めるので指定できる（＝決められる）。
    """
    from onnxruntime.quantization import (
        CalibrationDataReader,
        CalibrationMethod,
        QuantFormat,
        QuantType,
        quantize_static,
    )

    src = model_path(src_dir)
    out = _fresh_dir(name)
    input_name = _session(src_dir).get_inputs()[0].name
    rows = np.ascontiguousarray(calibration, dtype=np.float32)

    class FeatureReader(CalibrationDataReader):
        """キャリブレーションデータを1件ずつ流し込む。get_next が None を返したら終わり。"""

        def __init__(self) -> None:
            self.index = 0

        def get_next(self):
            if self.index >= len(rows):
                return None
            feed = {input_name: rows[self.index:self.index + 1]}
            self.index += 1
            return feed

        def rewind(self) -> None:
            self.index = 0

    t0 = time.perf_counter()
    quantize_static(
        str(src),
        str(out / src.name),
        FeatureReader(),
        quant_format=QuantFormat.QDQ,
        op_types_to_quantize=["MatMul"],        # 行列積だけを量子化する（挙動を追いやすくする）
        per_channel=False,
        activation_type=QuantType.QInt8,
        weight_type=QuantType.QInt8,
        calibrate_method=CalibrationMethod.MinMax,
    )
    note = f"calib n={len(rows)}"
    return QuantResult(f"ONNX int8 static ({name})", dir_size_mb(out),
                       time.perf_counter() - t0, note)
