#!/usr/bin/env python3
"""判断基準：タスク × 端末クラスの実現可能性マトリクス（セッション14）。

端末E（マイコン級）は **池が2つ**（Flash / RAM）なので別々に判定する。
端末D・端末A は **セッション11の共通端末**をそのまま使う（同じ端末を指すなら同じ数値）。

  端末A: 物理 4,096 MB / OS 1,024 MB / 他アプリ 1,536 MB -> 上限 1,228.80 MB
  端末D: 物理 1,024 MB / OS   256 MB / 他アプリ   128 MB -> 上限   512.00 MB

    python src/session14/feasibility.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

SANDBOX = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SANDBOX))
sys.path.insert(0, str(SANDBOX / "src" / "session11"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from edge_budget import Footprint, MemoryBudget, fits as fits_mb  # noqa: E402
from mcu_budget import (  # noqa: E402
    DEVICE_E, GGUF_Q4_K_M_MB, KB, KV_PER_TOKEN_KB_05B, KV_PER_TOKEN_KB_8B,
    MODEL_C12, MODEL_K, MODEL_W, ONNX_INT8_MB, SEQ_LEN, WELFORD_STATE_BYTES,
    fits_raw,
)

# ③ 前提値：セッション11の共通端末（数値を変えると章をまたいだ比較が壊れる）
DEVICE_D = MemoryBudget(total_mb=1024, os_reserved_mb=256, other_apps_mb=128)
DEVICE_A = MemoryBudget(total_mb=4096, os_reserved_mb=1024, other_apps_mb=1536)

# ③ 前提値：セッション11が置いた実行時メモリ（分類器 50.0 MB / 言語モデル 150.0 MB）
RUNTIME_CLASSIFIER_MB = 50.0
RUNTIME_LLM_MB = 150.0

# ③ 前提値：音声 1 秒（16kHz・int16）のバッファ
AUDIO_1S_BYTES = 16_000 * 2


@dataclass(frozen=True)
class TaskNeed:
    """タスク1件が要求する量。Flash 側と RAM 側を分けて持つ（KB 単位）。"""

    name: str
    weights_kb: float
    arena_kb: float
    runtime_mb: float      # OS のある端末で追加で要る実行時メモリ（③前提値）

    def total_mb(self) -> float:
        return (self.weights_kb + self.arena_kb) / KB + self.runtime_mb


TASKS = (
    TaskNeed("異常検知（逐次統計量）", 0.0, WELFORD_STATE_BYTES / KB, 0.0),
    TaskNeed("キーワード検出（モデルK・int8）", MODEL_K.weights_kb(),
             MODEL_K.arena_peak_kb(), RUNTIME_CLASSIFIER_MB),
    TaskNeed("画像の在/不在（モデルW・int8）", MODEL_W.weights_kb(),
             MODEL_W.arena_peak_kb(), RUNTIME_CLASSIFIER_MB),
    TaskNeed(f"6分類の分類器（S12・int8・{ONNX_INT8_MB} MB）", ONNX_INT8_MB * KB,
             MODEL_C12.arena_peak_kb(), RUNTIME_CLASSIFIER_MB),
    TaskNeed(f"0.5B の言語モデル（Q4_K_M・{GGUF_Q4_K_M_MB} MB）", GGUF_Q4_K_M_MB * KB,
             KV_PER_TOKEN_KB_05B * SEQ_LEN, RUNTIME_LLM_MB),
    TaskNeed("8B 級の言語モデル（f16）", 8e9 * 2 / KB,
             KV_PER_TOKEN_KB_8B * SEQ_LEN, RUNTIME_LLM_MB),
)


def mcu_ok(task: TaskNeed) -> bool:
    """マイコン級は2つの池を別々に判定する（片方でも溢れたら載らない）。"""
    return fits_raw(DEVICE_E, task.weights_kb, task.arena_kb).ok


def mb_ok(budget: MemoryBudget, task: TaskNeed) -> bool:
    """OS のある端末は1つの池として judge する（セッション11の見積もり）。"""
    fp = Footprint(weights_mb=task.weights_kb / KB, kv_mb=task.arena_kb / KB,
                   runtime_mb=task.runtime_mb)
    ok, _ = fits_mb(budget, fp)
    return ok


def word(ok: bool) -> str:
    return "載る" if ok else "載らない"


def print_matrix() -> None:
    print("=== 判断基準：タスク × 端末クラス（③前提値の設計）===")
    print(f"端末E（マイコン級・本章）: Flash {DEVICE_E.weights_limit_kb:.2f} KB / "
          f"RAM アリーナ {DEVICE_E.arena_limit_kb:.2f} KB")
    print(f"端末D（SBC 相当・S11・物理 {DEVICE_D.total_mb:,.0f} MB）: "
          f"推論に使える上限 {DEVICE_D.limit_mb:.2f} MB")
    print(f"端末A（スマホ相当・S11・物理 {DEVICE_A.total_mb:,.0f} MB）: "
          f"推論に使える上限 {DEVICE_A.limit_mb:.2f} MB")
    print()
    print("| タスク | 必要量 | 端末E | 端末D | 端末A |")
    print("| :--- | :--- | :--- | :--- | :--- |")
    for t in TASKS:
        print(f"| {t.name} | Flash {t.weights_kb:,.2f} KB / RAM {t.arena_kb:,.2f} KB | "
              f"{word(mcu_ok(t))} | {word(mb_ok(DEVICE_D, t))} | "
              f"{word(mb_ok(DEVICE_A, t))} |")


def print_device_d() -> None:
    print("\n=== 端末D で見た合計（重み＋中間テンソル＋実行時メモリ③前提値）===")
    print("| タスク | 合計 | 端末D の上限 | 判定 |")
    print("| :--- | --: | --: | :--- |")
    for t in TASKS:
        print(f"| {t.name} | {t.total_mb():,.2f} MB | {DEVICE_D.limit_mb:.2f} MB | "
              f"{word(mb_ok(DEVICE_D, t))} |")
    print("-> **端末のクラスを1つ上げると、載るタスクが1段増える。** "
          "これが「タスクを変える」以外の選択肢である。")


def print_options() -> None:
    limit = DEVICE_E.arena_limit_kb
    feat_kb = MODEL_K.tensors[0] / KB
    audio_kb = AUDIO_1S_BYTES / KB
    c12_mb = TASKS[3].total_mb()
    print("\n=== 載らないときの3つの選択肢（端末E で測る）===")
    print("| 選択肢 | 端末に置くもの | RAM | アリーナ上限比 |")
    print("| :--- | :--- | --: | --: |")
    print(f"| ① タスクを分ける（前段だけ端末） | 特徴量 49x40（int8） | "
          f"{feat_kb:.2f} KB | {feat_kb / limit:.1%} |")
    print(f"| ② クラウドに送る（生データ） | 音声 1 秒（16kHz・int16） | "
          f"{audio_kb:.2f} KB | {audio_kb / limit:.1%} |")
    print(f"| ③ 端末のクラスを上げる | モデルそのまま（端末D で {c12_mb:.2f} MB） | "
          "— | — |")


def main() -> None:
    print_matrix()
    print_device_d()
    print_options()


if __name__ == "__main__":
    main()
