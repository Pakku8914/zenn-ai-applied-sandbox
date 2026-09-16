#!/usr/bin/env python3
"""中間プロジェクト2（小型モデルを実用水準にする）の提出物を機械的に点検する。

  docker compose exec app python src/mid02/verify.py
  docker compose exec app python src/mid02/verify.py --dir runs/mid02 --min-configs 4

**モデルを読まない・学習しない・生成しない。** 記録された JSON と提出物の Markdown を
読むだけなので数秒で終わる。点検するのは「他人がこの記録だけで採否の判断を追えるか」で
あって、指標の高さでも小ささでもない（正解率が高いこと・サイズが小さいことは合格条件では
ない）。

点検項目:
  0. 先に宣言した基準（runs/mid02/requirements.json）がある。**無ければここで終わる**
     ― 許容できる劣化・目標サイズ・目標速度が数字で、かつ根拠付きで書かれていること
  1. 各構成の記録が「サイズ・速度・精度」の3点をそろえて持っている
  2. 少なくとも3構成を比べている（手段が2種類以上）
  3. 基準の宣言が測定より前の時刻になっている（結果を見てから基準を書いていない）
  4. 要求を満たす構成がどれかを機械的に判定する（判定は情報。落とすのは記録の不備だけ）
  5. 評価件数から言える差の下限を計算する
  6. 判断記録（runs/mid02/decision.json）の採否と、主張した差が件数で言える差かどうか
  7. 4点の提出物とモデルカードの必須項目

要件を満たしていなければ非0で終了する。まだ何も提出していない状態では
「まだ提出物がない」と分かる出力になる。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SANDBOX = Path(__file__).resolve().parents[2]

REQ_SCHEMA = "mid02-requirements/1"
CONFIG_SCHEMA = "mid02-config/1"
DECISION_SCHEMA = "mid02-decision/1"

# 速度の指標（記録側）と、要求（予算側）のキーの対応。
# 3つのうち1つに全構成をそろえる。ms と 秒/step を混ぜた比較は成立しない。
SPEED_BUDGET = {
    "seconds_per_item": "max_seconds_per_item",
    "latency_ms": "max_latency_ms",
    "seconds_per_step": "max_seconds_per_step",
}
SPEED_UNIT = {"seconds_per_item": "秒/件", "latency_ms": "ms", "seconds_per_step": "秒/step"}

# 基準（requirements.json の budget）に必ず入っていなければならない項目
BUDGET_REQUIRED = ("max_size_mib", "max_accuracy_drop", "min_format_rate", "eval_n")
# 数字の根拠。**数字だけ書いて根拠を書かないのがこの章で最も多い失敗**
RATIONALE_REQUIRED = {
    "size": "サイズをその値にした根拠",
    "speed": "速度をその値にした根拠",
    "accuracy": "許容できる劣化をその値にした根拠",
}
RATIONALE_MIN_CHARS = 15

# 構成の記録に必ず入っていなければならない項目
RECIPE_REQUIRED = ("base_model", "method", "quant", "task", "seed")
RECIPE_RECOMMENDED = ("steps", "lora_r", "dtype", "max_length", "teacher")

# 4点の提出物（runs/mid02/reports/ に置く）
REPORTS = {
    "01-requirements.md": "要求と根拠（どこまで小さくするかの設計）",
    "02-comparison.md": "サイズ・速度・精度の3点比較表",
    "03-decision.md": "劣化の許容範囲の判断記録",
    "04-model-card.md": "モデルカード",
}

# モデルカードに書かれていなければならない情報（書式は問わない・情報の有無だけを見る）
MODEL_CARD_MARKERS = [
    ("モデル名", r"モデル名"),
    ("ベースモデル", r"(ベースモデル|SmolLM2|Qwen2\.5)"),
    ("想定する用途", r"想定する用途"),
    ("想定外の用途", r"想定外の用途"),
    ("学習データと版", r"(学習データ|データの版)"),
    ("正解率", r"正解率"),
    ("形式遵守率", r"形式遵守率"),
    ("評価件数", r"\d+\s*件"),
    ("測定条件", r"(測定条件|OMP_NUM_THREADS)"),
    ("サイズ", r"(MiB|MB)"),
    ("速度", r"(秒/件|秒/step|ms|レイテンシ)"),
    ("既知の限界", r"既知の限界"),
    ("torch のバージョン", r"torch\D{0,14}2\.13\.0\+cpu"),
    ("シード", r"20260815"),
]

VERDICTS = ("採用", "不採用", "保留")
ASSERTIONS = ("改善", "劣化", "同等")

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
    """'quality.accuracy' のようなパスで値を取り出す（無ければ None）。"""
    current = record
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def fmt(value, digits: int = 3) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "はい" if value else "いいえ"
    if isinstance(value, float):
        return f"{value:.{digits}f}" if abs(value) < 1000 else f"{value:.1f}"
    return str(value)


def parse_time(value):
    """ISO 8601 の時刻を読む。タイムゾーンが無ければ UTC とみなす。"""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def wald(p: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """正解率の 95% の目安（Wald 近似）。0 や 1 に近いと粗くなる（セッション9）。"""
    se = math.sqrt(max(p * (1 - p), 0.0) / n)
    return max(0.0, p - z * se), min(1.0, p + z * se)


def wald_diff(p1: float, n1: int, p2: float, n2: int,
              z: float = 1.96) -> tuple[float, float, float]:
    """2つの正解率の差の 95% の目安。0 をまたぐなら「差があるとは言えない」。"""
    se = math.sqrt(max(p1 * (1 - p1), 0.0) / n1 + max(p2 * (1 - p2), 0.0) / n2)
    diff = p2 - p1
    return diff, diff - z * se, diff + z * se


# ---------------------------------------------------------------------------
# 引数と入力
# ---------------------------------------------------------------------------
ap = argparse.ArgumentParser(description="中間プロジェクト2の提出物を点検する（学習しない）")
ap.add_argument("--dir", default="runs/mid02", help="記録を置いたディレクトリ")
ap.add_argument("--min-configs", type=int, default=3, help="必要な構成の数")
args = ap.parse_args()

root = Path(args.dir)
if not root.is_absolute():
    root = SANDBOX / root
reports_dir = root / "reports"
req_path = root / "requirements.json"
decision_path = root / "decision.json"

print("=" * 70)
print(" 中間プロジェクト2：提出物の点検（モデルを読まない・数秒で終わる）")
print("=" * 70)
print(f"記録の場所: {root}")

config_paths = (sorted(p for p in root.glob("*.json")
                       if p.name not in ("requirements.json", "decision.json"))
                if root.exists() else [])

if not req_path.exists():
    print("\n先に宣言した基準（requirements.json）がありません。")
    print(f"  1. mkdir -p {args.dir}/reports src/mid02")
    print("  2. 許容できる劣化・目標サイズ・目標速度を数字と根拠で決め、"
          f"{args.dir}/requirements.json に書く")
    print("  3. そのあとで測る")
    print(f"\n測定記録は {len(config_paths)} 件ありますが、基準が無いので"
          "「要求を満たしたか」を判定できません。")
    print("このプロジェクトでは、**基準を先に決めていないこと自体が不合格**です。")
    sys.exit(1)

try:
    requirements = json.loads(req_path.read_text(encoding="utf-8"))
except json.JSONDecodeError as exc:
    print(f"\nrequirements.json が JSON として読めません: {exc}")
    sys.exit(1)
if not isinstance(requirements, dict):
    print("\nrequirements.json が1件のオブジェクトになっていません。")
    sys.exit(1)

if not config_paths:
    print("\n基準はありますが、測定記録がまだありません。")
    print("  1. 基準構成（小さくする前のモデル）を1つ作り、サイズ・速度・精度を測る")
    print("     -> kind=\"baseline\" として記録する")
    print("  2. 小さくした候補を2つ以上測る（例：量子化・蒸留）")
    print(f"     -> {args.dir}/c01_*.json のように1構成1ファイルで記録する")
    print("\n点検できる記録が0件なので、要件を満たしていません。")
    sys.exit(1)

records: dict[str, dict] = {}
for path in config_paths:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        check(f"{path.name} が JSON として読める", False, str(exc))
        continue
    if not isinstance(record, dict):
        check(f"{path.name} が1件の記録（オブジェクト）である", False, type(record).__name__)
        continue
    config_id = record.get("config_id") or path.stem
    if config_id in records:
        check(f"config_id が重複していない（{config_id}）", False, f"{path.name} と重複")
        continue
    records[config_id] = record

print(f"読み込んだ構成: {len(records)} 件（{', '.join(sorted(records))}）")

# ---------------------------------------------------------------------------
# 0. 先に宣言した基準
# ---------------------------------------------------------------------------
print("\n=== 0. 先に宣言した基準（requirements.json）===")
check(f"schema が {REQ_SCHEMA}", requirements.get("schema") == REQ_SCHEMA,
      str(requirements.get("schema")))

budget = requirements.get("budget") if isinstance(requirements.get("budget"), dict) else {}
check("budget がある", bool(budget))

missing_budget = [k for k in BUDGET_REQUIRED if not is_number(budget.get(k))]
check(f"要求が数字で入っている（{'/'.join(BUDGET_REQUIRED)}）", not missing_budget,
      f"欠け: {', '.join(missing_budget)}" if missing_budget else "")

speed_keys = [k for k in SPEED_BUDGET.values() if is_number(budget.get(k))]
check("速度の要求がちょうど1つある（"
      f"{' / '.join(SPEED_BUDGET.values())}）", len(speed_keys) == 1,
      f"{len(speed_keys)} 個: {', '.join(speed_keys) or 'なし'}")
speed_budget_key = speed_keys[0] if len(speed_keys) == 1 else None
speed_metric_wanted = next((m for m, k in SPEED_BUDGET.items() if k == speed_budget_key), None)

eval_n = budget.get("eval_n") if isinstance(budget.get("eval_n"), int) else None
check("eval_n が 1 以上の整数", isinstance(eval_n, int) and eval_n >= 1,
      fmt(budget.get("eval_n")))

drop = budget.get("max_accuracy_drop")
if is_number(drop):
    check("許容できる劣化が 1.000 未満（何でも許すなら基準になっていない）", drop < 1.0,
          f"max_accuracy_drop={drop:.3f}")
    if drop >= 0.5:
        note(f"max_accuracy_drop={drop:.3f} は緩すぎないか確認してください"
             "（正解率が半分になっても許す、という宣言になっています）")

rationale = requirements.get("rationale") if isinstance(requirements.get("rationale"), dict) else {}
thin = [f"{key}（{label}）" for key, label in RATIONALE_REQUIRED.items()
        if len(str(rationale.get(key, "")).strip()) < RATIONALE_MIN_CHARS]
check(f"3つの数字それぞれに根拠が書かれている（各 {RATIONALE_MIN_CHARS} 文字以上）", not thin,
      f"不足: {', '.join(thin)}" if thin else "")

declared_at = parse_time(requirements.get("declared_at"))
check("declared_at（基準を決めた時刻）が読める", declared_at is not None,
      str(requirements.get("declared_at")))

reference_id = str(requirements.get("reference") or "")
reference = records.get(reference_id)
check("reference が実在する記録を指している", reference is not None,
      f"reference={reference_id!r}")
if reference is not None:
    check("reference が基準線（kind=\"baseline\"）である",
          reference.get("kind") == "baseline", str(reference.get("kind")))
    ref_size = dig(reference, "size.size_mib")
    if is_number(ref_size) and is_number(budget.get("max_size_mib")):
        check("目標サイズが基準構成より小さい（小さくする要求になっている）",
              budget["max_size_mib"] < ref_size,
              f"目標 {budget['max_size_mib']:.1f} MiB / 基準 {ref_size:.1f} MiB")

# ---------------------------------------------------------------------------
# 1. 各構成の記録（3点がそろっているか）
# ---------------------------------------------------------------------------
print("\n=== 1. 各構成の記録（サイズ・速度・精度の3点）===")
for config_id, record in sorted(records.items()):
    check(f"{config_id}: schema が {CONFIG_SCHEMA}", record.get("schema") == CONFIG_SCHEMA,
          str(record.get("schema")))
    check(f"{config_id}: kind が baseline か candidate",
          record.get("kind") in ("baseline", "candidate"), str(record.get("kind")))

    recipe = record.get("recipe") if isinstance(record.get("recipe"), dict) else {}
    missing = [k for k in RECIPE_REQUIRED if recipe.get(k) in (None, "")]
    check(f"{config_id}: 作り方が記録されている（{'/'.join(RECIPE_REQUIRED)}）", not missing,
          f"欠け: {', '.join(missing)}" if missing else "")
    absent = [k for k in RECIPE_RECOMMENDED if k not in recipe]
    if absent:
        note(f"{config_id}: 推奨項目が未記入（{', '.join(absent)}）"
             "— 後からこの構成を作り直せなくなります")

    # サイズ
    size = dig(record, "size.size_mib")
    check(f"{config_id}: サイズが数値（MiB）で入っている", is_number(size) and size > 0,
          fmt(size, 1))
    check(f"{config_id}: サイズを何で測ったかが書かれている（size.measured_by）",
          bool(str(dig(record, "size.measured_by") or "").strip()))
    check(f"{config_id}: サイズが近似かどうかが書かれている（size.approx）",
          isinstance(dig(record, "size.approx"), bool))
    if not str(dig(record, "size.artifact") or "").strip():
        note(f"{config_id}: size.artifact（何のサイズを測ったか）が空です")

    # 速度
    metric = dig(record, "speed.metric")
    check(f"{config_id}: 速度の指標が {' / '.join(SPEED_BUDGET)} のどれか",
          metric in SPEED_BUDGET, str(metric))
    value = dig(record, "speed.value")
    check(f"{config_id}: 速度が正の数値で入っている", is_number(value) and value > 0, fmt(value))
    check(f"{config_id}: 速度の測定件数（speed.n）が 1 以上",
          is_number(dig(record, "speed.n")) and dig(record, "speed.n") >= 1,
          fmt(dig(record, "speed.n")))
    check(f"{config_id}: 速度を何で測ったかが書かれている（speed.measured_by）",
          bool(str(dig(record, "speed.measured_by") or "").strip()))
    check(f"{config_id}: 速度が近似かどうかが書かれている（speed.approx）",
          isinstance(dig(record, "speed.approx"), bool))

    # 精度
    accuracy = dig(record, "quality.accuracy")
    format_rate = dig(record, "quality.format_rate")
    n_eval = dig(record, "quality.eval_n")
    check(f"{config_id}: 正解率が 0.0〜1.0 の数値",
          is_number(accuracy) and 0.0 <= accuracy <= 1.0, fmt(accuracy))
    check(f"{config_id}: 形式遵守率が 0.0〜1.0 の数値",
          is_number(format_rate) and 0.0 <= format_rate <= 1.0, fmt(format_rate))
    check(f"{config_id}: 評価件数（quality.eval_n）が 1 以上の整数",
          isinstance(n_eval, int) and n_eval >= 1, fmt(n_eval))
    check(f"{config_id}: 精度を何で測ったかが書かれている（quality.measured_by）",
          bool(str(dig(record, "quality.measured_by") or "").strip()))
    check(f"{config_id}: 精度が近似かどうかが書かれている（quality.approx）",
          isinstance(dig(record, "quality.approx"), bool))
    correct = dig(record, "quality.correct")
    if is_number(correct) and isinstance(n_eval, int) and n_eval >= 1 and is_number(accuracy):
        check(f"{config_id}: 正解数と正解率が食い違っていない",
              abs(correct / n_eval - accuracy) < 0.005,
              f"{correct}/{n_eval} = {correct / n_eval:.3f} 対 記録 {accuracy:.3f}")

    # 近似を1つでも含むなら、何が近似なのかを notes に書く（数字の独り歩きを止める）
    approx_axes = [name for name, key in (("サイズ", "size.approx"), ("速度", "speed.approx"),
                                          ("精度", "quality.approx"))
                   if dig(record, key) is True]
    if approx_axes:
        check(f"{config_id}: 近似で測った軸（{'/'.join(approx_axes)}）について notes がある",
              bool(str(record.get("notes") or "").strip()),
              "近似であることを書かないと、数字だけが独り歩きします")

    for path in ("environment.torch", "environment.python", "measured_at"):
        if dig(record, path) in (None, "", {}):
            check(f"{config_id}: {path} が記録されている", False, "未記録")

# ---------------------------------------------------------------------------
# 2. 比較の広さ
# ---------------------------------------------------------------------------
print("\n=== 2. 比較の広さ ===")
check(f"構成が {args.min_configs} 件以上ある", len(records) >= args.min_configs,
      f"{len(records)} 件")
baselines = [k for k, v in records.items() if v.get("kind") == "baseline"]
check("基準線（小さくする前）が1件だけある", len(baselines) == 1,
      f"{len(baselines)} 件（{', '.join(baselines) or 'なし'}）")

methods = sorted({str(dig(r, "recipe.method")) for r in records.values()})
check("小さくする手段が2種類以上ある（同じ手段の強弱だけになっていない）", len(methods) >= 2,
      " / ".join(methods))
combos = {(str(dig(r, "recipe.method")), str(dig(r, "recipe.quant"))) for r in records.values()}
check("手段と量子化形式の組み合わせが3通り以上ある", len(combos) >= 3, f"{len(combos)} 通り")

tasks = sorted({str(dig(r, "recipe.task")) for r in records.values()})
check("全構成が同じタスクで測られている（task が1種類）", len(tasks) == 1, " / ".join(tasks))

metrics = sorted({str(dig(r, "speed.metric")) for r in records.values()})
check("全構成が同じ速度の指標で測られている", len(metrics) == 1, " / ".join(metrics))
if speed_metric_wanted and len(metrics) == 1:
    check("速度の指標が基準（requirements.json）と対応している",
          metrics[0] == speed_metric_wanted,
          f"記録={metrics[0]} / 基準={speed_budget_key}")

eval_ns = sorted({dig(r, "quality.eval_n") for r in records.values()}, key=str)
check("全構成が同じ件数で評価されている", len(eval_ns) == 1,
      " / ".join(str(v) for v in eval_ns))
if eval_n is not None and len(eval_ns) == 1:
    check("評価件数が基準の eval_n と一致している", eval_ns[0] == eval_n,
          f"記録={eval_ns[0]} / 基準={eval_n}")

# ---------------------------------------------------------------------------
# 3. 基準が先か（時刻の前後）
# ---------------------------------------------------------------------------
print("\n=== 3. 基準を先に決めたか（時刻の前後）===")
measured_times = {k: parse_time(v.get("measured_at")) for k, v in records.items()}
known = {k: t for k, t in measured_times.items() if t is not None}
if declared_at is not None and known:
    earliest_id = min(known, key=lambda k: known[k])
    earliest = known[earliest_id]
    check("基準の宣言が最初の測定より前になっている", declared_at <= earliest,
          f"宣言 {declared_at.isoformat()} / 最初の測定 {earliest.isoformat()}"
          f"（{earliest_id}）")
    if declared_at > earliest:
        note("結果を見てから基準を書くと、基準が結果に合わせて動きます。"
             "基準を作り直すのではなく、なぜそうなったかを 03-decision.md に書いてください")
else:
    check("時刻を比べられる（declared_at と measured_at が読める）", False,
          "どちらかが読めません")

# ---------------------------------------------------------------------------
# 4. 判定（要求を満たす構成はどれか）
# ---------------------------------------------------------------------------
print("\n=== 4. 判定（要求を満たす構成はどれか）===")
print("  ※ ここは情報です。要求を満たす構成が無いこと自体は不合格ではありません。")

ref_accuracy = dig(reference, "quality.accuracy") if reference else None


def judge(record: dict) -> list[str]:
    """要求を満たさない軸の名前を返す（空なら要求を満たす）。"""
    bad: list[str] = []
    size = dig(record, "size.size_mib")
    if is_number(size) and is_number(budget.get("max_size_mib")) and size > budget["max_size_mib"]:
        bad.append("サイズ")
    value = dig(record, "speed.value")
    cap = budget.get(speed_budget_key) if speed_budget_key else None
    if is_number(value) and is_number(cap) and value > cap:
        bad.append("速度")
    accuracy = dig(record, "quality.accuracy")
    if is_number(accuracy):
        if is_number(budget.get("min_accuracy")) and accuracy < budget["min_accuracy"]:
            bad.append("正解率（絶対水準）")
        if (is_number(ref_accuracy) and is_number(budget.get("max_accuracy_drop"))
                and ref_accuracy - accuracy > budget["max_accuracy_drop"] + 1e-9):
            bad.append("正解率（劣化幅）")
    format_rate = dig(record, "quality.format_rate")
    if (is_number(format_rate) and is_number(budget.get("min_format_rate"))
            and format_rate < budget["min_format_rate"]):
        bad.append("形式遵守率")
    return bad


verdict_by_id = {config_id: judge(record) for config_id, record in records.items()}
passing = sorted((k for k, bad in verdict_by_id.items() if not bad),
                 key=lambda k: dig(records[k], "size.size_mib") or float("inf"))
for config_id in sorted(records):
    bad = verdict_by_id[config_id]
    mark = "満たす" if not bad else "満たさない（" + " / ".join(bad) + "）"
    print(f"  {config_id:<26} {mark}")
if passing:
    cheapest = passing[0]
    size = dig(records[cheapest], "size.size_mib")
    print(f"  -> 要求を満たす構成のうち最も小さいのは {cheapest}（{fmt(size, 1)} MiB）")
else:
    print("  -> 要求を満たす構成はありません（要求に戻る判断が要ります）")

# ---------------------------------------------------------------------------
# 5. 評価件数から言える差の下限
# ---------------------------------------------------------------------------
print("\n=== 5. 評価件数から言える差の下限 ===")
floor = None
if isinstance(eval_n, int) and eval_n >= 1:
    floor = 1 / eval_n
    print(f"  評価 {eval_n} 件で刻める最小の差: 1/{eval_n} = {floor:.3f}")
    if is_number(ref_accuracy):
        lo, hi = wald(ref_accuracy, eval_n)
        print(f"  基準の正解率 {ref_accuracy:.3f} の 95% の目安: {lo:.3f}〜{hi:.3f}"
              f"（幅 ±{(hi - lo) / 2:.3f}）")
    for config_id in sorted(records):
        if config_id == reference_id:
            continue
        accuracy = dig(records[config_id], "quality.accuracy")
        if not (is_number(accuracy) and is_number(ref_accuracy)):
            continue
        diff, dlo, dhi = wald_diff(ref_accuracy, eval_n, accuracy, eval_n)
        judgement = "0 をまたぐ（偶然と区別できない）" if dlo < 0 < dhi else "0 を含まない"
        print(f"  {config_id:<26} 差 {diff:+.3f}（{dlo:+.3f}〜{dhi:+.3f}）{judgement}")
else:
    print("  eval_n が読めないので計算できません。")

# ---------------------------------------------------------------------------
# 6. 判断記録（採否と、主張した差）
# ---------------------------------------------------------------------------
print("\n=== 6. 判断記録（decision.json）===")
decision: dict = {}
if not check("判断記録（decision.json）がある", decision_path.exists()):
    print("   ・どの構成を採るか・採らないかと、その理由を書いたファイルが要ります。")
else:
    try:
        loaded = json.loads(decision_path.read_text(encoding="utf-8"))
        decision = loaded if isinstance(loaded, dict) else {}
        check("decision.json が1件のオブジェクトである", bool(decision),
              type(loaded).__name__)
    except json.JSONDecodeError as exc:
        check("decision.json が JSON として読める", False, str(exc))

if decision:
    check(f"schema が {DECISION_SCHEMA}", decision.get("schema") == DECISION_SCHEMA,
          str(decision.get("schema")))
    decided_at = parse_time(decision.get("decided_at"))
    check("decided_at が読める", decided_at is not None, str(decision.get("decided_at")))
    if decided_at is not None and known:
        latest = max(known.values())
        if decided_at < latest:
            note("判断の時刻が最後の測定より前になっています。"
                 "測り終える前に採否を決めていないか確認してください")

    verdicts = decision.get("verdicts") if isinstance(decision.get("verdicts"), list) else []
    covered = {str(v.get("config_id")) for v in verdicts if isinstance(v, dict)}
    uncovered = sorted(set(records) - covered - {reference_id})
    check("すべての候補構成に採否が書かれている", not uncovered,
          f"未記入: {', '.join(uncovered)}" if uncovered else "")

    for entry in verdicts:
        if not isinstance(entry, dict):
            check("verdicts の各要素がオブジェクトである", False, type(entry).__name__)
            continue
        config_id = str(entry.get("config_id"))
        check(f"{config_id}: verdict が {' / '.join(VERDICTS)} のどれか",
              entry.get("verdict") in VERDICTS, str(entry.get("verdict")))
        check(f"{config_id}: 採否の理由が書かれている（20文字以上）",
              len(str(entry.get("reason", "")).strip()) >= 20,
              f"{len(str(entry.get('reason', '')).strip())} 文字")
        if config_id not in records:
            check(f"{config_id}: 実在する構成を指している", False, "記録にありません")
            continue

        for asserted in entry.get("asserted_diffs") or []:
            if not isinstance(asserted, dict):
                check(f"{config_id}: asserted_diffs の要素がオブジェクトである", False)
                continue
            metric = str(asserted.get("metric"))
            wording = str(asserted.get("as"))
            against = str(asserted.get("vs"))
            label = f"{config_id}: 「{against} と比べて {metric} が {wording}」"
            if metric not in ("accuracy", "format_rate"):
                check(f"{label} の metric が accuracy か format_rate", False, metric)
                continue
            if wording not in ASSERTIONS:
                check(f"{label} の as が {' / '.join(ASSERTIONS)} のどれか", False, wording)
                continue
            if against not in records:
                check(f"{label} の比較相手が実在する", False, against)
                continue
            here = dig(records[config_id], f"quality.{metric}")
            there = dig(records[against], f"quality.{metric}")
            if not (is_number(here) and is_number(there)) or floor is None:
                check(f"{label} を数値で確かめられる", False, "値が読めません")
                continue
            diff, dlo, dhi = wald_diff(there, eval_n, here, eval_n)
            if wording == "改善":
                ok = diff >= floor - 1e-9
            elif wording == "劣化":
                ok = diff <= -floor + 1e-9
            else:
                ok = True
            check(f"{label} が件数で言える差になっている", ok,
                  f"差 {diff:+.3f} / {eval_n} 件で刻める最小の差 {floor:.3f}")
            if wording in ("改善", "劣化") and dlo < 0 < dhi:
                note(f"{config_id}: {metric} の差 {diff:+.3f} は 95% の目安が "
                     f"{dlo:+.3f}〜{dhi:+.3f} で 0 をまたぎます。"
                     "「改善／劣化」と書くなら件数を増やすか、断定を弱めてください")
            if wording == "同等" and not (dlo < 0 < dhi):
                note(f"{config_id}: {metric} の差 {diff:+.3f} は 0 をまたがないので"
                     "「同等」とは言いにくい水準です")

    selected = decision.get("selected")
    if selected is None:
        check("採る構成が無い場合は、要求元に何を返すかが書かれている（escalation）",
              len(str(decision.get("escalation", "")).strip()) >= 20,
              f"{len(str(decision.get('escalation', '')).strip())} 文字")
        if passing:
            note(f"要求を満たす構成が {len(passing)} 件あるのに selected が null です"
                 f"（{', '.join(passing)}）。採らない理由を書いてください")
    else:
        selected = str(selected)
        if check("selected が実在する構成を指している", selected in records, selected):
            bad = verdict_by_id[selected]
            if bad:
                exception = str(dig(decision, "budget_exception.reason") or "").strip()
                check("要求を満たさない構成を採るなら、例外の理由が書かれている"
                      "（budget_exception.reason）", len(exception) >= 20,
                      f"{selected} は {' / '.join(bad)} を満たしていません")
            else:
                check(f"selected（{selected}）は要求を満たしている", True)
            if passing and selected != passing[0]:
                note(f"より小さくて要求を満たす構成があります（{passing[0]}）。"
                     "そちらを採らない理由を 03-decision.md に書いてください")
            selected_verdict = next((v for v in decision.get("verdicts") or []
                                     if isinstance(v, dict)
                                     and str(v.get("config_id")) == selected), None)
            check("selected の verdict が「採用」になっている",
                  bool(selected_verdict) and selected_verdict.get("verdict") == "採用",
                  str(selected_verdict.get("verdict") if selected_verdict else "記載なし"))

# ---------------------------------------------------------------------------
# 7. 提出物とモデルカード
# ---------------------------------------------------------------------------
print("\n=== 7. 提出物（4点）===")
for name, label in REPORTS.items():
    path = reports_dir / name
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    check(f"{label} がある（reports/{name}）", bool(text.strip()), f"{len(text)} 文字")

comparison = reports_dir / "02-comparison.md"
if comparison.exists():
    text = comparison.read_text(encoding="utf-8")
    check("3点比較表が表になっている（Markdown の表がある）",
          bool(re.search(r"^\s*\|.+\|", text, re.MULTILINE)))
    listed = [config_id for config_id in records if config_id in text]
    check("3点比較表が全構成に言及している", len(listed) == len(records),
          f"{len(listed)}/{len(records)} 件")

decision_md = reports_dir / "03-decision.md"
if decision_md.exists():
    text = decision_md.read_text(encoding="utf-8")
    check("判断記録に許容できる劣化の数値が書かれている",
          bool(re.search(r"0\.\d+", text)))

card = reports_dir / "04-model-card.md"
if card.exists():
    text = card.read_text(encoding="utf-8")
    missing = [label for label, pattern in MODEL_CARD_MARKERS
               if not re.search(pattern, text, re.IGNORECASE)]
    check("モデルカードの必須項目がそろっている", not missing,
          f"欠け: {', '.join(missing)}" if missing else "")
    if decision.get("selected") and str(decision["selected"]) not in text:
        note(f"モデルカードが selected（{decision['selected']}）に言及していません。"
             "どの構成を配るのかが読み取れません")

# ---------------------------------------------------------------------------
# 3点比較表（そのまま 02-comparison.md に貼れる Markdown 表）
# ---------------------------------------------------------------------------
print("\n=== 3点比較表（02-comparison.md に貼れます）===")
unit = SPEED_UNIT.get(metrics[0], "速度") if len(metrics) == 1 else "速度"
ref_size = dig(reference, "size.size_mib") if reference else None
ref_speed = dig(reference, "speed.value") if reference else None
header = (f"| config_id | 手段 | 量子化 | サイズ MiB | 対基準 | {unit} | 対基準 | "
          "正解率 | 対基準 | 形式遵守率 | 近似 | 要求 |")
print(header)
print("| :--- | :--- | :--- | --: | --: | --: | --: | --: | --: | --: | :--- | :--- |")
for config_id in sorted(records):
    record = records[config_id]
    size = dig(record, "size.size_mib")
    speed = dig(record, "speed.value")
    accuracy = dig(record, "quality.accuracy")
    size_ratio = (f"{size / ref_size * 100:.1f}%"
                  if is_number(size) and is_number(ref_size) and ref_size else "-")
    speed_ratio = (f"{speed / ref_speed * 100:.1f}%"
                   if is_number(speed) and is_number(ref_speed) and ref_speed else "-")
    acc_diff = (f"{accuracy - ref_accuracy:+.3f}"
                if is_number(accuracy) and is_number(ref_accuracy) else "-")
    approx = "/".join(name for name, key in (("サイズ", "size.approx"), (unit, "speed.approx"),
                                             ("精度", "quality.approx"))
                      if dig(record, key) is True) or "なし"
    bad = verdict_by_id[config_id]
    print(f"| {config_id} | {dig(record, 'recipe.method')} | {dig(record, 'recipe.quant')} | "
          f"{fmt(size, 1)} | {size_ratio} | {fmt(speed, 2)} | {speed_ratio} | "
          f"{fmt(accuracy)} | {acc_diff} | {fmt(dig(record, 'quality.format_rate'))} | "
          f"{approx} | {'満たす' if not bad else '×' + '/'.join(bad)} |")

print(f"\n基準: サイズ ≤ {fmt(budget.get('max_size_mib'), 1)} MiB / "
      f"{speed_budget_key} = {fmt(budget.get(speed_budget_key), 2)} / "
      f"許容できる劣化 ≤ {fmt(budget.get('max_accuracy_drop'))} / "
      f"形式遵守率 ≥ {fmt(budget.get('min_format_rate'))} / 評価 {fmt(eval_n)} 件")

# ---------------------------------------------------------------------------
print()
if notes:
    print(f"注意（要件ではないが確認する価値がある点）: {len(notes)} 件")
if failures:
    print(f"{len(failures)} 件の要件を満たしていません:")
    for label in failures:
        print(f"  - {label}")
    print("\n小ささも指標の高さも点検していません。足りないのは「基準」と「記録」です。")
    sys.exit(1)

print("提出物の要件をすべて満たしています。")
print("ただしこの点検は形式と算術だけを見ています。要求の数字そのものが妥当か"
      "（その劣化を本当に許してよいのか）は、要求元と合意した記録で確かめてください。")
