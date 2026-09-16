"""量子化（セッション10・11の参照実装）。

本書で扱う2つの経路：
  1. ONNX Runtime の動的量子化（int8）… pip だけで完結し、CPU で速くなる
  2. GGUF への変換と llama.cpp の量子化（Q8_0 / Q4_K_M）… 配布と CPU 推論の定番

GPU 前提の手法（bitsandbytes の 4bit・GPTQ・AWQ）は CUDA が必要なため本書では扱わない。
概念は本文で説明し、実測は上の2経路で行う。
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path

SANDBOX = Path(__file__).resolve().parent.parent
EXPORT_DIR = SANDBOX / "export"
ONNX_DIR = SANDBOX / "onnx"


def dir_size_mb(path: Path) -> float:
    return sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file()) / 1024 / 1024


@dataclass
class QuantResult:
    label: str
    size_mb: float
    seconds: float
    note: str = ""

    def summary(self) -> str:
        return f"{self.label:<22} {self.size_mb:>9.1f} MB  ({self.seconds:.1f}s) {self.note}"


def save_merged(model, tokenizer, name: str) -> Path:
    """LoRA を統合して普通のモデルとして保存する。

    アダプタのまま配ると読み込み側に peft が必要になる。配布時は統合するのが素直。
    """
    out = EXPORT_DIR / name
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    merged = model.merge_and_unload() if hasattr(model, "merge_and_unload") else model
    merged.save_pretrained(out)
    tokenizer.save_pretrained(out)
    return out


def export_onnx(model_dir: Path, name: str) -> QuantResult:
    """HuggingFace のモデルを ONNX に書き出す。"""
    from optimum.onnxruntime import ORTModelForCausalLM
    from transformers import AutoTokenizer

    out = ONNX_DIR / name
    if out.exists():
        shutil.rmtree(out)
    t0 = time.perf_counter()
    ort_model = ORTModelForCausalLM.from_pretrained(model_dir, export=True)
    ort_model.save_pretrained(out)
    AutoTokenizer.from_pretrained(model_dir).save_pretrained(out)
    return QuantResult(f"ONNX fp32 ({name})", dir_size_mb(out), time.perf_counter() - t0)


def quantize_onnx_dynamic(onnx_dir: Path, name: str) -> QuantResult:
    """ONNX Runtime の動的量子化（重みを int8 にする）。

    キャリブレーションデータが不要なのが動的量子化の利点。
    活性化の量子化は推論時に動的に決めるため、静的量子化より少し遅いが手間が少ない。
    """
    from onnxruntime.quantization import QuantType, quantize_dynamic

    out = ONNX_DIR / name
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    src = next(Path(onnx_dir).glob("*.onnx"))
    quantize_dynamic(str(src), str(out / src.name), weight_type=QuantType.QInt8)
    # 設定ファイル類は元のディレクトリからコピーする（推論に必要）
    for extra in Path(onnx_dir).glob("*"):
        if extra.suffix != ".onnx" and extra.is_file():
            shutil.copy2(extra, out / extra.name)
    return QuantResult(f"ONNX int8 ({name})", dir_size_mb(out), time.perf_counter() - t0)
