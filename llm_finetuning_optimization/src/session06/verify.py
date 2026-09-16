#!/usr/bin/env python3
"""セッション6の自己検証：LoRA のパラメータ・保存・切替・統合。

検証する主張（本文に書いた内容と1対1で対応させる）:
  1. 学習対象は r に正比例し、層の形からの計算値と param_stats が一致する
  2. SmolLM2-135M / r=16 / attention の4つで 1,843,200 個（1.35%）になる
  3. target_modules に MLP を含めると学習対象が増える（計算値と一致する）
  4. アダプタだけを保存すると「学習対象 × 4 バイト」相当のサイズになる
  5. merge_and_unload の統合前後で生成結果が一致する
  6. 1体のベースに2枚のアダプタを載せて切り替えられる
     （読み込んだアダプタは既定で凍結されている）

メモリ 5.8GB の環境では 135M モデルを3体同時に保持できない（1体あたり
peak RSS 約 2.11GB）。**モデルは必ず1体ずつ読み、del と gc.collect() で
解放する。** 学習は 12 step + 8 step だけなので数分で終わる。

  python src/session06/verify.py
  SAVE_MERGED=1 python src/session06/verify.py   # 統合済みモデル（約 513MB）も書き出す
"""

from __future__ import annotations

import gc
import os
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ftkit.data import build_prompt, load  # noqa: E402
from ftkit.evaluate import generate  # noqa: E402
from ftkit.models import FAST_MODEL, attach_lora, load_model, load_tokenizer, param_stats  # noqa: E402
from ftkit.quantize import dir_size_mb, save_merged  # noqa: E402
from ftkit.train import TrainConfig, set_seed, train  # noqa: E402

SEED = 20260815
ATTENTION = ("q_proj", "k_proj", "v_proj", "o_proj")
MLP = ("gate_proj", "up_proj", "down_proj")
EXPORT = Path(__file__).resolve().parents[2] / "export" / "session06"

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def expected_lora_params(model, r: int, targets: tuple[str, ...]) -> int:
    """LoRA を付けたときに増えるパラメータ数を、層の形から計算する。

    アダプタを付ける **前** のモデルに対して呼ぶ（付けた後は nn.Linear が
    peft の層に差し替わるので isinstance で拾えなくなる）。
    """
    total = 0
    for name, module in model.named_modules():
        if isinstance(module, torch.nn.Linear) and name.split(".")[-1] in targets:
            total += r * (module.in_features + module.out_features)
    return total


tokenizer = load_tokenizer(FAST_MODEL)
train_examples = load("train")
samples = load("test")[:3]

# --- 1. r を振ると学習対象が正比例で増える ---------------------------------
print("=== 1. r と学習対象パラメータ数 ===")
stats_by_r: dict[int, dict] = {}
for r in (4, 16, 64):
    base = load_model(FAST_MODEL)
    calc = expected_lora_params(base, r, ATTENTION)     # 付ける前に計算する
    set_seed(SEED)                                      # モデル構築の前に呼ぶ
    model = attach_lora(base, r=r, alpha=2 * r, target_modules=ATTENTION)
    stats = param_stats(model)
    stats_by_r[r] = {"calc": calc, **stats}
    print(f"  r={r:>2} alpha={2 * r:>3}  計算 {calc:>9,}  実測 {stats['trainable']:>9,}  "
          f"割合 {stats['ratio'] * 100:.2f}%")
    check(f"r={r} の計算値と param_stats が一致する", calc == stats["trainable"],
          f"{calc:,} vs {stats['trainable']:,}")
    del model, base
    gc.collect()                                        # 次を読む前に必ず解放する

check("学習対象は r に正比例する（r=64 は r=4 の16倍）",
      stats_by_r[64]["trainable"] == 16 * stats_by_r[4]["trainable"],
      f"{stats_by_r[4]['trainable']:,} -> {stats_by_r[64]['trainable']:,}")
check("r=16 の学習対象が 1,843,200 個（本文の実測と一致）",
      stats_by_r[16]["trainable"] == 1_843_200, f"{stats_by_r[16]['trainable']:,}")
check("r=16 の割合が 1.35%（小数第2位まで）",
      round(stats_by_r[16]["ratio"] * 100, 2) == 1.35,
      f"{stats_by_r[16]['ratio'] * 100:.2f}%")
check("r を上げると割合が単調に増える",
      stats_by_r[4]["ratio"] < stats_by_r[16]["ratio"] < stats_by_r[64]["ratio"],
      " < ".join(f"{stats_by_r[r]['ratio'] * 100:.2f}%" for r in (4, 16, 64)))

# --- 2. target_modules を広げると学習対象が増える ---------------------------
print("\n=== 2. target_modules と学習対象パラメータ数 ===")
base = load_model(FAST_MODEL)
calc_attn = expected_lora_params(base, 16, ATTENTION)
calc_mlp = expected_lora_params(base, 16, MLP)
calc_both = expected_lora_params(base, 16, ATTENTION + MLP)
set_seed(SEED)
model = attach_lora(base, r=16, alpha=32, target_modules=ATTENTION + MLP)
stats_both = param_stats(model)
print(f"  attention(4)     : {calc_attn:>9,}")
print(f"  mlp(3)           : {calc_mlp:>9,}")
print(f"  attention+mlp(7) : {calc_both:>9,}  実測 {stats_both['trainable']:>9,}  "
      f"割合 {stats_both['ratio'] * 100:.2f}%")
check("attention+MLP の計算値と param_stats が一致する",
      calc_both == stats_both["trainable"],
      f"{calc_both:,} vs {stats_both['trainable']:,}")
check("attention+MLP は attention のみより多い（r=16 で 4,884,480 個）",
      calc_both == 4_884_480 and calc_both > calc_attn, f"{calc_both:,}")
check("MLP の3層は attention の4層より重い（行列が大きいため）",
      calc_mlp > calc_attn, f"MLP {calc_mlp:,} > attention {calc_attn:,}")
del model, base
gc.collect()

# --- 3. アダプタを学習して保存する ------------------------------------------
print("\n=== 3. アダプタの学習と保存（r=8・12 step） ===")
set_seed(SEED)
model = attach_lora(load_model(FAST_MODEL), r=8, alpha=16)
stats_r8 = param_stats(model)
result = train(model, tokenizer, train_examples,
               TrainConfig(task="classify", batch_size=2, max_length=192,
                           max_steps=12, log_every=6, seed=SEED))
print(f"  {result.summary()}")
check("12 step 走った", result.steps == 12, f"{result.steps} step")
check("loss が NaN になっていない", all(x == x for x in result.losses))

adapter_classify = EXPORT / "adapter_classify"
adapter_classify.parent.mkdir(parents=True, exist_ok=True)
model.save_pretrained(adapter_classify)
files = sorted(p.name for p in adapter_classify.iterdir())
print(f"  保存されたファイル: {files}")
check("アダプタの重みと設定が保存されている",
      "adapter_model.safetensors" in files and "adapter_config.json" in files,
      str(files))
check("ベースモデルの重みは保存されない（アダプタだけ）",
      not any(name.startswith("model") and name.endswith(".safetensors")
              for name in files), str(files))

calc_mb = stats_r8["trainable"] * 4 / 1024 / 1024      # fp32 は 1 個 4 バイト
actual_mb = dir_size_mb(adapter_classify)
base_mb = (stats_r8["total"] - stats_r8["trainable"]) * 4 / 1024 / 1024
print(f"  学習対象 {stats_r8['trainable']:,} 個 / 計算 {calc_mb:.2f} MB / "
      f"実測 {actual_mb:.2f} MB / ベース(計算) {base_mb:.1f} MB")
check("r=8 の学習対象が 921,600 個", stats_r8["trainable"] == 921_600,
      f"{stats_r8['trainable']:,}")
check("アダプタのサイズが「学習対象 × 4 バイト」相当（誤差 10% 未満）",
      abs(actual_mb - calc_mb) / calc_mb < 0.10,
      f"計算 {calc_mb:.2f} MB vs 実測 {actual_mb:.2f} MB")
check("アダプタはベースより2桁小さい", base_mb / actual_mb > 100,
      f"ベースはアダプタの約 {base_mb / actual_mb:.0f} 倍")

# --- 4. 統合前後で出力が一致する --------------------------------------------
print("\n=== 4. merge_and_unload の統合前後で出力が一致する ===")
before = [generate(model, tokenizer, build_prompt(ex, "classify"), max_new_tokens=8)
          for ex in samples]
merged = model.merge_and_unload()          # 破壊的。アダプタは上で保存済み
after = [generate(merged, tokenizer, build_prompt(ex, "classify"), max_new_tokens=8)
         for ex in samples]
for ex, b, a in zip(samples, before, after):
    print(f"  {ex.id}  統合前={b!r}  統合後={a!r}")
check("統合前後で生成結果が完全一致する", before == after,
      f"{sum(1 for b, a in zip(before, after) if b == a)}/{len(samples)} 件一致")
lora_left = [name for name, _ in merged.named_modules() if "lora" in name.lower()]
check("統合後は LoRA 層が残っていない（素のモデルに戻っている）",
      not lora_left, f"{len(lora_left)} 個残っている")

if os.environ.get("SAVE_MERGED") == "1":
    merged_dir = save_merged(merged, tokenizer, "helpdesk-135m-r8")
    merged_mb = dir_size_mb(merged_dir)
    print(f"  統合済みモデル: {merged_mb:.1f} MB ({merged_dir})")
    check("統合はサイズを小さくしない（アダプタの100倍以上）",
          merged_mb > actual_mb * 100, f"{merged_mb:.1f} MB vs {actual_mb:.2f} MB")
else:
    print("  （SAVE_MERGED=1 を付けると統合済みモデル約 513MB も書き出します）")

del model, merged, result
gc.collect()

# --- 5. 2枚目のアダプタを作る（format タスク） ------------------------------
print("\n=== 5. 2枚目のアダプタ（format・8 step） ===")
set_seed(SEED)
model = attach_lora(load_model(FAST_MODEL), r=8, alpha=16)
train(model, tokenizer, train_examples,
      TrainConfig(task="format", batch_size=2, max_length=192,
                  max_steps=8, log_every=4, seed=SEED))
adapter_format = EXPORT / "adapter_format"
model.save_pretrained(adapter_format)
print(f"  -> {adapter_format}")
del model
gc.collect()

# --- 6. 1体のベースに2枚を載せて切り替える ----------------------------------
print("\n=== 6. 複数アダプタの切替 ===")
from peft import PeftModel  # noqa: E402


def active_names(peft_model) -> list[str]:
    """有効なアダプタ名を、peft の版差を吸収して取り出す。"""
    names = getattr(peft_model, "active_adapters", None)
    if callable(names):
        names = names()
    if names is None:
        names = peft_model.active_adapter
    return [names] if isinstance(names, str) else list(names)


base = load_model(FAST_MODEL)
multi = PeftModel.from_pretrained(base, adapter_classify, adapter_name="classify")
multi.load_adapter(adapter_format, adapter_name="format")
loaded = sorted(multi.peft_config)
print(f"  載っているアダプタ: {loaded}")
check("2枚のアダプタが1体のベースに載っている", loaded == ["classify", "format"],
      str(loaded))
check("読み込んだアダプタは既定で凍結されている（is_trainable=False）",
      param_stats(multi)["trainable"] == 0,
      f"trainable={param_stats(multi)['trainable']}")

multi.set_adapter("format")
print(f"  set_adapter('format') -> 有効={active_names(multi)}")
check("set_adapter で有効なアダプタが切り替わる",
      active_names(multi) == ["format"], str(active_names(multi)))
multi.set_adapter("classify")
check("classify に戻せる", active_names(multi) == ["classify"],
      str(active_names(multi)))

# 2枚の中身が本当に違うことを、重み（lora_B）の比較で確かめる
weights: dict[str, dict[str, torch.Tensor]] = {"classify": {}, "format": {}}
for name, param in multi.named_parameters():
    for adapter in weights:
        marker = f"lora_B.{adapter}."
        if marker in name:
            weights[adapter][name.replace(marker, "lora_B.")] = param.detach()
shared = sorted(set(weights["classify"]) & set(weights["format"]))
diffs = [float((weights["classify"][k] - weights["format"][k]).abs().max())
         for k in shared]
check("両アダプタに同じ数の lora_B がある", len(shared) > 0 and
      len(shared) == len(weights["classify"]) == len(weights["format"]),
      f"{len(shared)} 個")
check("2枚のアダプタの中身が違う（別のタスクで学習したため）",
      bool(diffs) and max(diffs) > 1e-8, f"最大差={max(diffs):.2e}" if diffs else "0 個")

with multi.disable_adapter():
    disabled = generate(multi, tokenizer, build_prompt(samples[0], "classify"),
                        max_new_tokens=8)
print(f"  アダプタ無効時の出力: {disabled!r}")
check("disable_adapter が例外なく使える", isinstance(disabled, str))

del multi, base
gc.collect()

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション6の検証はすべて成功しました。")
