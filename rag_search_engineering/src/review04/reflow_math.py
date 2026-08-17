#!/usr/bin/env python3
"""横断復習04：本番ログを評価に還流する算数（セッション17 × セッション2 × セッション12）。

  保存ポリシー -> 層化サンプリング -> 評価セットの重み -> 検知できる最小の悪化幅

同じ検索器でも、評価セットの型の混ぜ方を変えるだけで数字は 0.968 から 0.763 まで動く。
「良くなった」と言う前に、**どの重みで見た数字か**を必ず添える。

ログは読み込まない（セッション17で確定した件数を定数に写している）。

実行:  docker compose exec app python src/review04/reflow_math.py
"""

from __future__ import annotations

import hashlib
import re

# --- セッション17で確定した合成クエリログの実体 ---------------------------------
LOG_ROWS = 429
ROWS_WITH_RESULTS = 419          # 結果があった行（上位無クリック率の分母）
ZERO_HIT_ROWS = LOG_ROWS - ROWS_WITH_RESULTS   # 10 行
CLICK_RATE = 0.620               # 分母は 429 行
NO_CLICK_RATE = 0.365            # 分母は 419 行
REFORMULATION_RATE = 0.375       # 言い換え率（セッション付きの v2 サンプル）

# 本番の需要（クエリ型別の行数）
TRAFFIC_ROWS: dict[str, int] = {
    "natural": 345, "keyword": 30, "abbrev": 20,
    "multi_condition": 12, "temporal": 12, "unanswerable": 10,
}

# 型別 Recall@10（bm25(morph) / fixed(400/80)・2026-08-15 実測）
PER_TYPE_RECALL: dict[str, float] = {
    "natural": 0.968, "keyword": 0.967, "abbrev": 0.182,
    "multi_condition": 0.452, "temporal": 0.919,
}

# 評価セットの中身（型 -> 件数）。同じ検索器を、この4つの重みで見る
EVAL_SETS: dict[str, dict[str, int]] = {
    "最初の評価セット(66)": {"natural": 36, "keyword": 30},
    "比例配分で還流(69)": {"natural": 36, "keyword": 30, "abbrev": 1,
                          "multi_condition": 1, "temporal": 1},
    "最低件数を保証して還流(78)": {"natural": 36, "keyword": 30, "abbrev": 3,
                                  "multi_condition": 3, "temporal": 3, "unanswerable": 3},
    "型を均等に見る(120)": {"natural": 36, "keyword": 30, "abbrev": 20,
                          "multi_condition": 12, "temporal": 12, "unanswerable": 10},
    "本番の需要で重み付け(429)": dict(TRAFFIC_ROWS),
}

# 保存ポリシー：フィールドごとに keep / hash / mask / drop のどれかを必ず決める
STORAGE_POLICY: dict[str, str] = {
    "query_id": "keep", "text": "mask", "query_type": "keep", "n_results": "keep",
    "top_score": "keep", "clicked_rank": "keep", "latency_ms": "keep",
    "user_role": "keep", "user_dept": "keep", "filters": "keep",
    "retriever": "keep", "index_version": "keep", "answer_verdict": "keep",
    "session_id": "hash", "user_id": "hash",
    "raw_ip": "drop", "user_agent": "drop", "answer_text": "drop",
}

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"0\d{1,4}-\d{1,4}-\d{4}")
_EMPLOYEE_ID = re.compile(r"[A-Z]{2}-\d{4,6}")

DIRTY_QUERY = "tanaka@example.co.jp の立替金 03-1234-5678 EM-10432"


# --- 1. 取り込み口でのマスキング（冪等であること）-------------------------------
def mask_text(text: str) -> str:
    """PII を伏せ字にする。2回かけても結果が変わらない（冪等）ことが要件。"""
    text = _EMAIL.sub("<EMAIL>", text)
    text = _PHONE.sub("<PHONE>", text)
    return _EMPLOYEE_ID.sub("<EMPLOYEE_ID>", text)


def pii_hits(text: str) -> list[str]:
    return [name for name, pat in (("email", _EMAIL), ("phone", _PHONE),
                                   ("employee_id", _EMPLOYEE_ID)) if pat.search(text)]


def hash_value(value: str, salt: str) -> str:
    """同じ値は同じハッシュ、ソルトが変われば別のハッシュ（追跡はできるが復元できない）。"""
    return hashlib.sha256(f"{salt}:{value}".encode("utf-8")).hexdigest()[:16]


def dropped_fields() -> tuple[str, ...]:
    return tuple(sorted(f for f, action in STORAGE_POLICY.items() if action == "drop"))


# --- 2. 層化サンプリング ---------------------------------------------------------
def allocate_proportional(n: int, rows: dict[str, int]) -> dict[str, int]:
    """本番の需要に比例して配る。多数派の型ばかりが選ばれる。"""
    total = sum(rows.values())
    exact = {t: n * c / total for t, c in rows.items()}
    out = {t: int(v) for t, v in exact.items()}
    rest = n - sum(out.values())
    order = sorted(rows, key=lambda t: (-(exact[t] - int(exact[t])), -rows[t], t))
    for t in order[:rest]:
        out[t] += 1
    return out


def allocate_min_then_even(n: int, rows: dict[str, int], minimum: int = 2) -> dict[str, int]:
    """まず全型に最低件数を配り、残りを均等に配る（余りは需要の多い型へ）。

    少数派の型（略語・複数条件）を評価セットに必ず入れるための配り方。
    """
    types = list(rows)
    if n < minimum * len(types):
        raise ValueError(f"n={n} では全型に最低 {minimum} 件を配れません")
    out = {t: minimum for t in types}
    rest = n - minimum * len(types)
    each, extra = divmod(rest, len(types))
    for t in types:
        out[t] += each
    for t in sorted(types, key=lambda t: (-rows[t], t))[:extra]:
        out[t] += 1
    return out


# --- 3. 評価セットの重み ---------------------------------------------------------
def weighted_recall(counts: dict[str, int]) -> float:
    """型別 Recall@10 を件数で重み付けする。

    回答不能クエリは Recall を定義できないので分母から外す（混ぜると平均が歪む）。
    """
    pairs = [(c, PER_TYPE_RECALL[t]) for t, c in counts.items() if t in PER_TYPE_RECALL]
    total = sum(c for c, _ in pairs)
    if total == 0:
        raise ValueError("回答可能な型が1つもありません")
    return sum(c * r for c, r in pairs) / total


def answerable_size(counts: dict[str, int]) -> int:
    return sum(c for t, c in counts.items() if t in PER_TYPE_RECALL)


# --- 4. 検知できる最小の悪化幅 ---------------------------------------------------
def binom_tail_ge(n: int, k: int, p: float) -> float:
    """二項分布の上側確率 P(X >= k)。漸化式で回すのでオーバーフローしない。"""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    pmf = (1.0 - p) ** n
    total = 0.0
    for i in range(n + 1):
        if i >= k:
            total += pmf
        if i < n:
            pmf = pmf * (n - i) / (i + 1) * p / (1.0 - p)
    return total


def min_detectable_rate(n: int, p0: float, alpha: float = 0.01) -> float:
    """n 件の窓で「偶然ではない」と言える最小の悪化率。"""
    for k in range(n + 1):
        if binom_tail_ge(n, k, p0) <= alpha:
            return k / n
    return 1.0


def zero_hit_rate() -> float:
    return ZERO_HIT_ROWS / LOG_ROWS


def main() -> None:
    print("=== 1. 取り込み口でのマスキング ===")
    masked = mask_text(DIRTY_QUERY)
    print(f"  生   : {DIRTY_QUERY}")
    print(f"  マスク: {masked}")
    print(f"  当たった PII: {pii_hits(DIRTY_QUERY)} -> マスク後: {pii_hits(masked)}")
    print(f"  冪等（2回かけても同じ）: {mask_text(masked) == masked}")
    print(f"  落とすフィールド: {dropped_fields()}")

    print("\n=== 2. 失敗シグナル（分母を必ず添える）===")
    print(f"  ゼロヒット率     : {zero_hit_rate() * 100:.1f}%（{ZERO_HIT_ROWS} / {LOG_ROWS} 行）")
    print(f"  クリック率       : {CLICK_RATE * 100:.1f}%（分母 {LOG_ROWS} 行）")
    print(f"  上位無クリック率 : {NO_CLICK_RATE * 100:.1f}%（分母 {ROWS_WITH_RESULTS} 行）")
    print(f"  言い換え率       : {REFORMULATION_RATE:.3f}")

    print("\n=== 3. 20件を層化サンプリングで選ぶ ===")
    prop = allocate_proportional(20, TRAFFIC_ROWS)
    mte = allocate_min_then_even(20, TRAFFIC_ROWS)
    print(f"  比例配分       : {prop}（合計 {sum(prop.values())}）")
    print(f"  最低2件を保証  : {mte}（合計 {sum(mte.values())}）")
    print(f"  比例配分だと略語は {prop['abbrev']} 件しか入らない"
          f"（本番の需要が {TRAFFIC_ROWS['abbrev']} / {LOG_ROWS} 行しかないため）")

    print("\n=== 4. 同じ検索器が、重みを変えると別の数字に見える ===")
    for label, counts in EVAL_SETS.items():
        print(f"  {label:<26} Recall@10 = {weighted_recall(counts):.3f}"
              f"（回答可能 {answerable_size(counts)} 件）")

    print("\n=== 5. 窓の大きさと、検知できる最小のゼロヒット率（α=0.01）===")
    p0 = zero_hit_rate()
    for n in (20, 50, 100, 500, 1000):
        print(f"  {n:>5} 件の窓 : {min_detectable_rate(n, p0) * 100:.1f}% 以上でないと"
              "有意にならない")


if __name__ == "__main__":
    main()
