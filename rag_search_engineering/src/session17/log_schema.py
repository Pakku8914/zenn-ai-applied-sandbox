#!/usr/bin/env python3
"""検索ログのスキーマ設計 ― 測りたい指標から必要なフィールドを逆算する。

  python src/session17/log_schema.py

「とりあえず全部残す」でも「クエリ本文だけ残す」でもなく、
運用で見る指標を先に決め、その指標が計算できる最小のフィールドを決める。
フィールドごとに保存ポリシー（keep / hash / mask / drop）を付けるのが本体。
"""

from __future__ import annotations

from dataclasses import dataclass

# 保存ポリシー（4文字にそろえてある）
KEEP, HASH, MASK, DROP = "keep", "hash", "mask", "drop"


@dataclass(frozen=True)
class Field:
    """ログの1フィールドと、その保存ポリシー。"""

    name: str
    policy: str
    why: str


# 本書が推奨する検索ログのスキーマ（v2）。
# corpus/query_log.jsonl（v1）はこの部分集合しか持っていない。
SCHEMA: tuple[Field, ...] = (
    Field("ts", KEEP, "いつのクエリか。窓を切って前後を比べるための軸"),
    Field("request_id", KEEP, "1回の検索を一意に指す。障害調査で他のログと突き合わせる"),
    Field("session_id", HASH, "同一セッションの言い換えを追う。個人には戻さない"),
    Field("user_id", HASH, "同じ人かどうかだけ分かればよい。日次ソルトで戻せなくする"),
    Field("user_role", KEEP, "権限コンテキスト。権限で結果が変わる以上、これが無いと再現できない"),
    Field("user_dept", KEEP, "部署フィルタの結果を再現する"),
    Field("query_text", MASK, "失敗クラスタを読むのに要る。PII をマスクしてから残す"),
    Field("query_type", KEEP, "型別に成績を分ける（keyword / natural / abbrev / ...）"),
    Field("retriever", KEEP, "どの構成で出た結果か（bm25 / dense / hybrid / rerank）"),
    Field("index_version", KEEP, "どの索引で出た結果か。エイリアス切り替えと対応させる"),
    Field("filters", KEEP, "権限・鮮度のフィルタ条件。ゼロヒットの原因切り分けに要る"),
    Field("n_results", KEEP, "ゼロヒット率の分子になる"),
    Field("top_score", KEEP, "低いスコアのまま返した割合を見る"),
    Field("result_doc_ids", KEEP, "何を返したか。判定データ（qrels）の候補に変換できる"),
    Field("latency_ms", KEEP, "レイテンシの SLO を見る"),
    Field("clicked_rank", KEEP, "上位無クリック率を計算する"),
    Field("clicked_doc_id", KEEP, "還流のときに適合候補として使う"),
    Field("answer_verdict", KEEP, "ok / abstained / low_evidence / unparsable / no_citation / invalid_citation"),
    Field("raw_ip", DROP, "検索の改善に使わない。持てば漏洩面積が増えるだけ"),
    Field("user_agent", DROP, "同上。端末別の分析が要るなら別系統で短期保持する"),
    Field("answer_text", DROP, "生成文はログの中で最も危ない。必要なら短期・限定アクセスの別系統へ"),
)

# corpus/query_log.jsonl が実際に持っているフィールド（v1・9個）
V1_FIELDS: tuple[str, ...] = (
    "ts", "query_id", "text", "query_type", "n_results",
    "top_score", "latency_ms", "clicked_rank", "user_role",
)

# v1 と v2 で名前が違うもの（名前の不一致そのものが引き継ぎコストになる）
V1_TO_V2: dict[str, str] = {"text": "query_text"}

# 指標 -> その指標を計算するのに要るフィールド
METRIC_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "ゼロヒット率": ("n_results",),
    "上位無クリック率": ("n_results", "clicked_rank"),
    "型別の成績": ("query_type",),
    "レイテンシ p95": ("latency_ms",),
    "言い換え率": ("session_id", "ts", "query_text"),
    "権限起因のゼロヒット": ("n_results", "filters", "user_role"),
    "結果の再現": ("retriever", "index_version", "filters"),
    "回答判定の内訳": ("answer_verdict",),
}


def stored_fields() -> tuple[str, ...]:
    """保存するフィールド（drop 以外）。"""
    return tuple(f.name for f in SCHEMA if f.policy != DROP)


def dropped_fields() -> tuple[str, ...]:
    """保存しないフィールド。"""
    return tuple(f.name for f in SCHEMA if f.policy == DROP)


def fields_by_policy(policy: str) -> tuple[str, ...]:
    return tuple(f.name for f in SCHEMA if f.policy == policy)


def policy_of(name: str) -> str:
    for f in SCHEMA:
        if f.name == name:
            return f.policy
    raise KeyError(f"スキーマに無いフィールドです: {name}")


def normalize_names(names) -> set[str]:
    """v1 の名前を v2 の名前に寄せる（text -> query_text）。"""
    return {V1_TO_V2.get(n, n) for n in names}


def unmeasurable(available) -> dict[str, list[str]]:
    """手持ちのフィールドでは計算できない指標と、足りないフィールドを返す。"""
    have = normalize_names(available)
    out: dict[str, list[str]] = {}
    for metric, needs in METRIC_REQUIREMENTS.items():
        missing = [n for n in needs if n not in have]
        if missing:
            out[metric] = missing
    return out


def main() -> None:
    print("=== 保存ポリシー ===")
    for f in SCHEMA:
        print(f"[{f.policy}] {f.name}: {f.why}")
    print(f"\n保存する: {len(stored_fields())} / 落とす: {len(dropped_fields())}")

    print("\n=== いまのログ（v1・9フィールド）では計算できない指標 ===")
    missing = unmeasurable(V1_FIELDS)
    for metric, fields in missing.items():
        print(f"{metric} -> 足りない: {', '.join(fields)}")
    print(f"計算できない指標: {len(missing)} / {len(METRIC_REQUIREMENTS)}")


if __name__ == "__main__":
    main()
