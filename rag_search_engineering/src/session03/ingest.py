#!/usr/bin/env python3
"""取り込みパイプライン（冪等）。

  収集 → 抽出 → 正規化 → ボイラープレート除去 → 除外判定 → 重複除去
  → メタデータ付与 → 出力 → 差分の記録

何度実行しても同じ出力になる（冪等）ことを設計の第一条件にしている。
そのためレコードには実行時刻を入れない。実行時刻を入れると、2回目の実行で
全件が「変わった」ように見えてしまう。

  python src/session03/ingest.py             取り込んで out/ に書き出す
  python src/session03/ingest.py --dry-run   書き出さずに差分だけ表示する
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from clean import (  # noqa: E402
    clean_text, content_hash, has_broken_chars, is_effectively_empty,
    is_order_suspect, jaccard, shingles,
)
from dirty_corpus import load_raw  # noqa: E402

PIPELINE_VERSION = "s03-1"
MIN_CHARS = 10  # これ未満は本文が取れていないとみなす
SIMILARITY_THRESHOLD = 0.80  # 近重複とみなす Jaccard 係数
OUT_LABEL = "src/session03/out"  # 表示用の相対パス
OUT_DIR = Path(__file__).resolve().parent / "out"

# 元システムの公開範囲 → 検索側の visibility。
# 未知の値・未設定は「最も狭い範囲」に倒す（fail closed）。開いてから直すと、
# 直すまでの間ずっと見えてはいけない文書が検索できてしまう。
ACL_TO_VISIBILITY = {"all": "all", "dept": "dept", "manager": "manager"}
DEFAULT_VISIBILITY = "manager"

# doc_class が元システムに無いときだけ使う推定ルール（最後の手段）
SOURCE_TYPE_RULES = [
    (re.compile(r"規程|規則|細則"), "policy"),
    (re.compile(r"手順|要領|チェックリスト|まとめ"), "procedure"),
    (re.compile(r"お知らせ|通知|案内"), "notice"),
]
DEFAULT_SOURCE_TYPE = "faq"


@dataclass
class IngestResult:
    records: list[dict] = field(default_factory=list)
    dropped: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    diff: dict[str, list[str]] = field(default_factory=dict)

    def dropped_counts(self) -> dict[str, int]:
        counts = {"empty": 0, "exact_dup": 0, "near_dup": 0}
        for d in self.dropped:
            counts[d["reason"]] = counts.get(d["reason"], 0) + 1
        return counts

    def review_items(self) -> list[dict]:
        return [r for r in self.records if r["needs_review"]]


# --- 同定とメタデータ -------------------------------------------------------
def make_doc_id(key: str) -> str:
    """出所の安定キーから doc_id を作る。

    連番にしない。連番は「入力の並び」に依存するため、1件増えただけで
    以降の ID がすべてずれ、差分更新も権限の紐づけも成立しなくなる。
    """
    return "HD-" + key.replace("/", "-")


def title_from_path(path: str) -> str:
    """ファイル名から表題を作る（末尾の日付サフィックスは落とす）。"""
    return re.sub(r"_\d{8}$", "", Path(path).stem)


def guess_source_type(title: str) -> str:
    for pattern, value in SOURCE_TYPE_RULES:
        if pattern.search(title):
            return value
    return DEFAULT_SOURCE_TYPE


def source_priority(path: str) -> int:
    """同じ内容が複数の場所にあるとき、どれを残すかの優先度（小さいほど優先）。

    技術ではなく業務の決めごとなので、仕様書に明記して固定する。
    """
    if "backup/" in path:
        return 2
    if re.search(r" \(\d+\)\.[0-9a-z]+$", path):
        return 1
    return 0


def to_record(raw: dict) -> tuple[dict, list[str]]:
    """抽出結果1件を、検索側が使うレコードに変換する。"""
    warnings: list[str] = []
    reasons: list[str] = []

    body = clean_text(raw["text"])
    doc_id = make_doc_id(raw["key"])
    dms = raw["dms"]

    if is_order_suspect(raw["text"], raw.get("alt")):
        reasons.append("order_suspect")
    if has_broken_chars(body):
        reasons.append("mojibake")

    acl = dms.get("acl")
    if acl in ACL_TO_VISIBILITY:
        visibility = ACL_TO_VISIBILITY[acl]
    else:
        visibility = DEFAULT_VISIBILITY
        reasons.append("acl_unknown")

    source_type = dms.get("doc_class")
    title = title_from_path(raw["path"])
    if not source_type:
        source_type = guess_source_type(title)
        warnings.append(f"source_type を推定しました: {doc_id} -> {source_type}（DMS の doc_class が空）")

    record = dict(
        doc_id=doc_id,
        title=title,
        body=body,
        category=dms["folder"],
        source_type=source_type,
        source_format=raw["fmt"],
        source_path=raw["path"],
        updated_at=dms["mtime"],
        visibility=visibility,
        dept=dms["dept"],
        lang="ja",
        content_hash=content_hash(body),
        needs_review=bool(reasons),
        review_reasons=reasons,
    )
    return record, warnings


# --- パイプライン本体 -------------------------------------------------------
def run_ingest(raws: list[dict], previous: dict[str, str] | None = None) -> IngestResult:
    previous = previous or {}
    result = IngestResult()
    staged: list[dict] = []

    for raw in raws:
        record, warnings = to_record(raw)
        result.warnings.extend(warnings)
        if is_effectively_empty(record["body"], MIN_CHARS):
            # 空判定はボイラープレート除去の「あと」に行う。先に判定すると、
            # ナビだけのページが「本文あり」として通ってしまう
            result.dropped.append(dict(path=raw["path"], reason="empty", kept=None))
            continue
        record["_priority"] = source_priority(raw["path"])
        staged.append(record)

    # 完全重複：本文の指紋が一致するもの。優先度の高いパスを残す
    seen: dict[str, dict] = {}
    survivors: list[dict] = []
    for record in sorted(staged, key=lambda r: (r["_priority"], r["doc_id"])):
        keeper = seen.get(record["content_hash"])
        if keeper:
            result.dropped.append(
                dict(path=record["source_path"], reason="exact_dup", kept=keeper["doc_id"])
            )
            continue
        seen[record["content_hash"]] = record
        survivors.append(record)

    # 近重複：文字 5-gram の Jaccard 係数。更新日の新しい方を残す
    kept: list[dict] = []
    for record in sorted(survivors, key=lambda r: r["doc_id"]):
        record["_shingles"] = shingles(record["body"])
        index = next(
            (i for i, k in enumerate(kept)
             if jaccard(record["_shingles"], k["_shingles"]) >= SIMILARITY_THRESHOLD),
            None,
        )
        if index is None:
            kept.append(record)
            continue
        other = kept[index]
        newer, older = (record, other) if _is_newer(record, other) else (other, record)
        kept[index] = newer
        result.dropped.append(
            dict(path=older["source_path"], reason="near_dup", kept=newer["doc_id"])
        )

    result.records = sorted(
        ({k: v for k, v in r.items() if not k.startswith("_")} for r in kept),
        key=lambda r: r["doc_id"],
    )
    result.diff = compute_diff(result.records, previous)
    return result


def _is_newer(a: dict, b: dict) -> bool:
    return (a["updated_at"], a["doc_id"]) > (b["updated_at"], b["doc_id"])


def compute_diff(records: list[dict], previous: dict[str, str]) -> dict[str, list[str]]:
    current = {r["doc_id"]: r["content_hash"] for r in records}
    both = set(current) & set(previous)
    return dict(
        added=sorted(set(current) - set(previous)),
        changed=sorted(d for d in both if current[d] != previous[d]),
        removed=sorted(set(previous) - set(current)),
        unchanged=sorted(d for d in both if current[d] == previous[d]),
    )


# --- 入出力 -----------------------------------------------------------------
def load_state(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("pipeline_version") != PIPELINE_VERSION:
        # パイプラインを変えたら差分の意味が変わる。全件を作り直す
        return {}
    return state.get("docs", {})


def write_output(result: IngestResult, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "docs.jsonl").open("w", encoding="utf-8") as f:
        for record in result.records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    state = dict(
        pipeline_version=PIPELINE_VERSION,
        docs={r["doc_id"]: r["content_hash"] for r in result.records},
    )
    (out_dir / "state.json").write_text(
        json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )

    report = dict(
        pipeline_version=PIPELINE_VERSION,
        n_records=len(result.records),
        dropped=result.dropped,
        warnings=result.warnings,
        review=[dict(doc_id=r["doc_id"], reasons=r["review_reasons"]) for r in result.review_items()],
        diff={k: len(v) for k, v in result.diff.items()},
    )
    (out_dir / "ingest_report.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def print_summary(result: IngestResult, n_input: int, wrote: bool) -> None:
    counts = result.dropped_counts()
    print(f"[ingest] 入力: {n_input} 件")
    print(f"[ingest] 除外: 空 {counts['empty']} / 完全重複 {counts['exact_dup']} "
          f"/ 近重複 {counts['near_dup']}")
    for warning in result.warnings:
        print(f"[ingest] 警告: {warning}")
    review = result.review_items()
    print(f"[ingest] 要レビュー: {len(review)} 件")
    for record in review:
        print(f"[ingest]   {record['doc_id']}: {','.join(record['review_reasons'])}")
    destination = f" -> {OUT_LABEL}/docs.jsonl" if wrote else "（--dry-run のため書き出していません）"
    print(f"[ingest] 出力: {len(result.records)} 件{destination}")
    diff = result.diff
    print(f"[ingest] 差分: 追加 {len(diff['added'])} / 更新 {len(diff['changed'])} "
          f"/ 削除 {len(diff['removed'])} / 変更なし {len(diff['unchanged'])}")


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    raws = load_raw()
    result = run_ingest(raws, load_state(OUT_DIR / "state.json"))
    if not dry_run:
        write_output(result, OUT_DIR)
    print_summary(result, len(raws), wrote=not dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
