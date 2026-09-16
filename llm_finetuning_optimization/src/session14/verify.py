#!/usr/bin/env python3
"""セッション14の自己検証：記録の欠落・データの版・モデルカード・環境の固定。

検証する主張（本文に書いた内容と1対1で対応させる）:
  1. runs/compare_*.json には max_length / batch_size / seed / 分割方式 が入らない
     （＝結果だけが残り、条件が残らない）。シードの設定位置もソースから点検できる
  2. TrainConfig の全フィールドは asdict で取れる。だから1行足せば条件は埋まる。
     ただし split（データの分割方式）は TrainConfig に無いので別に記録する
  3. データの版は sha256 で固定できる。make_dataset.py は決定的なので2回実行しても同じ
  4. モデルカードの必須9項目をチェッカーで機械的に検査できる
  5. 環境（Python・torch・プラットフォーム・スレッド数）を記録でき、latest 依存を弾ける

**モデルの重みを読まない。学習もしない。** 数秒で終わる。

  python src/session14/verify.py
  SKIP_REGEN=1 python src/session14/verify.py   # データの再生成（決定性の確認）を飛ばす
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from repro import (  # noqa: E402
    COND_EXPERIMENT, COND_REQUIRED, DATA_FILES, EXAMPLE_CARD, MODEL_CARD_ITEMS,
    PATTERN_FILES, SCHEMA, TRAINCONFIG_FIELDS, audit_pinning, audit_runs,
    audit_seed_placement, check_model_card, combined_digest, data_version, drop_lines,
    env_record, file_digest, is_cpu_wheel, mid01_required_conditions, missing_conditions,
    missing_env, record_keys_in_source, thin_conditions, upgrade_record,
)

from ftkit.train import TrainConfig  # noqa: E402

SANDBOX = Path(__file__).resolve().parents[2]
RUNS = SANDBOX / "runs"
OUT = RUNS / "session14"

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> bool:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)
    return cond


# tools/train_and_eval.py が runs/compare_{tag}.json に書き出す記録（実物と同じキー）。
# 値は 2026-08-15 実測（Qwen2.5-0.5B / format / 80 step / bf16 / test 30件）。
TOOL_RECORD = {
    "model": "Qwen/Qwen2.5-0.5B-Instruct", "dtype": "bf16", "task": "format", "steps": 80,
    "lora_r": 16, "lr": 2e-4, "eval_n": 30,
    "trainable_params": 2_163_000, "total_params": 496_200_000,
    "median_step_seconds": 7.27, "train_seconds": 664.6, "peak_rss_gb": 2.29,
    "first_loss": 1.5290, "last_loss": 0.0447,
    "before": {"accuracy": 0.033, "format_rate": 0.300},
    "after": {"accuracy": 0.833, "format_rate": 1.000},
}

SEED_OK_SRC = """
from ftkit.models import attach_lora, load_model
from ftkit.train import TrainConfig, set_seed, train

set_seed(20260815)                      # モデル構築の前に固定する
model = attach_lora(load_model(JA_MODEL), r=16)
"""

SEED_LATE_SRC = """
from ftkit.models import attach_lora, load_model
from ftkit.train import TrainConfig, set_seed, train

model = attach_lora(load_model(JA_MODEL), r=16)
set_seed(20260815)                      # 遅い。LoRA の初期化はもう終わっている
"""

# ---------------------------------------------------------------------------
# 1. 実験記録に何が入っていないか
# ---------------------------------------------------------------------------
print("=== 1. 実験記録の欠落（結果だけ残して条件を残さない）===")

tool_path = SANDBOX / "tools" / "train_and_eval.py"
tool_src = tool_path.read_text(encoding="utf-8")
keys = record_keys_in_source(tool_src)
if check("tools/train_and_eval.py の記録しているキーをソースから取り出せた", keys is not None):
    print(f"  記録しているキー（{len(keys)} 個）: {', '.join(sorted(keys))}")
    for name in ("max_length", "batch_size", "seed", "split"):
        print(f"    {name:<12}: {'記録あり' if name in keys else '**記録なし**'}")
    print("  （自分で直したあとに実行すると『記録あり』に変わります）")

missing = missing_conditions(TOOL_RECORD)
print(f"  見本の記録に足りない条件: {missing}")
check("欠落チェッカーが4項目を検出する（max_length / batch_size / seed / split）",
      missing == ["max_length", "batch_size", "seed", "split"], str(missing))
check("入っている条件は誤検出しない（model / task / steps / lora_r / dtype）",
      all(key not in missing for key in ("model", "task", "steps", "lora_r", "dtype")))
check("推奨項目の不足も分かる（lora_alpha / grad_accum / epochs / target_modules）",
      thin_conditions(TOOL_RECORD) == ["lora_alpha", "grad_accum", "epochs", "target_modules"],
      str(thin_conditions(TOOL_RECORD)))
check("結果（loss と正解率）はちゃんと残っている＝欠けているのは条件だけ",
      TOOL_RECORD["last_loss"] == 0.0447 and TOOL_RECORD["after"]["accuracy"] == 0.833)

mid01 = mid01_required_conditions()
check("中間プロジェクト1が要求している条件と同じ定義を使っている", mid01 == COND_EXPERIMENT,
      str(mid01))
check("本章の要求（9項目）は中間プロジェクト1の要求（8項目）を含む",
      set(COND_EXPERIMENT) <= set(COND_REQUIRED) and len(COND_REQUIRED) == 9)

print("\n--- runs/compare_*.json の監査（無ければスキップ）---")
rows = audit_runs()
if not rows:
    print("  runs/compare_*.json がまだありません。")
    print("  例: python tools/train_and_eval.py --model fast --steps 20 --eval-n 10")
else:
    print("| ファイル | キー数 | 足りない条件 | 推奨項目の不足 |")
    print("| :--- | --: | :--- | :--- |")
    for row in rows:
        print(f"| {row['name']} | {row.get('keys', '-')} | "
              f"{', '.join(row['missing']) or 'なし'} | "
              f"{', '.join(row['thin']) or 'なし'} |")
    incomplete = [row for row in rows if row["missing"]]
    print(f"  {len(rows)} 件のうち {len(incomplete)} 件に条件の欠落があります。")
    check("すべての記録を読んで監査できた", all("error" not in row for row in rows),
          str([row for row in rows if "error" in row]))
    if not incomplete:
        print("  すべての記録に条件が揃っています（記録の作り直しができています）。")

print("\n--- シードの設定位置（ソースを読むだけで分かる）---")
check("モデル構築の前に set_seed を呼ぶ書き方は問題なしと判定される",
      audit_seed_placement(SEED_OK_SRC) == [], str(audit_seed_placement(SEED_OK_SRC)))
check("モデル構築の後で呼ぶ書き方を検出する",
      audit_seed_placement(SEED_LATE_SRC) == ["set_seed の呼び出しがモデル構築より後ろにある"],
      str(audit_seed_placement(SEED_LATE_SRC)))
check("import も呼び出しも無い書き方を検出する",
      audit_seed_placement("model = load_model(JA_MODEL)\n")
      == ["set_seed を import していない", "set_seed を呼んでいない"])
print(f"  tools/train_and_eval.py の点検結果: {audit_seed_placement(tool_src)}")
print("  （シードの位置を間違えると LoRA の初期化が再現せず、loss 列が最大 3.2e-2 ずれます。"
      "正しい位置なら最大差 0.00e+00・2026-08-15 実測）")

# ---------------------------------------------------------------------------
# 2. TrainConfig の全フィールド（1行足せば条件が埋まる）
# ---------------------------------------------------------------------------
print("\n=== 2. TrainConfig を記録に流し込む ===")

config = asdict(TrainConfig(task="format", batch_size=2, lr=2e-4, max_length=192, max_steps=80))
print("  asdict(TrainConfig(...)) = " + json.dumps(config, ensure_ascii=False))
check(f"TrainConfig の全フィールドが asdict で取れる（{len(TRAINCONFIG_FIELDS)} 項目）",
      sorted(config) == sorted(TRAINCONFIG_FIELDS), str(sorted(config)))
check("欠けていた max_length / batch_size / seed は config に入っている",
      all(key in config for key in ("max_length", "batch_size", "seed")))
check("split は TrainConfig に無い（分割方式は学習設定ではないので別に記録する）",
      "split" not in config)

env = env_record()
version_map = data_version()
upgraded = upgrade_record(TOOL_RECORD, config, split="pattern", run_id="exp-05-format-bf16",
                          environment=env, data_version_map=version_map)
print("  作り直した記録の条件: " + json.dumps(upgraded["conditions"], ensure_ascii=False))
check("作り直した記録に条件の欠落がない", missing_conditions(upgraded) == [],
      str(missing_conditions(upgraded)))
check("中間プロジェクト1の要求（8項目）も満たす",
      missing_conditions(upgraded, COND_EXPERIMENT) == [])
check("推奨項目で残るのは LoRA 側の2つだけ（自分で足す）",
      thin_conditions(upgraded) == ["lora_alpha", "target_modules"],
      str(thin_conditions(upgraded)))
check("結果は元の記録から失われていない",
      upgraded["results"]["after"]["accuracy"] == 0.833
      and upgraded["results"]["first_loss"] == 1.5290)
check("スキーマ名と run_id が入っている",
      upgraded["schema"] == SCHEMA and upgraded["run_id"] == "exp-05-format-bf16")
check("環境とデータの版が記録に埋まっている",
      bool(upgraded["environment"].get("torch")) and isinstance(upgraded["data_version"], dict))

OUT.mkdir(parents=True, exist_ok=True)
example_path = OUT / "example_record.json"
example_path.write_text(json.dumps(upgraded, ensure_ascii=False, indent=2), encoding="utf-8")
check("記録が JSON として保存でき、読み戻せる",
      json.loads(example_path.read_text(encoding="utf-8")) == upgraded,
      f"runs/session14/{example_path.name}")

# ---------------------------------------------------------------------------
# 3. データの版（sha256 で固定する）
# ---------------------------------------------------------------------------
print("\n=== 3. データの版（sha256 の先頭12桁）===")

if not version_map:
    check("data/*.jsonl がある", False,
          "先に python tools/make_dataset.py を実行してください")
else:
    for name, info in version_map.items():
        print(f"  {name:<20} {info['lines']:>4} 件  sha256:{info['sha256_12']}")
    print(f"  まとめた版（4ファイルのハッシュのハッシュ）: {combined_digest(version_map)}")
    check("4つのデータファイルすべての版が取れた", sorted(version_map) == sorted(DATA_FILES),
          str(sorted(version_map)))
    counts = {name: info["lines"] for name, info in version_map.items()}
    canonical = counts == {"train.jsonl": 720, "valid.jsonl": 90,
                           "test.jsonl": 90, "preference.jsonl": 200}
    check("件数が 720 / 90 / 90 / 200（素のランダム分割）", canonical,
          str(counts) if canonical else
          f"{counts}（python tools/make_dataset.py で戻してから実行してください）")
    check("まとめた版は12桁の16進数", len(combined_digest(version_map)) == 12
          and all(c in "0123456789abcdef" for c in combined_digest(version_map)))
    check("同じ入力なら何度呼んでも同じ版になる",
          combined_digest(version_map) == combined_digest(data_version()))

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "digest_a.txt").write_text("abc\n", encoding="utf-8")
    (OUT / "digest_b.txt").write_text("abd\n", encoding="utf-8")
    check("1文字違えばハッシュは変わる",
          file_digest(OUT / "digest_a.txt") != file_digest(OUT / "digest_b.txt"))
    check("ハッシュは中身だけで決まる（ファイル名に依存しない）",
          file_digest(OUT / "digest_a.txt") == hashlib.sha256(b"abc\n").hexdigest()[:12])

    if os.environ.get("SKIP_REGEN") == "1":
        print("  SKIP_REGEN=1 のためデータの再生成（決定性の確認）は飛ばします。")
    elif not canonical:
        print("  データが素の分割でないため、再生成による決定性の確認は飛ばします。")
    else:
        proc = subprocess.run([sys.executable, "tools/make_dataset.py"], cwd=str(SANDBOX),
                              capture_output=True, text=True)
        check("tools/make_dataset.py が正常終了する", proc.returncode == 0,
              (proc.stderr or "").strip()[-200:])
        after = data_version()
        changed = [name for name, info in version_map.items()
                   if after.get(name, {}).get("sha256_12") != info["sha256_12"]]
        check("2回実行しても全ファイルのハッシュが同じ（生成が決定的）", changed == [],
              f"変わったファイル: {changed}")
        check("まとめた版も変わらない", combined_digest(after) == combined_digest(version_map))

    pattern_map = data_version(names=PATTERN_FILES)
    if not pattern_map:
        print("  data/*_pattern.jsonl がありません"
              "（python src/session03/split_by_pattern.py で作れます）")
    else:
        for name, info in pattern_map.items():
            print(f"  {name:<20} {info['lines']:>4} 件  sha256:{info['sha256_12']}")
        check("型単位の分割は 600 / 150 / 150",
              [pattern_map[n]["lines"] for n in PATTERN_FILES if n in pattern_map]
              == [600, 150, 150],
              str({n: pattern_map[n]["lines"] for n in pattern_map}))
        check("同じ data/ でも分割方式が違えば版が違う（だから split を記録する）",
              pattern_map["train_pattern.jsonl"]["sha256_12"]
              != version_map["train.jsonl"]["sha256_12"])
        check("2つの分割をまとめた版も別の値になる",
              combined_digest(pattern_map) != combined_digest(version_map))

# ---------------------------------------------------------------------------
# 4. モデルカードの必須項目
# ---------------------------------------------------------------------------
print("\n=== 4. モデルカードの必須9項目 ===")

print(f"  必須項目: {', '.join(label for label, _ in MODEL_CARD_ITEMS)}")
check("必須項目は9項目ある", len(MODEL_CARD_ITEMS) == 9, f"{len(MODEL_CARD_ITEMS)} 項目")
check("記入例は9項目すべてを満たす", check_model_card(EXAMPLE_CARD) == [],
      str(check_model_card(EXAMPLE_CARD)))
check("空のカードでは9項目すべてが欠落として挙がる",
      len(check_model_card("# モデルカード\n")) == 9)

# 項目ごとに「その記述を落とすと検出できるか」を確かめる
for label, keyword in (
    ("モデル名", "モデル名"),
    ("ベースモデルとライセンス", "ライセンス"),
    ("データの版", "sha256"),
    ("ハイパーパラメータ", "max_length"),
    ("シード", "20260815"),
    ("環境", "torch"),
    ("評価結果", "正解率"),
    ("既知の限界", "既知の限界"),
    ("配布形式", "配布形式"),
):
    degraded = drop_lines(EXAMPLE_CARD, keyword)
    check(f"「{label}」が抜けたカードを検出する（{keyword} の行を落とした）",
          label in check_model_card(degraded), str(check_model_card(degraded)))

print("  記入例に書かれている数値（2026-08-15 実測）:")
for line in EXAMPLE_CARD.splitlines():
    if "正解率" in line or "loss" in line:
        print(f"    {line.strip()}")

cards = sorted(p for p in SANDBOX.glob("**/MODELCARD.md") if ".git" not in p.parts)
if not cards:
    print("  MODELCARD.md がまだありません（練習問題で書いたら、ここで点検されます）。")
else:
    for path in cards:
        lacking = check_model_card(path.read_text(encoding="utf-8"))
        print(f"  {path.relative_to(SANDBOX)}: "
              f"{'9項目そろっています' if not lacking else '足りない項目 → ' + ', '.join(lacking)}")

# ---------------------------------------------------------------------------
# 5. 環境の記録とバージョンの固定
# ---------------------------------------------------------------------------
print("\n=== 5. 環境の記録とバージョンの固定 ===")

for key, value in env.items():
    print(f"  {key:<16}: {value}")
check("環境の必須項目がそろっている（Python・プラットフォーム・スレッド数・主要ライブラリ）",
      missing_env(env) == [], f"欠け: {missing_env(env)}")
check("torch が CPU 専用 wheel（+cpu）である", is_cpu_wheel(env["torch"]), str(env["torch"]))
check("素の PyPI 版（+cpu が付かない）は CPU 専用 wheel と判定しない",
      not is_cpu_wheel("2.13.0") and is_cpu_wheel("2.13.0+cpu") and not is_cpu_wheel(None))

dockerfile = (SANDBOX / "Dockerfile").read_text(encoding="utf-8")
requirements = (SANDBOX / "requirements.txt").read_text(encoding="utf-8")
compose = (SANDBOX / "docker-compose.yml").read_text(encoding="utf-8")
audit = audit_pinning(dockerfile, requirements, compose)
check("このサンドボックスに latest 依存もバージョン未固定も無い", audit["problems"] == [],
      str(audit["problems"]))
for text in audit["notes"]:
    print(f"  注意: {text}")

bad = audit_pinning("FROM python:latest\n", "transformers\n")
check("latest とバージョン未固定を検出する",
      any("latest" in p for p in bad["problems"])
      and any("固定されていない" in p for p in bad["problems"]), str(bad["problems"]))
naive = audit_pinning("FROM python:3.12-slim\nENV HF_HOME=/models\n", "torch==2.13.0\n")
check("CPU 専用 wheel でない torch を弾く（イメージ 8.85GB 対 2.05GB の差になる）",
      any("CPU 専用 wheel でない" in p for p in naive["problems"]), str(naive["problems"]))
check("HF_HOME を固定していない Dockerfile を弾く（モデルの取得先が環境で変わる）",
      any("HF_HOME" in p for p in audit_pinning("FROM python:3.12-slim\n", "")["problems"]))

# ---------------------------------------------------------------------------
print()
if failures:
    print(f"{len(failures)} 件の検証に失敗しました:")
    for label in failures:
        print(f"  - {label}")
    sys.exit(1)
print("セッション14の検証はすべて成功しました。")
print("記録・データの版・モデルカード・環境の固定が、機械で点検できる形になっています。")
