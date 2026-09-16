#!/usr/bin/env python3
"""最終プロジェクト（モデル改善のパイプライン）の提出物を機械的に点検する。

  docker compose exec app python src/final/verify.py
  docker compose exec app python src/final/verify.py --dir runs/final --min-variants 3
  docker compose exec app python src/final/verify.py --require-files

**モデルを読まない・学習しない・生成しない。** 読むのは JSON と Markdown だけなので
数秒で終わる。点検するのは「他人がこの記録だけで同じモデルを作り直せるか」であって、
指標の高さでも小ささでもない（正解率が高いこと・サイズが小さいことは合格条件ではない）。

中間プロジェクト1（実験記録の連鎖）と中間プロジェクト2（3点比較と判断の記録）の
点検をこの1本に統合し、最終プロジェクトの要件を足してある。

点検項目:
  0. パイプラインの設計（runs/final/pipeline.json）がある。**無ければここで終わる**
  1. 段が5種そろい、段の入力が上流の段の成果物とつながっている（＝途中から再開できる）
  2. 7つの成果物がそろっている
  3. 実験記録が条件と結果を持ち、条件を1つずつ変えた連鎖になっている
  4. 混同表と忘却の検出が記録されている
  5. 配布候補がサイズ・速度・精度の3点をそろえて持っている
  6. 評価件数から言える差の下限を計算し、報告された差がその下限を超えているか
  7. 再現手順にバージョン・シード・データのハッシュ・コマンド列がそろっている
  8. モデルカードの必須9項目（セッション14の定義をそのまま使う）
  9. 「次に何を試すか」の提案に、実測値への参照として根拠が付いている

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
sys.path.insert(0, str(SANDBOX))
sys.path.insert(0, str(SANDBOX / "src" / "session14"))

# セッション14の定義をそのまま使う（章をまたいでスキーマをずらさないため）。
# repro.py は torch を読まないので import は一瞬で終わる。
from repro import COND_REQUIRED, MODEL_CARD_ITEMS, check_model_card  # noqa: E402

from ftkit.data import CATEGORIES  # noqa: E402

PIPELINE_SCHEMA = "final-pipeline/1"
EXPERIMENT_SCHEMA = "final-experiment/1"
VARIANT_SCHEMA = "final-variant/1"
PROPOSALS_SCHEMA = "final-proposals/1"

# 段の種類。データ→学習→評価→量子化→引き渡しの5種がそろって初めて「一巡」になる
STAGE_KINDS = ("data", "train", "eval", "quantize", "handoff")
STAGE_REQUIRED = ("id", "kind", "name", "command", "run_on",
                  "artifacts", "inputs", "depends_on", "resumable")
RUN_ON = ("app", "host")

# 実験記録の条件。セッション14の COND_REQUIRED（9項目）に eval_n を足す
COND_EXPERIMENT = list(COND_REQUIRED) + ["eval_n"]
COND_BASELINE = ["model", "task", "max_length", "dtype", "seed", "split", "eval_n"]
COND_RECOMMENDED = ["lora_alpha", "lr", "grad_accum", "epochs", "target_modules"]

# 配布候補の作り方。これが無いと「そのファイルをもう一度作る」ができない
RECIPE_REQUIRED = ("base_model", "method", "quant", "task", "seed", "source_run")
RECIPE_RECOMMENDED = ("adapter", "dtype", "max_length", "steps", "lora_r")

SPEED_METRICS = {"seconds_per_item": "秒/件", "latency_ms": "ms",
                 "seconds_per_step": "秒/step"}

# 7つの成果物（runs/final/reports/ に置く）
REPORTS = {
    "01-data-design.md": "① データ設計（汚染対策込み）",
    "02-training.md": "② 学習スクリプトと実験記録",
    "03-eval-report.md": "③ 評価レポート（混同表・忘却の検出）",
    "04-quantization.md": "④ 量子化とサイズ・速度・精度の比較",
    "05-model-card.md": "⑤ モデルカード",
    "06-reproduce.md": "⑥ 再現手順",
    "07-next-steps.md": "⑦ 次に何を試すかの提案（根拠付き）",
}

# 再現手順に書かれていなければならない情報
REPRODUCE_MARKERS = [
    ("torch のバージョン", r"torch\D{0,14}2\.13\.0\+cpu"),
    ("transformers のバージョン", r"transformers\D{0,14}4\.57\.6"),
    ("peft のバージョン", r"peft\D{0,14}0\.20\.0"),
    ("Python のバージョン", r"[Pp]ython\D{0,8}3\.12"),
    ("シード", r"20260815"),
    ("スレッド数", r"OMP_NUM_THREADS"),
    ("データの版（生成）", r"make_dataset\.py"),
    ("データの版（分割）", r"split_by_pattern\.py"),
    ("データのハッシュ", r"sha256"),
    ("起動コマンド", r"docker compose"),
]

# 提案の軸。本書の背骨（モデル選定が最も効く）を思い出すために列挙してある
AXES = ("モデル選定", "データ", "入力設計", "学習手法", "評価",
        "出力設計", "量子化・軽量化", "運用")
SPINE_AXIS = "モデル選定"

CLAIM_METRICS = ("accuracy", "format_rate")
CLAIM_WORDS = ("改善", "劣化", "同等")
VERDICTS = ("検出", "未検出")

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


def dig(record, path: str):
    """'results.after.accuracy' のようなパスで値を取り出す（無ければ None）。"""
    current = record
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def as_list(value) -> list:
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def fmt(value, digits: int = 3) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "はい" if value else "いいえ"
    if isinstance(value, float):
        return f"{value:.{digits}f}" if abs(value) < 1000 else f"{value:.1f}"
    if isinstance(value, list):
        return "/".join(str(v) for v in value)
    return str(value)


def norm_path(text: str) -> str:
    """記録に書かれたパスの表記ゆれを吸収する（./ の有無・末尾の / ）。"""
    return str(text).strip().lstrip("./").rstrip("/")


def parse_time(value):
    """ISO 8601 の時刻を読む。タイムゾーンが無ければ UTC とみなす。"""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        stamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
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


def diff_conditions(base: dict, child: dict) -> list[str]:
    """2つの条件の差分（値が違うキー）。片方に無いキーも差分として扱う。"""
    return [k for k in sorted(set(base) | set(child)) if base.get(k) != child.get(k)]


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# 引数と入力
# ---------------------------------------------------------------------------
ap = argparse.ArgumentParser(description="最終プロジェクトの提出物を点検する（学習しない）")
ap.add_argument("--dir", default="runs/final", help="記録を置いたディレクトリ")
ap.add_argument("--min-stages", type=int, default=5, help="必要な段の数")
ap.add_argument("--min-experiments", type=int, default=3, help="必要な実験条件の数")
ap.add_argument("--min-variants", type=int, default=3, help="必要な配布候補の数")
ap.add_argument("--min-proposals", type=int, default=3, help="必要な提案の数")
ap.add_argument("--require-files", action="store_true",
                help="段の成果物が実在することも要求する（GGUF を消したあとは落ちる）")
args = ap.parse_args()

root = Path(args.dir)
if not root.is_absolute():
    root = SANDBOX / root
reports_dir = root / "reports"
pipeline_path = root / "pipeline.json"
proposals_path = root / "proposals.json"

print("=" * 74)
print(" 最終プロジェクト：提出物の点検（モデルを読まない・数秒で終わる）")
print("=" * 74)
print(f"記録の場所: {root}")

if not pipeline_path.exists():
    print("\nパイプラインの設計（pipeline.json）がありません。")
    print(f"  1. mkdir -p {args.dir}/reports src/final")
    print("  2. python tools/make_dataset.py && python src/session03/split_by_pattern.py")
    print("  3. 段（データ→学習→評価→量子化→引き渡し）と、各段が残す中間成果物の"
          f"パスを {args.dir}/pipeline.json に書く")
    print("  4. そのあとで各段を走らせ、記録を残す")
    print("\nこのプロジェクトでは、**設計を先に書いていないこと自体が不合格**です。")
    print("段を先に決めないと、途中で落ちたときにどこから再開すればよいか分かりません。")
    sys.exit(1)

pipeline, error = read_json(pipeline_path)
if error or not isinstance(pipeline, dict):
    print(f"\npipeline.json が1件のオブジェクトとして読めません: {error or type(pipeline).__name__}")
    sys.exit(1)

# pipeline.json / proposals.json 以外の JSON を記録として読む
record_paths = sorted(p for p in root.glob("*.json")
                      if p.name not in ("pipeline.json", "proposals.json"))
records: dict[str, dict] = {}
for path in record_paths:
    record, error = read_json(path)
    if error:
        check(f"{path.name} が JSON として読める", False, error)
        continue
    if not isinstance(record, dict):
        check(f"{path.name} が1件の記録（オブジェクト）である", False, type(record).__name__)
        continue
    key = record.get("run_id") or record.get("variant_id") or path.stem
    if key in records:
        check(f"記録の id が重複していない（{key}）", False, f"{path.name} と重複")
        continue
    record["_file"] = path.name
    records[key] = record

experiments = {k: v for k, v in records.items()
               if v.get("schema") == EXPERIMENT_SCHEMA and v.get("kind") == "experiment"}
baselines = {k: v for k, v in records.items()
             if v.get("schema") == EXPERIMENT_SCHEMA and v.get("kind") == "baseline"}
runs = {**baselines, **experiments}
variants = {k: v for k, v in records.items() if v.get("schema") == VARIANT_SCHEMA}
unknown = {k: v for k, v in records.items()
           if k not in runs and k not in variants}

print(f"読み込んだ記録: 実験 {len(experiments)} / 基準線 {len(baselines)} / "
      f"配布候補 {len(variants)} 件")
for key, record in sorted(unknown.items()):
    check(f"{record['_file']}: schema が既知のどれか"
          f"（{EXPERIMENT_SCHEMA} / {VARIANT_SCHEMA}）", False,
          f"schema={record.get('schema')} kind={record.get('kind')}")

# ---------------------------------------------------------------------------
# 1. パイプラインの設計と再開可能性
# ---------------------------------------------------------------------------
print("\n=== 1. パイプラインの設計（段の連結と再開可能性）===")
check(f"schema が {PIPELINE_SCHEMA}", pipeline.get("schema") == PIPELINE_SCHEMA,
      str(pipeline.get("schema")))
check("created_at（設計を書いた時刻）が読める", parse_time(pipeline.get("created_at")) is not None,
      str(pipeline.get("created_at")))

raw_stages = pipeline.get("stages") if isinstance(pipeline.get("stages"), list) else []
stages: dict[str, dict] = {}
order: list[str] = []
for index, stage in enumerate(raw_stages, start=1):
    if not isinstance(stage, dict):
        check(f"stages[{index}] がオブジェクトである", False, type(stage).__name__)
        continue
    stage_id = str(stage.get("id") or "").strip()
    if not stage_id:
        check(f"stages[{index}] に id がある", False, "空です")
        continue
    if stage_id in stages:
        check(f"段の id が重複していない（{stage_id}）", False, f"stages[{index}]")
        continue
    stages[stage_id] = stage
    order.append(stage_id)

check(f"段が {args.min_stages} 本以上ある", len(stages) >= args.min_stages, f"{len(stages)} 本")

kinds_present = {str(stage.get("kind")) for stage in stages.values()}
missing_kinds = [k for k in STAGE_KINDS if k not in kinds_present]
check(f"5種の段がそろっている（{'/'.join(STAGE_KINDS)}）", not missing_kinds,
      f"欠け: {', '.join(missing_kinds)}" if missing_kinds else "")

artifact_owner: dict[str, str] = {}
for stage_id in order:
    stage = stages[stage_id]
    missing = [k for k in STAGE_REQUIRED if k not in stage]
    check(f"{stage_id}: 段の項目がそろっている（{'/'.join(STAGE_REQUIRED)}）", not missing,
          f"欠け: {', '.join(missing)}" if missing else "")
    check(f"{stage_id}: kind が {' / '.join(STAGE_KINDS)} のどれか",
          stage.get("kind") in STAGE_KINDS, str(stage.get("kind")))
    check(f"{stage_id}: run_on が {' / '.join(RUN_ON)} のどれか",
          stage.get("run_on") in RUN_ON, str(stage.get("run_on")))
    command = str(stage.get("command") or "").strip()
    check(f"{stage_id}: 実行コマンドが書かれている", bool(command), command[:60])
    check(f"{stage_id}: resumable が真偽値である", isinstance(stage.get("resumable"), bool),
          str(stage.get("resumable")))
    if stage.get("resumable") is False:
        check(f"{stage_id}: 再開できない段には理由が書かれている（notes）",
              len(str(stage.get("notes") or "").strip()) >= 15,
              "この段だけは毎回やり直すことになる理由を書いてください")

    artifacts = [norm_path(a) for a in as_list(stage.get("artifacts")) if str(a).strip()]
    check(f"{stage_id}: 中間成果物のパスが1つ以上ある", bool(artifacts),
          "この段が何を残すのか書かないと、次の段から再開できません")
    for artifact in artifacts:
        if artifact in artifact_owner:
            check(f"{stage_id}: 成果物 {artifact} が他の段（{artifact_owner[artifact]}）"
                  "と重複していない", False, "同じファイルを2つの段が上書きしています")
        else:
            artifact_owner[artifact] = stage_id

    parents = [str(p) for p in as_list(stage.get("depends_on"))]
    unknown_parents = [p for p in parents if p not in stages]
    check(f"{stage_id}: depends_on が実在する段を指している", not unknown_parents,
          f"不明: {', '.join(unknown_parents)}" if unknown_parents else
          (", ".join(parents) or "起点"))


def upstream_artifacts(stage_id: str) -> set[str]:
    """その段から辿れる上流の段が残す成果物の集合。"""
    found: set[str] = set()
    stack = [p for p in as_list(stages.get(stage_id, {}).get("depends_on"))]
    seen: set[str] = set()
    while stack:
        parent = str(stack.pop())
        if parent in seen or parent not in stages:
            continue
        seen.add(parent)
        found |= {norm_path(a) for a in as_list(stages[parent].get("artifacts"))}
        stack.extend(str(p) for p in as_list(stages[parent].get("depends_on")))
    return found


def covered_by(target: str, available: set[str]) -> bool:
    """入力 target が、上流の成果物 available のどれかで説明できるか。

    完全一致のほか、上流がディレクトリを成果物として宣言している場合
    （`export/final/` に対する `export/final/adapter_v1`）も認める。逆向き
    （上流が `export/final/adapter_v1` で入力が `export/final/`）も認める。
    """
    if target in available:
        return True
    return any(target.startswith(item + "/") or item.startswith(target + "/")
               for item in available)


def find_cycle() -> list[str]:
    done: set[str] = set()

    def visit(node: str, path: list[str]) -> list[str]:
        if node in done:
            return []
        if node in path:
            return path[path.index(node):] + [node]
        path.append(node)
        for parent in as_list(stages[node].get("depends_on")):
            parent = str(parent)
            if parent in stages:
                found = visit(parent, path)
                if found:
                    return found
        path.pop()
        done.add(node)
        return []

    for stage_id in order:
        found = visit(stage_id, [])
        if found:
            return found
    return []


cycle = find_cycle()
check("段の依存が循環していない", not cycle, " -> ".join(cycle) if cycle else "")

origins = [s for s in order if not as_list(stages[s].get("depends_on"))]
check("起点の段が1本だけある", len(origins) == 1,
      " / ".join(origins) if origins else "起点がありません（全段が依存を持っています）")

if not cycle:
    print("\n--- 段の入力が上流の成果物とつながっているか（＝途中から再開できるか）---")
    for stage_id in order:
        inputs = [norm_path(x) for x in as_list(stages[stage_id].get("inputs"))
                  if str(x).strip()]
        if not as_list(stages[stage_id].get("depends_on")):
            check(f"{stage_id}: 起点の段は入力を持たない（データ生成から始める）",
                  not inputs, ", ".join(inputs))
            continue
        check(f"{stage_id}: 入力が1つ以上ある", bool(inputs),
              "上流の成果物を読まない段は、上流と切れています")
        available = upstream_artifacts(stage_id)
        dangling = [x for x in inputs if not covered_by(x, available)]
        check(f"{stage_id}: 入力がすべて上流の段の成果物である", not dangling,
              f"上流に無い入力: {', '.join(dangling)}" if dangling else "")

print("\n--- 成果物の実在（記録の点検には必須ではない）---")
missing_files: list[str] = []
for artifact, owner in sorted(artifact_owner.items()):
    path = SANDBOX / artifact
    exists = path.exists()
    if not exists:
        missing_files.append(f"{artifact}（{owner}）")
    print(f"  {'ある  ' if exists else 'ない  '}{artifact}  <- {owner}")
if missing_files:
    if args.require_files:
        check("すべての成果物が実在する（--require-files）", False,
              f"{len(missing_files)} 件: {missing_files[0]} など")
    else:
        note(f"{len(missing_files)} 件の成果物が手元にありません。"
             "GGUF は 2.73GB を使うので消してよいですが、"
             "再現手順にはその段のコマンドを必ず残してください")

# ---------------------------------------------------------------------------
# 2. 7つの成果物
# ---------------------------------------------------------------------------
print("\n=== 2. 7つの成果物 ===")
report_text: dict[str, str] = {}
for name, label in REPORTS.items():
    path = reports_dir / name
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    report_text[name] = text
    check(f"{label} がある（reports/{name}）", bool(text.strip()), f"{len(text)} 文字")

# ---------------------------------------------------------------------------
# 3. 実験記録（条件と結果・変更の連鎖）
# ---------------------------------------------------------------------------
print("\n=== 3. 実験記録（条件と結果）===")
check("学習前の基準線がある（kind=\"baseline\"）", len(baselines) >= 1,
      f"{len(baselines)} 件（{', '.join(sorted(baselines)) or 'なし'}）")
check(f"実験条件が {args.min_experiments} 件以上ある",
      len(experiments) >= args.min_experiments, f"{len(experiments)} 件")

train_eval_stages = {s for s in order if stages[s].get("kind") in ("train", "eval")}
for run_id, record in sorted(runs.items()):
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
        check(f"{run_id}: steps が 1 以上",
              is_number(conditions.get("steps")) and conditions["steps"] >= 1,
              fmt(conditions.get("steps")))
        check(f"{run_id}: lora_r が 1 以上",
              is_number(conditions.get("lora_r")) and conditions["lora_r"] >= 1,
              fmt(conditions.get("lora_r")))
    check(f"{run_id}: dtype が fp32 か bf16", conditions.get("dtype") in ("fp32", "bf16"),
          str(conditions.get("dtype")))
    check(f"{run_id}: split が記録されている（分割方式は学習設定ではないので忘れやすい）",
          bool(str(conditions.get("split") or "").strip()), str(conditions.get("split")))

    wanted = ["before.accuracy", "before.format_rate"]
    if not baseline:
        wanted += ["first_loss", "last_loss", "after.accuracy", "after.format_rate"]
    bad = [p for p in wanted if not is_number(dig(record, "results." + p))]
    check(f"{run_id}: 結果が揃っている（{'/'.join(wanted)}）", not bad,
          f"欠け: {', '.join(bad)}" if bad else "")
    for key in ("first_loss", "last_loss"):
        value = dig(record, "results." + key)
        if is_number(value) and value != value:  # NaN
            note(f"{run_id}: {key} が NaN です。全マスク（採点対象が無い）か"
                 "学習率が大きすぎる可能性があります（セッション4・7）")

    for path in ("environment.torch", "environment.python", "data_version"):
        if dig(record, path) in (None, "", {}):
            check(f"{run_id}: {path} が記録されている", False, "未記録")
    check(f"{run_id}: どの段で作られた記録かが書かれている（stage）",
          str(record.get("stage") or "") in train_eval_stages,
          f"stage={record.get('stage')!r} / 学習・評価の段: "
          f"{', '.join(sorted(train_eval_stages)) or 'なし'}")

models = sorted({str(dig(r, "conditions.model")) for r in experiments.values()})
check("実験記録にモデルを変えた条件が含まれている（2種類以上）", len(models) >= 2,
      " / ".join(models) if models else "なし")
if len(models) < 2:
    note("本書の背骨は「データや手法の工夫より先にモデル選定が効く」です。"
         "モデルを変えた条件が無いと、その判断を自分の実測で語れません")

print("\n=== 3b. 変更の連鎖（1条件ずつ変えているか）===")
chain_origins = [k for k, v in experiments.items() if not v.get("changed_from")]
check("連鎖の起点がある（changed_from を持たない実験が1件以上）", len(chain_origins) >= 1,
      " / ".join(chain_origins) if chain_origins else "全記録が changed_from を持っています")
for run_id, record in sorted(experiments.items()):
    parent_id = record.get("changed_from")
    if not parent_id:
        continue
    parent = runs.get(str(parent_id))
    if not check(f"{run_id}: changed_from が実在する記録を指している", parent is not None,
                 f"changed_from={parent_id!r}"):
        continue
    declared = sorted(str(x) for x in as_list(record.get("changed_field")))
    actual = sorted(diff_conditions(parent.get("conditions") or {},
                                    record.get("conditions") or {}))
    check(f"{run_id}: changed_field が実際の差分と一致する（対 {parent_id}）",
          declared == actual, f"宣言={declared or 'なし'} / 実際={actual or 'なし'}")
    if len(actual) >= 2:
        check(f"{run_id}: 2項目以上を同時に変えた理由が notes に書かれている",
              len(str(record.get("notes") or "").strip()) >= 15,
              f"同時に変えた項目: {', '.join(actual)}")

for run_id in sorted(experiments):
    seen = [run_id]
    cursor = experiments[run_id].get("changed_from")
    while cursor and cursor in runs and cursor not in seen:
        seen.append(str(cursor))
        cursor = runs[str(cursor)].get("changed_from")
    if cursor in seen:
        check(f"{run_id}: 連鎖が循環していない", False, " -> ".join(seen + [str(cursor)]))

# ---------------------------------------------------------------------------
# 4. 混同表と忘却の検出
# ---------------------------------------------------------------------------
print("\n=== 4. 混同表と忘却の検出 ===")
with_confusion: list[str] = []
for run_id, record in sorted(runs.items()):
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

with_forgetting: list[str] = []
for run_id, record in sorted(runs.items()):
    forgetting = record.get("forgetting")
    if not isinstance(forgetting, dict) or not forgetting:
        continue
    before = norm_path(forgetting.get("before") or "")
    after = norm_path(forgetting.get("after") or "")
    ok = check(f"{run_id}: 忘却プローブの before と after が別のファイルとして記録されている",
               bool(before) and bool(after) and before != after,
               f"before={before or 'なし'} / after={after or 'なし'}")
    ok &= check(f"{run_id}: プローブが3件以上ある",
                is_number(forgetting.get("n_probes")) and forgetting["n_probes"] >= 3,
                fmt(forgetting.get("n_probes")))
    ok &= check(f"{run_id}: 忘却の判定が {' / '.join(VERDICTS)} のどれか",
                forgetting.get("verdict") in VERDICTS, str(forgetting.get("verdict")))
    regressions = as_list(forgetting.get("regressions"))
    if forgetting.get("verdict") == "検出":
        ok &= check(f"{run_id}: 検出したなら、どのプローブが劣化したかが書かれている",
                    bool(regressions), "regressions が空です")
        for entry in regressions:
            if not isinstance(entry, dict):
                ok &= check(f"{run_id}: regressions の要素がオブジェクトである", False,
                            type(entry).__name__)
                continue
            ok &= check(f"{run_id}: 劣化したプローブに id と観察が書かれている"
                        f"（{entry.get('probe')}）",
                        bool(re.fullmatch(r"P-\d+", str(entry.get("probe") or "")))
                        and len(str(entry.get("note") or "").strip()) >= 10,
                        f"probe={entry.get('probe')!r} note="
                        f"{len(str(entry.get('note') or '').strip())} 文字")
    elif forgetting.get("verdict") == "未検出":
        ok &= check(f"{run_id}: 未検出なら、何を見てそう判断したかが書かれている（notes）",
                    len(str(forgetting.get("notes") or "").strip()) >= 15,
                    "「変わらなかった」の根拠が要ります")
    if ok:
        with_forgetting.append(run_id)
check("少なくとも1件の記録に忘却の検出結果がある", bool(with_forgetting),
      " / ".join(with_forgetting) if with_forgetting else
      "学習したタスクの指標だけでは忘却は見えません（セッション9）")

# ---------------------------------------------------------------------------
# 5. 配布候補（サイズ・速度・精度の3点）
# ---------------------------------------------------------------------------
print("\n=== 5. 配布候補（サイズ・速度・精度の3点）===")
check(f"配布候補が {args.min_variants} 件以上ある", len(variants) >= args.min_variants,
      f"{len(variants)} 件")
variant_baselines = [k for k, v in variants.items() if v.get("kind") == "baseline"]
check("量子化する前の基準が1件だけある", len(variant_baselines) == 1,
      f"{len(variant_baselines)} 件（{', '.join(variant_baselines) or 'なし'}）")
reference_id = variant_baselines[0] if len(variant_baselines) == 1 else None
reference = variants.get(reference_id) if reference_id else None

for variant_id, record in sorted(variants.items()):
    check(f"{variant_id}: kind が baseline か candidate",
          record.get("kind") in ("baseline", "candidate"), str(record.get("kind")))
    recipe = record.get("recipe") if isinstance(record.get("recipe"), dict) else {}
    missing = [k for k in RECIPE_REQUIRED if recipe.get(k) in (None, "")]
    check(f"{variant_id}: 作り方が記録されている（{'/'.join(RECIPE_REQUIRED)}）", not missing,
          f"欠け: {', '.join(missing)}" if missing else "")
    absent = [k for k in RECIPE_RECOMMENDED if k not in recipe]
    if absent:
        note(f"{variant_id}: 推奨項目が未記入（{', '.join(absent)}）"
             "— この配布物をもう一度作れなくなります")
    check(f"{variant_id}: source_run が実在する実験記録を指している",
          str(recipe.get("source_run") or "") in runs,
          f"source_run={recipe.get('source_run')!r}")

    size = dig(record, "size.size_mib")
    check(f"{variant_id}: サイズが数値（MiB）で入っている", is_number(size) and size > 0,
          fmt(size, 1))
    check(f"{variant_id}: 何のサイズを測ったかが書かれている（size.artifact）",
          bool(str(dig(record, "size.artifact") or "").strip()))
    check(f"{variant_id}: サイズを何で測ったかが書かれている（size.measured_by）",
          bool(str(dig(record, "size.measured_by") or "").strip()))

    metric = dig(record, "speed.metric")
    check(f"{variant_id}: 速度の指標が {' / '.join(SPEED_METRICS)} のどれか",
          metric in SPEED_METRICS, str(metric))
    check(f"{variant_id}: 速度が正の数値で入っている",
          is_number(dig(record, "speed.value")) and dig(record, "speed.value") > 0,
          fmt(dig(record, "speed.value")))
    check(f"{variant_id}: 速度の測定件数（speed.n）が 1 以上",
          is_number(dig(record, "speed.n")) and dig(record, "speed.n") >= 1,
          fmt(dig(record, "speed.n")))

    accuracy = dig(record, "quality.accuracy")
    format_rate = dig(record, "quality.format_rate")
    eval_n = dig(record, "quality.eval_n")
    check(f"{variant_id}: 正解率が 0.0〜1.0 の数値",
          is_number(accuracy) and 0.0 <= accuracy <= 1.0, fmt(accuracy))
    check(f"{variant_id}: 形式遵守率が 0.0〜1.0 の数値",
          is_number(format_rate) and 0.0 <= format_rate <= 1.0, fmt(format_rate))
    check(f"{variant_id}: 評価件数（quality.eval_n）が 1 以上の整数",
          isinstance(eval_n, int) and eval_n >= 1, fmt(eval_n))
    correct = dig(record, "quality.correct")
    if is_number(correct) and isinstance(eval_n, int) and eval_n >= 1 and is_number(accuracy):
        check(f"{variant_id}: 正解数と正解率が食い違っていない",
              abs(correct / eval_n - accuracy) < 0.005,
              f"{correct}/{eval_n} = {correct / eval_n:.3f} 対 記録 {accuracy:.3f}")

    for axis, key in (("サイズ", "size.approx"), ("速度", "speed.approx"),
                      ("精度", "quality.approx")):
        check(f"{variant_id}: {axis}が近似かどうかが書かれている（{key}）",
              isinstance(dig(record, key), bool), str(dig(record, key)))
    approx_axes = [axis for axis, key in (("サイズ", "size.approx"), ("速度", "speed.approx"),
                                          ("精度", "quality.approx"))
                   if dig(record, key) is True]
    if approx_axes:
        check(f"{variant_id}: 近似で測った軸（{'/'.join(approx_axes)}）について notes がある",
              len(str(record.get("notes") or "").strip()) >= 15,
              "GGUF は transformers から読めないので、精度は PyTorch 上で丸めを"
              "再現して測ることになります。その事情を書かないと数字だけが独り歩きします")

    for path in ("environment.torch", "measured_at"):
        if dig(record, path) in (None, "", {}):
            check(f"{variant_id}: {path} が記録されている", False, "未記録")

quants = sorted({str(dig(r, "recipe.quant")) for r in variants.values()})
check("量子化の形式が2種類以上ある（1つだけでは比較になっていない）", len(quants) >= 2,
      " / ".join(quants) if quants else "なし")
tasks = sorted({str(dig(r, "recipe.task")) for r in variants.values()})
check("全候補が同じタスクで測られている", len(tasks) == 1, " / ".join(tasks))
metrics = sorted({str(dig(r, "speed.metric")) for r in variants.values()})
check("全候補が同じ速度の指標で測られている", len(metrics) == 1, " / ".join(metrics))
variant_eval_ns = sorted({dig(r, "quality.eval_n") for r in variants.values()}, key=str)
check("全候補が同じ件数で評価されている", len(variant_eval_ns) == 1,
      " / ".join(str(v) for v in variant_eval_ns))

# ---------------------------------------------------------------------------
# 6. 評価件数から言える差の下限と、報告された差
# ---------------------------------------------------------------------------
print("\n=== 6. 評価件数から言える差の下限 ===")
run_eval_ns = sorted({dig(r, "conditions.eval_n") for r in runs.values()}, key=str)
check("実験記録の評価件数が1つにそろっている", len(run_eval_ns) == 1,
      " / ".join(str(v) for v in run_eval_ns) or "記録がありません")

eval_n = variant_eval_ns[0] if len(variant_eval_ns) == 1 and isinstance(
    variant_eval_ns[0], int) else None
if eval_n is None and len(run_eval_ns) == 1 and isinstance(run_eval_ns[0], int):
    eval_n = run_eval_ns[0]
elif isinstance(eval_n, int) and len(run_eval_ns) == 1 and run_eval_ns[0] != eval_n:
    check("実験記録と配布候補の評価件数が一致している", False,
          f"実験 {run_eval_ns[0]} / 配布候補 {eval_n}（件数が違う比較は成立しません）")

floor = None
if isinstance(eval_n, int) and eval_n >= 1:
    floor = 1 / eval_n
    print(f"  評価 {eval_n} 件で刻める最小の差: 1/{eval_n} = {floor:.3f}")
    for p in (0.200, 0.500, 0.833):
        lo, hi = wald(p, eval_n)
        print(f"  正解率 {p:.3f} の 95% の目安: {lo:.3f}〜{hi:.3f}（幅 ±{(hi - lo) / 2:.3f}）")
    if eval_n <= 30:
        note(f"評価 {eval_n} 件では 1/{eval_n} = {floor:.3f} 未満の差は表現できません。"
             "2件差（例 0.200 と 0.267）は 30 件では言えません（セッション9の実測）")
else:
    print("  eval_n が1つに定まらないので計算できません。")

print("\n--- 報告された差（claims）---")
claim_count = 0
for owner_id, record in sorted(list(runs.items()) + list(variants.items())):
    is_variant = record.get("schema") == VARIANT_SCHEMA
    for claim in as_list(record.get("claims")):
        claim_count += 1
        if not isinstance(claim, dict):
            check(f"{owner_id}: claims の要素がオブジェクトである", False, type(claim).__name__)
            continue
        metric = str(claim.get("metric"))
        wording = str(claim.get("as"))
        against = str(claim.get("vs"))
        label = f"{owner_id}: 「{against} と比べて {metric} が {wording}」"
        if metric not in CLAIM_METRICS:
            check(f"{label} の metric が {' / '.join(CLAIM_METRICS)}", False, metric)
            continue
        if wording not in CLAIM_WORDS:
            check(f"{label} の as が {' / '.join(CLAIM_WORDS)} のどれか", False, wording)
            continue
        family = variants if is_variant else runs
        if against not in family:
            check(f"{label} の比較相手が同じ種類の記録として実在する", False, against)
            continue

        def metric_of(rec: dict, name: str):
            if rec.get("schema") == VARIANT_SCHEMA:
                return dig(rec, f"quality.{name}")
            value = dig(rec, f"results.after.{name}")
            return value if is_number(value) else dig(rec, f"results.before.{name}")

        here = metric_of(record, metric)
        there = metric_of(family[against], metric)
        if not (is_number(here) and is_number(there)) or floor is None:
            check(f"{label} を数値で確かめられる", False, "値が読めません")
            continue
        diff, dlo, dhi = wald_diff(there, eval_n, here, eval_n)
        if wording == "改善":
            ok = diff >= floor - 1e-9
        elif wording == "劣化":
            ok = diff <= -floor + 1e-9
        else:
            ok = abs(diff) < floor - 1e-9 or (dlo < 0 < dhi)
        check(f"{label} が件数で言える差になっている", ok,
              f"差 {diff:+.3f} / {eval_n} 件で刻める最小の差 {floor:.3f}")
        if wording in ("改善", "劣化") and dlo < 0 < dhi:
            note(f"{owner_id}: {metric} の差 {diff:+.3f} は 95% の目安が "
                 f"{dlo:+.3f}〜{dhi:+.3f} で 0 をまたぎます。"
                 "「改善／劣化」と断定するなら件数を増やすか、断定を弱めてください")
check("差の主張（claims）が1件以上ある", claim_count >= 1,
      "結論を書くなら、何と比べて何が動いたのかを記録に残してください")

# ---------------------------------------------------------------------------
# 7. 再現手順
# ---------------------------------------------------------------------------
print("\n=== 7. 再現手順 ===")
text = report_text.get("06-reproduce.md", "")
if text.strip():
    missing = [label for label, pattern in REPRODUCE_MARKERS
               if not re.search(pattern, text, re.IGNORECASE)]
    check("再現手順にバージョン・シード・データのハッシュがそろっている", not missing,
          f"欠け: {', '.join(missing)}" if missing else "")
    absent = [stage_id for stage_id in order
              if str(stages[stage_id].get("command") or "").strip()
              and str(stages[stage_id]["command"]).strip() not in text]
    check("再現手順に全段の実行コマンドが載っている", not absent,
          f"載っていない段: {', '.join(absent)}" if absent else f"{len(order)} 段すべて")
    ids_in_doc = [key for key in records if key in text]
    check("再現手順が記録の id に言及している（コマンドと記録が対応している）",
          bool(ids_in_doc), f"{len(ids_in_doc)}/{len(records)} 件に言及")

# ---------------------------------------------------------------------------
# 8. モデルカード（セッション14の必須9項目）
# ---------------------------------------------------------------------------
print("\n=== 8. モデルカード（必須9項目）===")
print(f"  必須項目: {', '.join(label for label, _ in MODEL_CARD_ITEMS)}")
card = report_text.get("05-model-card.md", "")
if card.strip():
    lacking = check_model_card(card)
    check("モデルカードの必須9項目がそろっている", not lacking,
          f"欠け: {', '.join(lacking)}" if lacking else "")
    named = [v for v in variants if v in card]
    check("モデルカードがどの配布候補を配るのかに言及している", bool(named),
          f"{len(named)}/{len(variants)} 件に言及")

# ---------------------------------------------------------------------------
# 9. 次に何を試すかの提案（根拠の照合）
# ---------------------------------------------------------------------------
print("\n=== 9. 次に何を試すかの提案（根拠の照合）===")
proposals: list[dict] = []
if not check("提案の記録（proposals.json）がある", proposals_path.exists()):
    print("   ・提案は文章だけでなく、根拠（どの記録のどの値を見たのか）を機械可読に残します。")
else:
    payload, error = read_json(proposals_path)
    if error or not isinstance(payload, dict):
        check("proposals.json が1件のオブジェクトとして読める", False,
              error or type(payload).__name__)
        payload = {}
    check(f"schema が {PROPOSALS_SCHEMA}", payload.get("schema") == PROPOSALS_SCHEMA,
          str(payload.get("schema")))
    check("written_at が読める", parse_time(payload.get("written_at")) is not None,
          str(payload.get("written_at")))
    proposals = [p for p in as_list(payload.get("proposals")) if isinstance(p, dict)]
    check(f"提案が {args.min_proposals} 件以上ある", len(proposals) >= args.min_proposals,
          f"{len(proposals)} 件")

priorities = [p.get("priority") for p in proposals]
if proposals:
    check("優先順位が 1 から始まる連番になっている（重複なし）",
          sorted(x for x in priorities if isinstance(x, int)) == list(range(1, len(proposals) + 1)),
          f"{priorities}")

models_by_proposal: dict[str, set] = {}
for proposal in proposals:
    pid = str(proposal.get("id") or "")
    label = f"提案 {pid or '(id なし)'}"
    check(f"{label}: id が3文字以上の識別子である",
          bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}", pid)), pid)
    check(f"{label}: 何を試すかが30文字以上で書かれている",
          len(str(proposal.get("proposal") or "").strip()) >= 30,
          f"{len(str(proposal.get('proposal') or '').strip())} 文字")
    check(f"{label}: 期待する効果が書かれている（15文字以上）",
          len(str(proposal.get("expected") or "").strip()) >= 15,
          f"{len(str(proposal.get('expected') or '').strip())} 文字")
    check(f"{label}: かかる手間・時間が書かれている（10文字以上）",
          len(str(proposal.get("cost") or "").strip()) >= 10,
          f"{len(str(proposal.get('cost') or '').strip())} 文字")
    check(f"{label}: axis が {' / '.join(AXES)} のどれか", proposal.get("axis") in AXES,
          str(proposal.get("axis")))

    evidence = [e for e in as_list(proposal.get("evidence")) if isinstance(e, dict)]
    if not check(f"{label}: 根拠が1件以上ある（実測値への参照）", bool(evidence),
                 "「たぶん効く」は提案ではありません"):
        continue
    seen_models: set = set()
    for item in evidence:
        source = str(item.get("source") or "")
        field = str(item.get("field") or "")
        target = records.get(source)
        if target is None:
            target = next((r for r in records.values()
                           if r["_file"] == norm_path(source).split("/")[-1]), None)
        if not check(f"{label}: 根拠 {source!r} が実在する記録を指している",
                     target is not None):
            continue
        actual = dig(target, field)
        if actual is None:
            check(f"{label}: 根拠のパス {field!r} がその記録から読める", False,
                  f"{source} に {field} はありません")
            continue
        claimed = item.get("value")
        if is_number(actual) and is_number(claimed):
            same = abs(actual - claimed) <= 1e-9 + 1e-6 * abs(actual)
        else:
            same = str(actual) == str(claimed)
        check(f"{label}: 根拠の値が記録と一致する（{source}.{field}）", same,
              f"記録 {fmt(actual)} / 提案に書いた値 {fmt(claimed)}")
        model = dig(target, "conditions.model")
        if model:
            seen_models.add(str(model))
    models_by_proposal[pid] = seen_models

if proposals:
    spine = [pid for pid, seen in models_by_proposal.items() if len(seen) >= 2]
    check("モデルを変えた2条件の実測を根拠にした提案が1件以上ある", bool(spine),
          " / ".join(spine) if spine else
          "同じデータ・同じ手法でもモデルを変えると指標が動きます。"
          "その実測を根拠に順位を付けてください")
    top = next((p for p in proposals if p.get("priority") == 1), None)
    if top is not None and top.get("axis") != SPINE_AXIS:
        check(f"優先順位1位（{top.get('id')}）が「{SPINE_AXIS}」以外なら、"
              "そちらを先にする理由が notes に書かれている",
              len(str(top.get("notes") or "").strip()) >= 30,
              f"axis={top.get('axis')} / notes="
              f"{len(str(top.get('notes') or '').strip())} 文字")

text = report_text.get("07-next-steps.md", "")
if text.strip() and proposals:
    check("提案の文書が表になっている（Markdown の表がある）",
          bool(re.search(r"^\s*\|.+\|", text, re.MULTILINE)))
    absent = [str(p.get("id")) for p in proposals if str(p.get("id")) not in text]
    check("提案の文書が全提案に言及している", not absent,
          f"言及なし: {', '.join(absent)}" if absent else f"{len(proposals)} 件すべて")

# ---------------------------------------------------------------------------
# 貼れる Markdown 表
# ---------------------------------------------------------------------------
print("\n=== パイプライン（06-reproduce.md に貼れます）===")
print("| 段 | 種類 | 実行場所 | 依存 | 中間成果物 | 再開可 |")
print("| :--- | :--- | :--- | :--- | :--- | :--- |")
for stage_id in order:
    stage = stages[stage_id]
    print(f"| {stage_id} | {stage.get('kind', '-')} | {stage.get('run_on', '-')} | "
          f"{'/'.join(str(x) for x in as_list(stage.get('depends_on'))) or '起点'} | "
          f"{'<br>'.join(norm_path(a) for a in as_list(stage.get('artifacts')))} | "
          f"{fmt(stage.get('resumable'))} |")

print("\n=== 実験記録（02-training.md に貼れます）===")
print("| run_id | 種別 | 変更点 | モデル | task | split | step | r | ml | dtype | "
      "loss 始→終 | 正解率 前→後 | 形式遵守率 前→後 |")
print("| :--- | :--- | :--- | :--- | :--- | :--- | --: | --: | --: | :--- | :--- | :--- | :--- |")
for run_id, record in sorted(runs.items()):
    c = record.get("conditions") or {}
    changed = "/".join(str(x) for x in as_list(record.get("changed_field"))) or "起点"
    print(f"| {run_id} | {record.get('kind', '-')} | {changed} | "
          f"{str(c.get('model', '-')).split('/')[-1]} | {c.get('task', '-')} | "
          f"{c.get('split', '-')} | {fmt(c.get('steps'))} | {fmt(c.get('lora_r'))} | "
          f"{fmt(c.get('max_length'))} | {c.get('dtype', '-')} | "
          f"{fmt(dig(record, 'results.first_loss'))} → "
          f"{fmt(dig(record, 'results.last_loss'))} | "
          f"{fmt(dig(record, 'results.before.accuracy'))} → "
          f"{fmt(dig(record, 'results.after.accuracy'))} | "
          f"{fmt(dig(record, 'results.before.format_rate'))} → "
          f"{fmt(dig(record, 'results.after.format_rate'))} |")

print("\n=== 3点比較表（04-quantization.md に貼れます）===")
unit = SPEED_METRICS.get(metrics[0], "速度") if len(metrics) == 1 else "速度"
ref_size = dig(reference, "size.size_mib") if reference else None
ref_speed = dig(reference, "speed.value") if reference else None
ref_accuracy = dig(reference, "quality.accuracy") if reference else None
print(f"| variant_id | 手段 | 量子化 | サイズ MiB | 対基準 | {unit} | 対基準 | "
      "正解率 | 対基準 | 形式遵守率 | 近似 |")
print("| :--- | :--- | :--- | --: | --: | --: | --: | --: | --: | --: | :--- |")
for variant_id, record in sorted(variants.items()):
    size = dig(record, "size.size_mib")
    speed = dig(record, "speed.value")
    accuracy = dig(record, "quality.accuracy")
    size_ratio = (f"{size / ref_size * 100:.1f}%"
                  if is_number(size) and is_number(ref_size) and ref_size else "-")
    speed_ratio = (f"{speed / ref_speed * 100:.1f}%"
                   if is_number(speed) and is_number(ref_speed) and ref_speed else "-")
    acc_diff = (f"{accuracy - ref_accuracy:+.3f}"
                if is_number(accuracy) and is_number(ref_accuracy) else "-")
    approx = "/".join(axis for axis, key in (("サイズ", "size.approx"), (unit, "speed.approx"),
                                             ("精度", "quality.approx"))
                      if dig(record, key) is True) or "なし"
    print(f"| {variant_id} | {dig(record, 'recipe.method')} | {dig(record, 'recipe.quant')} | "
          f"{fmt(size, 1)} | {size_ratio} | {fmt(speed, 2)} | {speed_ratio} | "
          f"{fmt(accuracy)} | {acc_diff} | {fmt(dig(record, 'quality.format_rate'))} | "
          f"{approx} |")

if proposals:
    print("\n=== 次に何を試すか（07-next-steps.md に貼れます）===")
    print("| 順位 | id | 軸 | 試すこと | 期待 | 手間 | 根拠 |")
    print("| --: | :--- | :--- | :--- | :--- | :--- | :--- |")
    for proposal in sorted(proposals, key=lambda p: p.get("priority") or 99):
        evidence = [f"{e.get('source')}.{e.get('field')}={fmt(e.get('value'))}"
                    for e in as_list(proposal.get("evidence")) if isinstance(e, dict)]
        print(f"| {fmt(proposal.get('priority'))} | {proposal.get('id')} | "
              f"{proposal.get('axis')} | {str(proposal.get('proposal'))[:40]} | "
              f"{str(proposal.get('expected'))[:24]} | {str(proposal.get('cost'))[:20]} | "
              f"{'<br>'.join(evidence)} |")

# ---------------------------------------------------------------------------
print()
if notes:
    print(f"注意（要件ではないが確認する価値がある点）: {len(notes)} 件")
if failures:
    print(f"{len(failures)} 件の要件を満たしていません:")
    for label in failures:
        print(f"  - {label}")
    print("\n指標の高さも小ささも点検していません。足りないのは「設計」と「記録」です。")
    sys.exit(1)

print("提出物の要件をすべて満たしています。")
print("ただしこの点検は形式と算術だけを見ています。**他人がこの記録だけで同じモデルを"
      "作り直せるか**は、自分の再現手順を上から順に実行し直して確かめてください。")
print("それが本章の唯一の合格条件です。")
