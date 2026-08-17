#!/usr/bin/env python3
"""打ち手とコストを1つの表で語る。モデルを使わないので数秒で終わる。

数値はすべて `tools/` の決定的スクリプトの実測（2026-08-15 / aarch64 / CPU 2コア /
メモリ 5.8GB / Python 3.12.13）で、**測っていない欄には None を入れてある**。
None のところに「たぶんこれくらい」を書き込まないこと。それが表を殺す。

実行:  docker compose exec app python src/review03/budget_table.py
"""

from __future__ import annotations

# --- レイテンシの実測 -------------------------------------------------------
# 候補数 -> リランクの所要時間の中央値 ms（tools/bench_rerank.py）
MEASURED_RERANK_MS: dict[int, float] = {10: 405.0, 20: 709.0, 50: 1571.0, 100: 2710.0}
RERANK_LOAD_S = 15.5      # リランカのロード（常駐前提。1リクエストの予算には入れない）
QUERY_ENCODE_MS = 9.8     # クエリ1件の符号化の中央値（tools/bench_embed.py）
ANN_MS = 1.4              # 20,000件の総当たりの実測（tools/bench_hnsw.py）を上限として使う
STAGE1_MS = 20.0          # 1段目に引き当てる時間（セッション9と同じ置き方）

# --- 精度の実測 -------------------------------------------------------------
# 構成 -> (Recall@10, 基準線, 出典)。**基準線が違う値を足し引きしてはいけない**
MEASURED_RECALL: dict[str, tuple[float, str, str]] = {
    "bm25 / fixed": (0.763, "-", "S02"),
    "bm25(bigram) / fixed": (0.812, "bm25 0.763", "S05"),
    "bm25 + 索引側同義語展開": (0.873, "bm25 0.763", "S05"),
    "bm25 + クエリ側同義語展開": (0.889, "bm25 0.763", "Review01"),
    "dense / fixed": (0.783, "-", "S06"),
    "hybrid minmax(0.3:1.0)": (0.797, "-", "S08"),
    "dense → rerank(候補20)": (0.798, "dense 0.783", "S09"),
    "dense → rerank(候補50)": (0.818, "dense 0.783", "S09"),
}

# 打ち手 -> (効く失敗の層, 効くクエリ型, 構成名, 1リクエストの追加レイテンシ ms, 準備コスト)
MOVE_COST: list[tuple[str, str, str, str, float, str]] = [
    ("何もしない", "-", "-", "bm25 / fixed", 0.0, "-"),
    ("クエリ側の同義語展開", "到達不足", "abbrev", "bm25 + クエリ側同義語展開", 0.0,
     "辞書19語の作成と維持"),
    ("索引側の同義語展開", "到達不足", "abbrev", "bm25 + 索引側同義語展開", 0.0,
     "辞書19語＋索引の作り直し（展開されたチャンク166件）"),
    ("文字N-gramのトークナイザ", "到達不足", "全般", "bm25(bigram) / fixed", 0.0,
     "索引の作り直し（索引が太る）"),
    ("密ベクトル検索に替える", "到達不足", "abbrev / temporal", "dense / fixed",
     QUERY_ENCODE_MS + ANN_MS, "モデル取得 941MB・索引作成 38.21秒（673チャンク）"),
    ("スコア融合の重み調整", "両方", "abbrev", "hybrid minmax(0.3:1.0)",
     QUERY_ENCODE_MS + ANN_MS, "重みの決定と全条件の測り直し"),
    ("リランク（候補20）", "順位不足", "multi_condition", "dense → rerank(候補20)",
     QUERY_ENCODE_MS + ANN_MS + 709.0, f"リランカのロード {RERANK_LOAD_S}秒（常駐）"),
    ("リランク（候補50）", "順位不足", "multi_condition", "dense → rerank(候補50)",
     QUERY_ENCODE_MS + ANN_MS + 1571.0, f"リランカのロード {RERANK_LOAD_S}秒（常駐）"),
    ("リランク（候補100）", "順位不足", "multi_condition", "dense → rerank(候補100)",
     QUERY_ENCODE_MS + ANN_MS + 2710.0, f"リランカのロード {RERANK_LOAD_S}秒（常駐）"),
]


def per_item_ms(candidates: int) -> float:
    """候補1件あたりのリランク時間。候補を増やすほど安くなる（まとめ処理の効き）。"""
    return MEASURED_RERANK_MS[candidates] / candidates


def _bracket_by_time(target_ms: float) -> tuple[int, int]:
    """target_ms を挟む2つの測定点を返す。挟めなければ端の2点を返す。"""
    pts = sorted(MEASURED_RERANK_MS)
    for lo, hi in zip(pts, pts[1:]):
        if MEASURED_RERANK_MS[lo] <= target_ms <= MEASURED_RERANK_MS[hi]:
            return lo, hi
    return (pts[0], pts[1]) if target_ms < MEASURED_RERANK_MS[pts[0]] else (pts[-2], pts[-1])


def _bracket_by_count(candidates: int) -> tuple[int, int]:
    pts = sorted(MEASURED_RERANK_MS)
    for lo, hi in zip(pts, pts[1:]):
        if lo <= candidates <= hi:
            return lo, hi
    return (pts[0], pts[1]) if candidates < pts[0] else (pts[-2], pts[-1])


def _line(lo: int, hi: int) -> tuple[float, float]:
    """2つの測定点を通る直線（傾き, 切片）。予算の近くだけを当てる局所モデル。"""
    slope = (MEASURED_RERANK_MS[hi] - MEASURED_RERANK_MS[lo]) / (hi - lo)
    return slope, MEASURED_RERANK_MS[lo] - slope * lo


def rerank_ms(candidates: int) -> float:
    """候補数からリランクの所要時間を出す。測定点はその値をそのまま返す。"""
    if candidates in MEASURED_RERANK_MS:
        return MEASURED_RERANK_MS[candidates]
    slope, intercept = _line(*_bracket_by_count(candidates))
    return slope * candidates + intercept


def max_candidates(budget_ms: float, stage1_ms: float = STAGE1_MS) -> tuple[int, bool]:
    """レイテンシ予算から候補数の上限を逆算する。

    戻り値: (上限候補数, 測定点の内側か)。**内側でなければ外挿**なので、
    その数字は「測った」とは言えない。決定表にはその旨を書く。
    """
    target = budget_ms - stage1_ms
    lo, hi = _bracket_by_time(target)
    slope, intercept = _line(lo, hi)
    n = int((target - intercept) / slope)
    inside = MEASURED_RERANK_MS[lo] <= target <= MEASURED_RERANK_MS[hi]
    return max(n, 0), inside


def pipeline_ms(candidates: int) -> float:
    """1リクエストの内訳の合計（クエリ符号化 + 近似検索 + リランク）。"""
    return QUERY_ENCODE_MS + ANN_MS + rerank_ms(candidates)


def rerank_share(candidates: int) -> float:
    """レイテンシのうちリランク段が占める割合。"""
    return rerank_ms(candidates) / pipeline_ms(candidates)


def recall_evidence(candidates: int) -> tuple[str, float] | None:
    """その候補数で Recall@10 を測ってあるか。無ければ None（推定値を返さない）。"""
    name = f"dense → rerank(候補{candidates})"
    row = MEASURED_RECALL.get(name)
    return (name, row[0]) if row else None


def decision(budget_ms: float) -> dict:
    """予算から構成を決める。決まらないことも「決まらない」と返す。"""
    n, inside = max_candidates(budget_ms)
    evidence = recall_evidence(n)
    return {
        "budget_ms": budget_ms,
        "rerank_budget_ms": budget_ms - STAGE1_MS,
        "max_candidates": n,
        "inside_measured_range": inside,
        "recall_evidence": evidence,
        "verdict": (
            "リランクは入れられない（測定点 405ms より短い）" if n < 10 else
            f"候補{n}件までリランクできる。ただし Recall@10 は未測定なので、"
            "採用前にその候補数で測ること"
            if evidence is None else
            f"候補{n}件でリランクできる（Recall@10 {evidence[1]:.3f} を測定済み）"
        ),
    }


def print_table() -> None:
    print("[リランクのレイテンシ（tools/bench_rerank.py / 2026-08-15 / aarch64 / CPU 2コア）]")
    print(f"{'候補数':>6}{'中央値 ms':>12}{'1件あたり ms':>14}{'1リクエスト合計 ms':>20}"
          f"{'リランクの占有率':>18}")
    for n in sorted(MEASURED_RERANK_MS):
        print(f"{n:>6}{MEASURED_RERANK_MS[n]:>12.0f}{per_item_ms(n):>14.1f}"
              f"{pipeline_ms(n):>20.1f}{rerank_share(n):>18.3f}")
    print(f"  （1段目の内訳: クエリ符号化 {QUERY_ENCODE_MS} ms + 近似検索 {ANN_MS} ms。"
          f"リランカのロード {RERANK_LOAD_S} 秒は常駐前提で予算に入れない）")

    print("\n[打ち手とコスト]")
    print(f"{'打ち手':<26}{'効く層':<10}{'効く型':<20}{'Recall@10':>10}{'基準線':>14}"
          f"{'追加ms':>10}")
    for name, layer, qtype, config, ms, _prep in MOVE_COST:
        row = MEASURED_RECALL.get(config)
        recall = f"{row[0]:.3f}" if row else "未測定"
        base = row[1] if row else "-"
        print(f"{name:<26}{layer:<10}{qtype:<20}{recall:>10}{base:>14}{ms:>10.1f}")

    print("\n[予算からの逆算]")
    for budget in (300.0, 500.0, 1000.0, 3000.0):
        d = decision(budget)
        flag = "測定点の内側" if d["inside_measured_range"] else "外挿（測定点の外側）"
        print(f"  予算 {budget:>6.0f} ms -> 上限候補数 {d['max_candidates']:>3} 件 "
              f"[{flag}] : {d['verdict']}")


if __name__ == "__main__":
    print_table()
