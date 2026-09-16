#!/usr/bin/env python3
"""中間プロジェクト1（社内文体に合わせる LoRA）の提出物を機械的に点検する。

  docker compose exec app python src/mid01/verify.py
  docker compose exec app python src/mid01/verify.py --dir runs/mid01 --min-experiments 4

**モデルを読まない・学習しない。** 記録された JSON と提出物の Markdown を読むだけなので
数秒で終わる。点検するのは「他人が再現できる記録になっているか」であって、指標の高さは
採点しない（正解率が高いことは合格条件ではない）。

点検項目:
  1. runs/mid01/ に実験記録の JSON が 4 件以上ある
  2. 学習前の基準線（kind="baseline"）の記録がある
  3. 各記録が条件（モデル・タスク・step 数・r・max_length・dtype・シード・分割方式）と
     結果（loss の始点と終点・正解率・形式遵守率）を持っている
  4. 実験記録の中に「モデルを変えた条件」が含まれている
  5. 条件の変更が1つずつ追える（changed_from / changed_field が実際の差分と一致する）
  6. 混同表が保存されている
  7. 5点の提出物が揃っていて、再現手順にバージョン・シード・データの版が書かれている

1つでも満たしていなければ非0で終了する。まだ何も提出していない状態では
「提出物がまだありません」と分かる出力になる。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SANDBOX = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SANDBOX))

from ftkit.data import CATEGORIES  # noqa: E402  （data.py は torch を読まないので一瞬）

SCHEMA = "mid01-experiment/1"

# 実験記録に必ず入っていなければならない条件（本章の要件）
COND_EXPERIMENT = ["model", "task", "steps", "lora_r", "max_length", "dtype", "seed", "split"]
# 基準線（学習前）は step も r も無いので、要求する条件が少し違う
COND_BASELINE = ["model", "task", "max_length", "dtype", "seed", "split", "eval_n"]
# 無くても落とさないが、無いと後から条件を再現できない項目
COND_RECOMMENDED = ["lora_alpha", "lr", "batch_size", "grad_accum", "eval_n", "target_modules"]

# 5点の提出物（runs/mid01/reports/ に置く）
REPORTS = {
    "01-data-design.md": "データ設計メモ（分割方式と汚染対策）",
    "02-experiments.md": "実験記録（条件と結果の表）",
    "03-eval-report.md": "before/after の評価レポート",
    "04-failure-analysis.md": "混同表と失敗ケースの分析",
    "05-reproduce.md": "再現手順",
}

# 再現手順に書かれていなければならない情報（バージョン・シード・データの版）
REPRODUCE_MARKERS = [
    ("torch のバージョン", r"torch\D{0,14}2\.13\.0\+cpu"),
    ("transformers のバージョン", r"transformers\D{0,14}4\.57\.6"),
    ("peft のバージョン", r"peft\D{0,14}0\.20\.0"),
    ("シード", r"20260815"),
    ("データの版（生成）", r"make_dataset\.py"),
    ("データの版（分割）", r"split_by_pattern\.py"),
    ("起動コマンド", r"docker compose"),
]

failures: list[str] = []
notes: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> bool:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)
    return cond


def note(text: str) -> None:
    print(f"   ・{text}")
    notes.append(text)


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def dig(record: dict, path: str):
    """'results.before.accuracy' のようなパスで値を取り出す（無ければ None）。"""
    current = record
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def diff_conditions(base: dict, child: dict) -> list[str]:
    """2つの条件の差分（値が違うキー）を返す。片方に無いキーも差分として扱う。"""
    return [k for k in sorted(set(base) | set(child)) if base.get(k) != child.get(k)]


def as_list(value) -> list:
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}" if abs(value) < 100 else f"{value:.1f}"
    if isinstance(value, list):
        return "/".join(str(v) for v in value)
    return str(value)


# ---------------------------------------------------------------------------
# 引数と入力
# ---------------------------------------------------------------------------
ap = argparse.ArgumentParser(description="中間プロジェクト1の提出物を点検する（学習しない）")
ap.add_argument("--dir", default="runs/mid01", help="実験記録を置いたディレクトリ")
ap.add_argument("--min-experiments", type=int, default=4, help="必要な実験条件の数")
args = ap.parse_args()

root = Path(args.dir)
if not root.is_absolute():
    root = SANDBOX / root
reports_dir = root / "reports"

print("=" * 66)
print(" 中間プロジェクト1：提出物の点検（モデルを読まない・数秒で終わる）")
print("=" * 66)
print(f"記録の場所: {root}")

paths = sorted(p for p in root.glob("*.json")) if root.exists() else []
if not paths:
    print("\n提出物がまだありません。")
    print(f"  1. mkdir -p {args.dir}/reports")
    print("  2. python tools/make_dataset.py && python src/session03/split_by_pattern.py")
    print("  3. 基準線を1本測って runs/mid01/*.json に記録する（kind=\"baseline\"）")
    print("  4. 条件を1つずつ変えた実験を4本以上記録する（kind=\"experiment\"）")
    print("\n点検できる記録が0件なので、要件を満たしていません。")
    sys.exit(1)

records: dict[str, dict] = {}
for path in paths:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        check(f"{path.name} が JSON として読める", False, str(exc))
        continue
    if not isinstance(record, dict):
        check(f"{path.name} が1件の記録（オブジェクト）である", False, type(record).__name__)
        continue
    run_id = record.get("run_id") or path.stem
    if run_id in records:
        check(f"run_id が重複していない（{run_id}）", False, f"{path.name} と重複")
        continue
    records[run_id] = record

print(f"読み込んだ記録: {len(records)} 件（{', '.join(sorted(records))}）")

# ---------------------------------------------------------------------------
# 1. スキーマと種別
# ---------------------------------------------------------------------------
print("\n=== 1. 記録の形式 ===")
for run_id, record in sorted(records.items()):
    check(f"{run_id}: schema が {SCHEMA}", record.get("schema") == SCHEMA,
          str(record.get("schema")))
    check(f"{run_id}: kind が baseline か experiment",
          record.get("kind") in ("baseline", "experiment"), str(record.get("kind")))
    check(f"{run_id}: conditions と results がある",
          isinstance(record.get("conditions"), dict) and isinstance(record.get("results"), dict))

baselines = {k: v for k, v in records.items() if v.get("kind") == "baseline"}
experiments = {k: v for k, v in records.items() if v.get("kind") == "experiment"}

# ---------------------------------------------------------------------------
# 2. 件数（基準線1本以上・実験4本以上）
# ---------------------------------------------------------------------------
print("\n=== 2. 記録の件数 ===")
check("学習前の基準線がある（kind=\"baseline\"）", len(baselines) >= 1,
      f"{len(baselines)} 件（{', '.join(sorted(baselines)) or 'なし'}）")
check(f"実験条件が {args.min_experiments} 件以上ある", len(experiments) >= args.min_experiments,
      f"{len(experiments)} 件")

# ---------------------------------------------------------------------------
# 3. 条件と結果が揃っている
# ---------------------------------------------------------------------------
print("\n=== 3. 条件と結果 ===")
for run_id, record in sorted(records.items()):
    conditions = record.get("conditions") if isinstance(record.get("conditions"), dict) else {}
    baseline = record.get("kind") == "baseline"
    required = COND_BASELINE if baseline else COND_EXPERIMENT
    missing = [k for k in required if conditions.get(k) in (None, "")]
    check(f"{run_id}: 条件が揃っている（{'/'.join(required)}）", not missing,
          f"欠け: {', '.join(missing)}" if missing else "")
    thin = [k for k in COND_RECOMMENDED if k not in conditions]
    if thin:
        note(f"{run_id}: 推奨項目が未記入（{', '.join(thin)}）— 後から条件を再現しにくくなります")

    if not baseline:
        check(f"{run_id}: steps が 1 以上", is_number(conditions.get("steps"))
              and conditions.get("steps") >= 1, fmt(conditions.get("steps")))
        check(f"{run_id}: lora_r が 1 以上", is_number(conditions.get("lora_r"))
              and conditions.get("lora_r") >= 1, fmt(conditions.get("lora_r")))
        check(f"{run_id}: dtype が fp32 か bf16", conditions.get("dtype") in ("fp32", "bf16"),
              str(conditions.get("dtype")))

    # 結果：loss の始点と終点（基準線は学習しないので不要）／before と after の指標
    wanted = ["before.accuracy", "before.format_rate"]
    if not baseline:
        wanted += ["first_loss", "last_loss", "after.accuracy", "after.format_rate"]
    bad = [p for p in wanted if not is_number(dig(record, "results." + p))]
    check(f"{run_id}: 結果が揃っている（{'/'.join(wanted)}）", not bad,
          f"欠け: {', '.join(bad)}" if bad else "")
    for path in ("first_loss", "last_loss"):
        value = dig(record, "results." + path)
        if is_number(value) and value != value:  # NaN
            note(f"{run_id}: {path} が NaN です。全マスク（採点対象が無い）か"
                 "学習率が大きすぎる可能性があります（セッション4・7）")

    for path in ("environment.torch", "environment.python", "data_version"):
        if dig(record, path) in (None, "", {}):
            check(f"{run_id}: {path} が記録されている", False, "未記録")

# ---------------------------------------------------------------------------
# 4. モデルを変えた条件が含まれている
# ---------------------------------------------------------------------------
print("\n=== 4. 比較の広さ ===")
models = sorted({str(dig(r, "conditions.model")) for r in experiments.values()})
check("実験記録にモデルを変えた条件が含まれている（2種類以上）", len(models) >= 2,
      " / ".join(models) if models else "なし")
for field in ("task", "split", "lora_r", "max_length", "dtype", "lr", "steps"):
    values = {json.dumps(dig(r, f"conditions.{field}"), ensure_ascii=False)
              for r in experiments.values()}
    if len(values) >= 2:
        note(f"{field} も振っています（{len(values)} 通り）")

# ---------------------------------------------------------------------------
# 5. 変更の連鎖（1つずつ変えた記録になっているか）
# ---------------------------------------------------------------------------
print("\n=== 5. 変更の連鎖（1条件ずつ変えているか）===")
origins = [k for k, v in experiments.items() if not v.get("changed_from")]
check("連鎖の起点がある（changed_from を持たない実験が1件以上）", len(origins) >= 1,
      " / ".join(origins) if origins else "全記録が changed_from を持っています")
if len(origins) > 1:
    note(f"起点が {len(origins)} 本あります（{' / '.join(origins)}）。"
         "比較の枝が分かれているので、評価レポートでどの枝の話かを明示してください")

for run_id, record in sorted(experiments.items()):
    parent_id = record.get("changed_from")
    if not parent_id:
        continue
    parent = records.get(parent_id)
    if not check(f"{run_id}: changed_from が実在する記録を指している", parent is not None,
                 f"changed_from={parent_id!r}"):
        continue
    declared = [str(x) for x in as_list(record.get("changed_field"))]
    actual = [k for k in diff_conditions(parent.get("conditions") or {},
                                         record.get("conditions") or {})]
    check(f"{run_id}: changed_field が実際の差分と一致する（対 {parent_id}）",
          sorted(declared) == sorted(actual),
          f"宣言={declared or 'なし'} / 実際={actual or 'なし'}")
    if len(actual) >= 2:
        check(f"{run_id}: 2項目以上を同時に変えた理由が notes に書かれている",
              bool(str(record.get("notes") or "").strip()),
              f"同時に変えた項目: {', '.join(actual)}")

# 連鎖をたどって循環していないか（辿れない記録は再現の手順が復元できない）
for run_id in sorted(experiments):
    seen = [run_id]
    cursor = experiments[run_id].get("changed_from")
    while cursor and cursor in records and cursor not in seen:
        seen.append(cursor)
        cursor = records[cursor].get("changed_from")
    if cursor in seen:
        check(f"{run_id}: 連鎖が循環していない", False, " -> ".join(seen + [str(cursor)]))

# ---------------------------------------------------------------------------
# 6. 混同表
# ---------------------------------------------------------------------------
print("\n=== 6. 混同表 ===")
with_confusion: list[str] = []
for run_id, record in sorted(records.items()):
    confusion = record.get("confusion")
    if not isinstance(confusion, dict) or not confusion:
        continue
    problems: list[str] = []
    if sorted(confusion) != sorted(CATEGORIES):
        problems.append(f"行が6区分と一致しない（{', '.join(sorted(confusion))}）")
    total = 0
    for gold, row in confusion.items():
        if not isinstance(row, dict):
            problems.append(f"{gold} の行が表になっていない")
            continue
        for predicted, count in row.items():
            if not is_number(count):
                problems.append(f"{gold}→{predicted} が数値でない")
            else:
                total += count
    eval_n = dig(record, "conditions.eval_n")
    if is_number(eval_n) and total != eval_n:
        problems.append(f"合計 {total} が eval_n={eval_n} と一致しない")
    if check(f"{run_id}: 混同表の形式が正しい", not problems, " / ".join(problems)):
        with_confusion.append(run_id)
check("少なくとも1件の記録に混同表が保存されている", bool(with_confusion),
      " / ".join(with_confusion) if with_confusion else "1件もありません")

# ---------------------------------------------------------------------------
# 7. 提出物（5点）と再現手順の中身
# ---------------------------------------------------------------------------
print("\n=== 7. 提出物 ===")
for name, label in REPORTS.items():
    path = reports_dir / name
    exists = path.exists() and path.read_text(encoding="utf-8").strip() != ""
    size = len(path.read_text(encoding="utf-8")) if path.exists() else 0
    check(f"{label} がある（reports/{name}）", exists, f"{size} 文字")

reproduce = reports_dir / "05-reproduce.md"
if reproduce.exists():
    text = reproduce.read_text(encoding="utf-8")
    missing = [label for label, pattern in REPRODUCE_MARKERS
               if not re.search(pattern, text, re.IGNORECASE)]
    check("再現手順にバージョン・シード・データの版が揃っている", not missing,
          f"欠け: {', '.join(missing)}" if missing else "")
    ids_in_doc = [run_id for run_id in records if run_id in text]
    check("再現手順が実験記録の run_id に言及している", bool(ids_in_doc),
          f"{len(ids_in_doc)}/{len(records)} 件に言及")

# ---------------------------------------------------------------------------
# 記録の一覧（そのまま 02-experiments.md に貼れる Markdown 表）
# ---------------------------------------------------------------------------
print("\n=== 記録の一覧（02-experiments.md に貼れます）===")
header = ("| run_id | 種別 | 変更点 | モデル | task | split | step | r | ml | dtype | "
          "seed | loss 始→終 | 正解率 前→後 | 形式遵守率 前→後 |")
print(header)
print("| :--- | :--- | :--- | :--- | :--- | :--- | --: | --: | --: | :--- | --: | :--- | :--- | :--- |")
for run_id, record in sorted(records.items()):
    c = record.get("conditions") or {}
    changed = "/".join(str(x) for x in as_list(record.get("changed_field"))) or "起点"
    model = str(c.get("model", "-")).split("/")[-1]
    loss = f"{fmt(dig(record, 'results.first_loss'))} → {fmt(dig(record, 'results.last_loss'))}"
    acc = (f"{fmt(dig(record, 'results.before.accuracy'))} → "
           f"{fmt(dig(record, 'results.after.accuracy'))}")
    fr = (f"{fmt(dig(record, 'results.before.format_rate'))} → "
          f"{fmt(dig(record, 'results.after.format_rate'))}")
    print(f"| {run_id} | {record.get('kind', '-')} | {changed} | {model} | "
          f"{c.get('task', '-')} | {c.get('split', '-')} | {fmt(c.get('steps'))} | "
          f"{fmt(c.get('lora_r'))} | {fmt(c.get('max_length'))} | {c.get('dtype', '-')} | "
          f"{fmt(c.get('seed'))} | {loss} | {acc} | {fr} |")

print("\n=== 変更の連鎖 ===")
for run_id, record in sorted(experiments.items()):
    chain = [run_id]
    cursor = record.get("changed_from")
    while cursor and cursor in records and cursor not in chain:
        chain.append(cursor)
        cursor = records[cursor].get("changed_from")
    trail = " <- ".join(chain)
    print(f"  {trail}  （変更点: "
          f"{'/'.join(str(x) for x in as_list(record.get('changed_field'))) or '起点'}）")

# ---------------------------------------------------------------------------
print()
if notes:
    print(f"注意（要件ではないが確認する価値がある点）: {len(notes)} 件")
if failures:
    print(f"{len(failures)} 件の要件を満たしていません:")
    for label in failures:
        print(f"  - {label}")
    print("\n指標の高さは点検していません。足りないのは「記録」です。")
    sys.exit(1)

print("提出物の要件をすべて満たしています。")
print("ただしこの点検は形式だけを見ています。結論に根拠があるか（なぜその値になったのかを"
      "説明できるか）は、評価レポートを自分で読み返して確かめてください。")
