#!/usr/bin/env python3
"""セッション2の自己検証：学習前の基準線（baseline）を測る。

このスクリプトは **学習しない**。素のモデル（ダウンロードしたまま・一度も
追加学習していないモデル）に指示を出して、

  - 正解率（accuracy）      … 区分を当てられたか
  - 形式遵守率（format_rate）… 決めた形で出せたか

を測り、`runs/baseline_{tag}.json` に残す。学習してよいかどうかは、
この基準線を持ってから判断する。

  python src/session02/verify.py                         # 既定（既定環境で数分）
  python src/session02/verify.py --fast-n 30 --ja-n 30   # 本文の表と同じ条件（時間がかかる）
  python src/session02/verify.py --skip-ja               # 0.5B を読まない（メモリが厳しいとき）

既定環境（CPU 2コア / メモリ 5.8GB）で終わるように件数を絞ってある。
モデルは1体ずつ読み、使い終わったら del と gc.collect() で必ず解放する
（5.8GB では 0.5B と 135M を同時に保持すると落ちることがある）。
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import torch  # noqa: E402

from ftkit.data import build_prompt, load  # noqa: E402
from ftkit.evaluate import FORMAT_RE, evaluate, extract_category, generate  # noqa: E402
from ftkit.models import FAST_MODEL, JA_MODEL, load_model, load_tokenizer  # noqa: E402

SANDBOX = Path(__file__).resolve().parents[2]
RUNS = SANDBOX / "runs"

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


ap = argparse.ArgumentParser(description="学習前の基準線を測る（学習はしない）")
ap.add_argument("--fast-n", type=int, default=10, help="SmolLM2-135M で評価する件数")
ap.add_argument("--ja-n", type=int, default=5,
                help="Qwen2.5-0.5B で評価する件数（1件あたり最大 48 トークン生成する）")
ap.add_argument("--ja-dtype", choices=["bf16", "fp32"], default="bf16",
                help="本文の表は bf16 で測っている。fp32 は CPU では速いがメモリを2倍使う")
ap.add_argument("--skip-ja", action="store_true", help="0.5B モデルを読まない")
ap.add_argument("--tag", default="session02")
args = ap.parse_args()

print("=" * 60)
print(" セッション2：学習前の基準線を測る（学習はしない）")
print("=" * 60)
print(f"Python {platform.python_version()} / torch {torch.__version__} / "
      f"{platform.machine()} / CPU {os.cpu_count()} コア / "
      f"OMP_NUM_THREADS={os.environ.get('OMP_NUM_THREADS', '未設定')}")

# --- 1. 指標の定義を確かめる（モデルを読まないので一瞬で終わる）---------------
# 「正解率」と「形式遵守率」は別の指標である。形式を守ったまま中身を間違える
# こともあれば、形式を崩したまま中身が合っていることもある。
# (正解の区分, モデルの出力, 形式に合っているか, 出力から取り出される区分)
CASES = [
    ("経費", "【区分】経費\n【担当】経理部\n【期限】3営業日以内", True, "経費"),
    ("勤怠", "【区分】勤怠\n【担当】人事部\n【期限】翌営業日\n【備考】ご確認ください",
     False, "勤怠"),
    ("PC", "ご不明な点がありましたらお知らせください。", False, "ご不明な点がありましたら"),
    ("アカウント", "【区分】セキュリティ\n【担当】情報システム部\n【期限】即日",
     True, "セキュリティ"),
    ("オフィス", "【区分】オフィス\n【担当】総務部", False, "オフィス"),
]

print("\n--- 1. 指標の定義（手計算と実装が一致するか）---")
definition_correct = definition_format_ok = 0
for gold, output, expected_format, expected_pred in CASES:
    predicted = extract_category(output)
    is_format = bool(FORMAT_RE.match(output.strip()))
    check(f"『{output.splitlines()[0]}』の判定",
          predicted == expected_pred and is_format == expected_format,
          f"取り出した区分={predicted!r} / 形式={is_format} / 正解={gold!r}")
    definition_correct += int(predicted == gold)
    definition_format_ok += int(is_format)

definition_accuracy = definition_correct / len(CASES)
definition_format_rate = definition_format_ok / len(CASES)
print(f"    5件の集計: 正解率={definition_accuracy:.3f} "
      f"形式遵守率={definition_format_rate:.3f}")
check("正解率と形式遵守率は別の指標である",
      abs(definition_accuracy - 0.6) < 1e-9 and abs(definition_format_rate - 0.4) < 1e-9,
      f"正解 {definition_correct}/5・形式一致 {definition_format_ok}/5")

# --- 2. 速いモデルの基準線（SmolLM2-135M / classify）--------------------------
examples = load("test")
check("test を読めた", len(examples) == 90, f"{len(examples)} 件")

print(f"\n--- 2. {FAST_MODEL} / classify / {args.fast_n} 件 / fp32 ---")
tokenizer = load_tokenizer(FAST_MODEL)
model = load_model(FAST_MODEL, dtype=torch.float32)
sample_fast = generate(model, tokenizer, build_prompt(examples[0], "classify"),
                       max_new_tokens=12)
print(f"学習前の出力（1件目 / 正解は「{examples[0].category}」）: {sample_fast!r}")

t0 = time.perf_counter()
fast_result = evaluate(model, tokenizer, examples, "classify", limit=args.fast_n)
fast_seconds = time.perf_counter() - t0
print(f"{fast_result.summary()}  （{fast_seconds:.1f}s）")

check("学習前でも空ではない出力が返る（指示そのものは届いている）",
      len(sample_fast.strip()) > 0, f"{len(sample_fast)} 文字")
check("学習前は区分名だけを返せていない（形式遵守率 < 1.000）",
      fast_result.format_rate < 1.0, f"形式遵守率={fast_result.format_rate:.3f}")
check("学習前の正解率に伸びしろがある（< 0.500）",
      fast_result.accuracy < 0.5, f"正解率={fast_result.accuracy:.3f}")

if args.fast_n >= 3:
    # do_sample=False（貪欲法）なので、同じモデル・同じ入力なら結果は毎回同じ。
    # 基準線が再現しないなら、それは基準線ではない。
    again = evaluate(model, tokenizer, examples[:3], "classify")
    check("同じ設定なら同じ結果になる（基準線は再現できる）",
          again.predictions == fast_result.predictions[:3],
          f"先頭3件の予測={[p for _, _, p in again.predictions]}")

del model
gc.collect()

# --- 3. 日本語モデルの基準線（Qwen2.5-0.5B / format）-------------------------
ja_record: dict | None = None
if args.skip_ja:
    print("\n--- 3. Qwen2.5-0.5B はスキップしました（--skip-ja）---")
else:
    print(f"\n--- 3. {JA_MODEL} / format / {args.ja_n} 件 / {args.ja_dtype} ---")
    print("（初回はモデルのダウンロードで数分かかります）")
    dtype = torch.bfloat16 if args.ja_dtype == "bf16" else torch.float32
    ja_tokenizer = load_tokenizer(JA_MODEL)
    ja_model = load_model(JA_MODEL, dtype=dtype)

    sample_ja = generate(ja_model, ja_tokenizer, build_prompt(examples[0], "format"),
                         max_new_tokens=48)
    print(f"学習前の出力（1件目 / 正解の区分は「{examples[0].category}」）:")
    for line in sample_ja.splitlines() or [""]:
        print(f"  | {line}")

    t0 = time.perf_counter()
    ja_result = evaluate(ja_model, ja_tokenizer, examples, "format", limit=args.ja_n)
    ja_seconds = time.perf_counter() - t0
    print(f"{ja_result.summary()}  （{ja_seconds:.1f}s）")

    check("指示は届いている（空ではない出力が返る）",
          len(sample_ja.strip()) > 0, f"{len(sample_ja)} 文字")
    check("しかし決めた形は守りきれない（形式遵守率 < 1.000）",
          ja_result.format_rate < 1.0, f"形式遵守率={ja_result.format_rate:.3f}")
    check("学習前の正解率に伸びしろがある（< 0.500）",
          ja_result.accuracy < 0.5, f"正解率={ja_result.accuracy:.3f}")

    ja_record = {
        "model": JA_MODEL, "task": "format", "dtype": args.ja_dtype,
        "n": ja_result.n, "accuracy": ja_result.accuracy,
        "format_rate": ja_result.format_rate, "seconds": round(ja_seconds, 1),
        "sample_output": sample_ja,
    }
    del ja_model
    gc.collect()

# --- 4. レポートに落とす（学習後の値と並べるための土台）----------------------
baselines = [{
    "model": FAST_MODEL, "task": "classify", "dtype": "fp32",
    "n": fast_result.n, "accuracy": fast_result.accuracy,
    "format_rate": fast_result.format_rate, "seconds": round(fast_seconds, 1),
    "sample_output": sample_fast,
}]
if ja_record:
    baselines.append(ja_record)

report = {
    "session": 2,
    "kind": "baseline",
    "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    "environment": {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "omp_num_threads": os.environ.get("OMP_NUM_THREADS", ""),
    },
    "definition_check": {"accuracy": definition_accuracy,
                         "format_rate": definition_format_rate},
    "baselines": baselines,
    "note": "学習前の値。学習後の値と必ず同じ条件で並べて報告する。",
}

RUNS.mkdir(parents=True, exist_ok=True)
path = RUNS / f"baseline_{args.tag}.json"
path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n-> runs/baseline_{args.tag}.json")

reloaded = json.loads(path.read_text(encoding="utf-8"))
check("レポートを読み直せる",
      reloaded["baselines"][0]["n"] == fast_result.n,
      f"{len(reloaded['baselines'])} 件の基準線を記録")
check("レポートに測定条件が入っている",
      all(reloaded["environment"].get(k) for k in ("python", "torch", "machine")),
      str(reloaded["environment"]))

print("\n--- 基準線（学習前）---")
print(f"{'モデル':<32}{'タスク':>10}{'件数':>6}{'正解率':>9}{'形式遵守率':>12}")
for row in baselines:
    print(f"{row['model']:<32}{row['task']:>10}{row['n']:>6}"
          f"{row['accuracy']:>9.3f}{row['format_rate']:>12.3f}")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション2の検証はすべて成功しました。")
print("この値を消さないこと。学習後の値と並べて初めて「効いたか」が言える。")
