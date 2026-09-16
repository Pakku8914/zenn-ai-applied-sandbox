#!/usr/bin/env python3
"""セッション14の参照実装：実験の記録・データの版・モデルカード・環境の固定。

「半年後の自分が同じモデルを作れる」ために必要な道具だけを集めてある。
**モデルの重みを読まない。学習もしない。** 読むのは JSON・JSONL・ソースコードだけ。

自己検証は src/session14/verify.py が行う。
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import platform
import re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

SANDBOX = Path(__file__).resolve().parents[2]
DATA = SANDBOX / "data"
RUNS = SANDBOX / "runs"

# 実験記録のスキーマ名（中間プロジェクト1で決めたものをそのまま使う）
SCHEMA = "mid01-experiment/1"

# 中間プロジェクト1が要求している条件（src/mid01/verify.py の COND_EXPERIMENT と一致させる）
COND_EXPERIMENT = ["model", "task", "steps", "lora_r", "max_length", "dtype", "seed", "split"]
# 本章の要求。上の8項目に batch_size を足した9項目を「条件」の下限とする
COND_REQUIRED = ["model", "task", "steps", "lora_r", "max_length", "batch_size",
                 "dtype", "seed", "split"]
# 無くても落とさないが、無いと後から条件を再現しにくい項目
COND_RECOMMENDED = ["lora_alpha", "lr", "grad_accum", "epochs", "eval_n", "target_modules"]
# 表記が揺れても拾う別名
ALIASES = {
    "split": ("split", "split_method", "data_split"),
    "max_length": ("max_length", "seq_len"),
    "steps": ("steps", "max_steps"),
}

# ftkit.train.TrainConfig のフィールド（API契約。asdict でそのまま記録に流せる）
TRAINCONFIG_FIELDS = ["task", "epochs", "batch_size", "grad_accum", "lr",
                      "max_length", "seed", "max_steps", "log_every", "warmup_ratio"]

DATA_FILES = ("train.jsonl", "valid.jsonl", "test.jsonl", "preference.jsonl")
PATTERN_FILES = ("train_pattern.jsonl", "valid_pattern.jsonl", "test_pattern.jsonl")

# 環境の記録に必ず入れる項目
ENV_REQUIRED = ["python", "platform", "machine", "omp_num_threads",
                "torch", "transformers", "peft"]
ENV_PACKAGES = ("torch", "transformers", "peft", "trl", "datasets", "numpy")


# ---------------------------------------------------------------------------
# 1. 実験記録の監査（条件が揃っているか）
# ---------------------------------------------------------------------------
def conditions_of(record: dict) -> dict:
    """記録から「条件」の部分を取り出す。平らな記録はそのまま条件として扱う。"""
    inner = record.get("conditions")
    return inner if isinstance(inner, dict) else record


def _present(conditions: dict, key: str) -> bool:
    for name in ALIASES.get(key, (key,)):
        if conditions.get(name) not in (None, ""):
            return True
    return False


def missing_conditions(record: dict, required: list[str] | None = None) -> list[str]:
    """記録に入っていない条件を、要求した順で返す。"""
    conditions = conditions_of(record)
    return [key for key in (required or COND_REQUIRED) if not _present(conditions, key)]


def thin_conditions(record: dict) -> list[str]:
    """必須ではないが、無いと再現しにくい項目を返す。"""
    conditions = conditions_of(record)
    return [key for key in COND_RECOMMENDED if not _present(conditions, key)]


def audit_runs(runs_dir: Path | str = RUNS, pattern: str = "compare_*.json") -> list[dict]:
    """runs/ の記録を1件ずつ監査する（ファイルが無ければ空のリストを返す）。"""
    rows: list[dict] = []
    root = Path(runs_dir)
    if not root.exists():
        return rows
    for path in sorted(root.glob(pattern)):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            rows.append({"name": path.name, "error": f"{type(exc).__name__}",
                         "missing": list(COND_REQUIRED), "thin": list(COND_RECOMMENDED)})
            continue
        if not isinstance(record, dict):
            rows.append({"name": path.name, "error": "オブジェクトでない",
                         "missing": list(COND_REQUIRED), "thin": list(COND_RECOMMENDED)})
            continue
        rows.append({"name": path.name, "keys": len(record),
                     "missing": missing_conditions(record), "thin": thin_conditions(record)})
    return rows


def record_keys_in_source(source: str) -> set[str] | None:
    """スクリプトが実験記録に書き出しているキーをソースから取り出す。

    実際に学習を回さなくても「何を記録していないか」が分かる。取り出せなければ None。
    """
    try:
        start = source.index("write_text(json.dumps(")
        end = source.index("ensure_ascii", start)
    except ValueError:
        return None
    return set(re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"\s*:', source[start:end]))


def mid01_required_conditions(path: Path | str | None = None) -> list[str] | None:
    """中間プロジェクト1の点検スクリプトが要求している条件を読み取る。

    記録のスキーマが章をまたいでずれていないことを機械的に確かめるために使う。
    """
    target = Path(path) if path else SANDBOX / "src" / "mid01" / "verify.py"
    if not target.exists():
        return None
    match = re.search(r"COND_EXPERIMENT\s*=\s*(\[[^\]]*\])", target.read_text(encoding="utf-8"))
    if not match:
        return None
    return list(ast.literal_eval(match.group(1)))


def upgrade_record(raw: dict, config: dict, split: str, run_id: str | None = None,
                   environment: dict | None = None, data_version_map: dict | None = None,
                   kind: str = "experiment") -> dict:
    """条件の足りない記録を、条件が揃った記録に作り直す。

    `config` は `dataclasses.asdict(TrainConfig(...))` の結果を渡す。これで
    max_length・batch_size・seed が埋まる。**split は TrainConfig に無いので手で足す。**
    """
    conditions: dict = {
        "model": raw.get("model"),
        "task": raw.get("task") or config.get("task"),
        "steps": raw.get("steps"),
        "lora_r": raw.get("lora_r"),
        "dtype": raw.get("dtype"),
        "eval_n": raw.get("eval_n"),
        "split": split,
    }
    for key in ("max_length", "batch_size", "grad_accum", "epochs", "lr", "seed"):
        if key in config:
            conditions[key] = config[key]
    if raw.get("lr") is not None:
        conditions["lr"] = raw["lr"]
    results = {
        "first_loss": raw.get("first_loss"),
        "last_loss": raw.get("last_loss"),
        "median_step_seconds": raw.get("median_step_seconds"),
        "train_seconds": raw.get("train_seconds"),
        "peak_rss_gb": raw.get("peak_rss_gb"),
        "before": raw.get("before"),
        "after": raw.get("after"),
    }
    return {
        "schema": SCHEMA,
        "run_id": run_id or "run-unnamed",
        "kind": kind,
        "conditions": conditions,
        "results": results,
        "environment": environment if environment is not None else env_record(),
        "data_version": data_version_map if data_version_map is not None else {},
    }


# ---------------------------------------------------------------------------
# 2. シードの設定位置（ソースを読むだけで分かる欠陥）
# ---------------------------------------------------------------------------
def audit_seed_placement(source: str) -> list[str]:
    """シードがモデル構築の前に固定されているかをソースから点検する。"""
    problems: list[str] = []
    imported = bool(re.search(r"from\s+ftkit\.train\s+import[^\n]*\bset_seed\b", source)
                    or re.search(r"^\s*(import\s+ftkit\.train|from\s+\.train\s+import)", source,
                                 re.MULTILINE))
    calls = [m.start() for m in re.finditer(r"\bset_seed\s*\(", source)]
    builds = [m.start() for m in re.finditer(r"\b(load_model|attach_lora)\s*\(", source)]
    if not imported:
        problems.append("set_seed を import していない")
    if not calls:
        problems.append("set_seed を呼んでいない")
    elif builds and min(calls) > min(builds):
        problems.append("set_seed の呼び出しがモデル構築より後ろにある")
    return problems


# ---------------------------------------------------------------------------
# 3. データの版（ハッシュで固定する）
# ---------------------------------------------------------------------------
def file_digest(path: Path | str, length: int = 12) -> str:
    """ファイルの sha256 の先頭 length 桁。中身が1バイト変われば必ず変わる。"""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()[:length]


def line_count(path: Path | str) -> int:
    with open(path, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def data_version(data_dir: Path | str = DATA, names: tuple[str, ...] = DATA_FILES) -> dict:
    """データの版：ファイルごとの sha256（先頭12桁）と件数。"""
    root = Path(data_dir)
    out: dict[str, dict] = {}
    for name in names:
        path = root / name
        if path.exists():
            out[name] = {"sha256_12": file_digest(path), "lines": line_count(path)}
    return out


def combined_digest(version_map: dict, length: int = 12) -> str:
    """複数ファイルの版を1つの文字列にまとめる（記録や版名に使える）。"""
    digest = hashlib.sha256()
    for name in sorted(version_map):
        digest.update(f"{name}:{version_map[name]['sha256_12']}\n".encode("utf-8"))
    return digest.hexdigest()[:length]


# ---------------------------------------------------------------------------
# 4. モデルカード
# ---------------------------------------------------------------------------
# 必須項目（項目名, その項目が書かれていると判断する正規表現のリスト＝すべて満たすこと）
MODEL_CARD_ITEMS: list[tuple[str, list[str]]] = [
    ("モデル名", [r"モデル名"]),
    ("ベースモデルとライセンス", [r"ベースモデル", r"ライセンス"]),
    ("データの版", [r"データの版", r"sha256"]),
    ("ハイパーパラメータ", [r"max_length", r"\blr\b|学習率"]),
    ("シード", [r"シード|seed", r"\d{6,}"]),
    ("環境", [r"torch", r"[Pp]ython"]),
    ("評価結果", [r"正解率", r"形式遵守率"]),
    ("既知の限界", [r"既知の限界|限界|できないこと"]),
    ("配布形式", [r"配布形式"]),
]


def check_model_card(text: str) -> list[str]:
    """モデルカードに書かれていない必須項目を返す（空なら9項目そろっている）。"""
    return [label for label, patterns in MODEL_CARD_ITEMS
            if not all(re.search(pattern, text) for pattern in patterns)]


# 必須9項目がそろった記入例（数値は 2026-08-15 実測 / aarch64 / CPU 2コア / メモリ 5.8GB /
# Python 3.12.13 / torch 2.13.0+cpu / OMP_NUM_THREADS=2 の測定条件で得たもの）
EXAMPLE_CARD = """# モデルカード: helpdesk-format-qwen05b-v1

## 用途と対象
みなと商事の社内ヘルプデスク問い合わせに、【区分】【担当】【期限】の3行で回答します。
社内の一次受けの下書き用です。人の確認なしに回答を送信する用途には使えません。

## モデル名と版
- モデル名: helpdesk-format-qwen05b
- 版: v1（2026-08-15 作成）
- 対応する実験記録: exp-05-format-bf16（runs/mid01/exp-05-format-bf16.json）

## ベースモデルとライセンス
- ベースモデル: Qwen/Qwen2.5-0.5B-Instruct
- ライセンス: Apache-2.0（2026-08-15 時点の配布元表記。配布前に配布元で必ず再確認する）
- 学習データの由来: 架空企業の合成データ（tools/make_dataset.py が生成・再配布可）

## データの版
- 分割方式: 型単位（train 600 / valid 150 / test 150）
- data/train_pattern.jsonl sha256:xxxxxxxxxxxx（12桁）
- 生成コマンド: python tools/make_dataset.py && python src/session03/split_by_pattern.py

## ハイパーパラメータ
- 手法: LoRA（r=16 / alpha=32 / dropout=0.05）
- max_length=192 / batch_size=2 / grad_accum=1 / lr=2e-4 / max_steps=80 / dtype=bf16

## シードと決定性
- シード: 20260815（set_seed をモデル構築の前に呼ぶ）
- 生成: do_sample=False（決定的）

## 環境
- Python 3.12.13 / torch 2.13.0+cpu / transformers 4.57.6 / peft 0.20.0
- aarch64 / CPU 2コア / メモリ 5.8GB / OMP_NUM_THREADS=2

## 評価結果（test 30件）
- 正解率 0.033 → 0.833 ／ 形式遵守率 0.300 → 1.000
- loss 1.5290 → 0.0447 ／ 学習 664.6 秒（7.27 秒/step）／ peak RSS 2.29GB

## 既知の限界
- 6区分の外の問い合わせも、必ずどれかの区分に押し込みます
- test 30件での測定です。正解率 0.833 の幅は広いと考えてください
- 学習データは合成データです。実際の問い合わせ文の分布とは違います

## 配布形式
- LoRAアダプタ（約 3.5 MiB・読み込み側に peft が必要）
- 統合済み（957.5 MiB）／GGUF Q4_K_M（379.4 MiB）
"""


def drop_lines(text: str, keyword: str) -> str:
    """keyword を含む行を落とす（チェッカーの検証に使う）。"""
    return "\n".join(line for line in text.splitlines() if keyword not in line)


# ---------------------------------------------------------------------------
# 5. 環境の記録とバージョンの固定
# ---------------------------------------------------------------------------
def env_record() -> dict:
    """実験記録に埋め込む環境の情報（モデルを読まない）。"""
    record: dict = {
        "python": platform.python_version(),
        "platform": platform.system(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "omp_num_threads": os.environ.get("OMP_NUM_THREADS", "未設定"),
    }
    for dist in ENV_PACKAGES:
        try:
            record[dist] = version(dist)
        except PackageNotFoundError:
            record[dist] = None
    return record


def missing_env(record: dict) -> list[str]:
    return [key for key in ENV_REQUIRED if not record.get(key)]


def is_cpu_wheel(torch_version: str | None) -> bool:
    """CPU 専用 wheel かどうか（+cpu が付いているか）。"""
    return bool(torch_version) and torch_version.endswith("+cpu")


def audit_pinning(dockerfile: str, requirements: str, compose: str = "") -> dict:
    """バージョンが固定されているかを点検する（latest 依存を弾く）。"""
    problems: list[str] = []
    notes: list[str] = []

    for image in re.findall(r"^FROM\s+(\S+)", dockerfile, re.MULTILINE):
        if ":" not in image:
            problems.append(f"FROM にタグが無い（{image}）")
        elif image.rsplit(":", 1)[1] == "latest":
            problems.append(f"FROM が latest（{image}）")
    if "HF_HOME" not in dockerfile:
        problems.append("HF_HOME が固定されていない（モデルの取得先が環境で変わる）")

    cpu_index = "download.pytorch.org/whl/cpu" in requirements
    for line in requirements.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-"):
            continue
        if "==" not in stripped:
            problems.append(f"バージョンが固定されていない（{stripped}）")
        elif stripped.startswith("torch=="):
            if not is_cpu_wheel(stripped.split("==", 1)[1]):
                problems.append(f"torch が CPU 専用 wheel でない（{stripped}）")
            if not cpu_index:
                problems.append("CPU 専用 wheel の取得先（whl/cpu）が指定されていない")

    for image in re.findall(r"image:\s*(\S+)", compose):
        if "@sha256:" in image:
            continue
        tag = image.rsplit(":", 1)[1] if ":" in image else ""
        if tag == "latest" or not tag:
            problems.append(f"compose の image が latest（{image}）")
        else:
            notes.append(f"{image} はタグ固定だが可変タグ。厳密にするなら digest で固定する")

    return {"problems": problems, "notes": notes}
