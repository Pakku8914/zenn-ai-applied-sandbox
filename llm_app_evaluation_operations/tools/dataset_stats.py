"""同梱データセットの主要な統計量を出力する。

    python tools/dataset_stats.py

本文・練習問題・解答に載せる数値は、すべてこのスクリプトの出力と一致していなければ
ならない。章を書くときも、読者が答え合わせをするときも、ここが基準になる。
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATASETS = BASE_DIR / "datasets"

# 1M トークンあたりの単価（USD）。2026-08 時点の Claude API 標準料金。
PRICING = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
CACHE_WRITE_MULTIPLIER = 1.25  # 5 分 TTL のキャッシュ書き込み
CACHE_READ_MULTIPLIER = 0.10   # キャッシュ読み出し


def load(name: str) -> list[dict]:
    rows = []
    for line in (DATASETS / name).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            rows.append(json.loads(stripped))
    return rows


def section(title: str) -> None:
    print(f"\n{'=' * 68}\n{title}\n{'=' * 68}")


def percentile(values: list[float], q: float) -> float:
    """最近傍順位法によるパーセンタイル（実装が 1 行で説明でき、再現しやすい）。"""
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(q / 100 * len(ordered) + 0.5) - 1))
    return ordered[index]


def cohens_kappa(labels_x: dict[str, int], labels_y: dict[str, int]) -> tuple[float, float]:
    """単純一致率と Cohen's κ を返す。"""
    ids = sorted(labels_x)
    agree = sum(1 for i in ids if labels_x[i] == labels_y[i])
    po = agree / len(ids)

    pe = 0.0
    for value in (0, 1):
        px = sum(1 for i in ids if labels_x[i] == value) / len(ids)
        py = sum(1 for i in ids if labels_y[i] == value) / len(ids)
        pe += px * py

    return po, (po - pe) / (1 - pe)


def spearman(xs: list[float], ys: list[float]) -> float:
    """Spearman の順位相関係数（同順位は平均順位で処理する）。"""
    def ranks(values: list[float]) -> list[float]:
        ordered = sorted(range(len(values)), key=lambda i: values[i])
        result = [0.0] * len(values)
        position = 0
        while position < len(ordered):
            end = position
            while end + 1 < len(ordered) and values[ordered[end + 1]] == values[ordered[position]]:
                end += 1
            average = (position + end) / 2 + 1
            for k in range(position, end + 1):
                result[ordered[k]] = average
            position = end + 1
        return result

    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else 0.0


def row_cost(row: dict) -> float:
    price_in, price_out = PRICING[row["model"]]
    billable = (
        row["input_tokens"]
        + row.get("cache_creation_input_tokens", 0) * CACHE_WRITE_MULTIPLIER
        + row.get("cache_read_input_tokens", 0) * CACHE_READ_MULTIPLIER
    )
    return (billable * price_in + row["output_tokens"] * price_out) / 1_000_000


# ---------------------------------------------------------------------------

def stats_raw_logs() -> None:
    section("Session 3: raw_logs.jsonl（本番ログ 60 行）")
    rows = load("raw_logs.jsonl")
    counts = Counter(row["question"] for row in rows)

    print(f"総行数: {len(rows)} / ユニークな質問: {len(counts)}")
    print(f"PII を含む行: {sum(1 for r in rows if r['contains_pii'])} 件")
    print("\n出現頻度 上位5件:")
    for question, count in counts.most_common(5):
        print(f"  {count:2d} 回  {question[:38]}")
    singles = [q for q, c in counts.items() if c == 1]
    print(f"\n1 回しか出現しない質問: {len(singles)} 件"
          f"（= 頻度順に上位を取るだけでは 1 件も拾えない層）")


def stats_annotation() -> None:
    section("Session 4: アノテーションと一致率")
    items = {row["id"]: row for row in load("annotation_set.jsonl")}
    a = {row["id"]: row["label"] for row in load("labels_a.jsonl")}
    b = {row["id"]: row["label"] for row in load("labels_b.jsonl")}
    a2 = {row["id"]: row["label"] for row in load("labels_a2.jsonl")}

    po1, k1 = cohens_kappa(a, b)
    po2, k2 = cohens_kappa(a2, b)
    print(f"ガイドライン修正前  単純一致率 {po1:.4f} ({round(po1 * 15)}/15)  Cohen's κ = {k1:.4f}")
    print(f"ガイドライン修正後  単純一致率 {po2:.4f} ({round(po2 * 15)}/15)  Cohen's κ = {k2:.4f}")

    by_tag: dict[str, list[int]] = defaultdict(list)
    for case_id in a:
        by_tag[items[case_id]["tags"][0]].append(1 if a[case_id] != b[case_id] else 0)
    print("\nタグ別の不一致件数（修正前）:")
    for tag, flags in sorted(by_tag.items()):
        print(f"  {tag}: {sum(flags)} / {len(flags)} 件が不一致")


def stats_judge_bias() -> None:
    section("Session 7: judge のバイアスと妥当性")
    pairs = load("judge_pairs.jsonl")
    flips = sum(1 for row in pairs if row["flips_on_swap"])
    print(f"位置バイアス: 順序を入れ替えると判定が変わったペア {flips} / {len(pairs)} "
          f"= 不一致率 {flips / len(pairs):.1%}")

    verb = load("verbosity_pairs.jsonl")
    gaps = [row["score_long"] - row["score_short"] for row in verb]
    print(f"冗長性バイアス: 長文 − 短文 の平均点差 = +{sum(gaps) / len(gaps):.3f} 点"
          f"（{len(gaps)} 組中 {sum(1 for g in gaps if g > 0)} 組で長文が高評価）")

    items = {row["id"]: row for row in load("annotation_set.jsonl")}
    human = {row["id"]: row["label"] for row in load("labels_b.jsonl")}
    judge = {row["id"]: row["score"] for row in load("judge_scores.jsonl")}
    ids = sorted(items)

    overall = spearman([human[i] for i in ids], [judge[i] for i in ids])
    print(f"\n人手ラベル × judge スコアの Spearman 相関（全 15 件）: {overall:.4f}")

    by_tag: dict[str, list[str]] = defaultdict(list)
    for case_id in ids:
        by_tag[items[case_id]["tags"][0]].append(case_id)
    # judge を「4 点以上なら合格」で二値化し、人手ラベルと同じ土俵に載せる。
    # ここが Session 4 と Session 7 をつなぐ結び目になる。
    binarized = {case_id: (1 if judge[case_id] >= 4 else 0) for case_id in ids}
    print("\njudge を 4 点以上で二値化して人手ラベルと比べる:")
    for name in ("labels_a.jsonl", "labels_b.jsonl"):
        human_labels = {row["id"]: row["label"] for row in load(name)}
        po, kappa = cohens_kappa(binarized, human_labels)
        print(f"  judge(>=4) × {name[:-6]:9}: 一致 {round(po * len(ids))}/{len(ids)}"
              f" = {po:.4f}  Cohen's κ = {kappa:.4f}")
    mismatch = [i for i in ids if binarized[i] != human[i]]
    print(f"  labels_b との不一致: {mismatch}")
    print("  → judge はアノテータ A を完全に再現している（κ = 1.0）。"
          "A は Session 4 でガイドライン修正が必要だった側で、\n"
          "    B と食い違うのは境界タグの 4 件だけ。judge は誰かの盲点を継承する")

    print("\nタグ別:")
    for tag, tag_ids in sorted(by_tag.items()):
        human_values = [human[i] for i in tag_ids]
        judge_values = [judge[i] for i in tag_ids]
        # 分散が無い（全員同じラベル）タグでは相関を定義できない。0 と表示すると
        # 「相関が無い」と誤読されるので、測れないことを明示する
        if len(set(human_values)) < 2 or len(set(judge_values)) < 2:
            print(f"  {tag}（{len(tag_ids)}件）: 判定不能（ラベルに分散が無く相関を定義できない）")
            continue
        rho = spearman(human_values, judge_values)
        verdict = "judge に任せてよい" if rho >= 0.5 else "人手に回すべき"
        print(f"  {tag}（{len(tag_ids)}件）: ρ = {rho:+.4f}  → {verdict}")


def stats_usage() -> None:
    section("Session 12: usage_30d.jsonl（コスト分析）")
    rows = load("usage_30d.jsonl")
    total = sum(row_cost(row) for row in rows)
    print(f"総行数: {len(rows)}  30 日間の総コスト: ${total:.2f}\n")

    print(f"{'機能':<11}{'モデル':<19}{'件数':>6}{'コスト':>10}{'占有率':>8}{'ヒット率':>9}")
    print("-" * 68)
    for feature in ("summarize", "faq", "classify", "escalate"):
        subset = [row for row in rows if row["feature"] == feature]
        cost = sum(row_cost(row) for row in subset)
        hits = sum(1 for row in subset if row["cache_read_input_tokens"] > 0)
        print(f"{feature:<11}{subset[0]['model']:<19}{len(subset):>6}"
              f"{'$' + format(cost, '.2f'):>10}{cost / total:>7.1%}{hits / len(subset):>9.1%}")

    print("\nキャッシュヒット率 0% の機能とその原因:")
    print("  summarize : プロンプト先頭にタイムスタンプ → プレフィックスが毎回変わり書き込みだけ発生")
    print("              （キャッシュ書き込みは入力単価の 1.25 倍。入れる前より高い）")
    print("  escalate  : プレフィックスが 1,100 トークン → haiku 4.5 の最小キャッシュ長 4,096 に未達")
    print("              （エラーは出ない。cache_creation も cache_read も 0 のまま）")

    summarize = [row for row in rows if row["feature"] == "summarize"]
    fixed = sum(
        (row["input_tokens"] * 5.00
         + row["cache_creation_input_tokens"] * 5.00 * CACHE_READ_MULTIPLIER
         + row["output_tokens"] * 25.00) / 1_000_000
        for row in summarize
    )
    current = sum(row_cost(row) for row in summarize)
    print(f"\n打ち手1（summarize のキャッシュ修正）: ${current:.2f} → ${fixed:.2f} "
          f"= ${current - fixed:.2f} 削減")

    classify = [row for row in rows if row["feature"] == "classify"]
    haiku = sum(
        ((row["input_tokens"] + row["cache_read_input_tokens"] * CACHE_READ_MULTIPLIER
          + row["cache_creation_input_tokens"] * CACHE_WRITE_MULTIPLIER) * 1.00
         + row["output_tokens"] * 5.00) / 1_000_000
        for row in classify
    )
    now = sum(row_cost(row) for row in classify)
    print(f"打ち手2（classify を opus → haiku）: ${now:.2f} → ${haiku:.2f} "
          f"= ${now - haiku:.2f} 削減（※品質検証が前提）")


def stats_latency() -> None:
    section("Session 13: latency_7d.jsonl（レイテンシ分析）")
    rows = load("latency_7d.jsonl")
    print(f"総行数: {len(rows)}\n")

    print(f"{'エンドポイント':<14}{'件数':>6}{'p50':>9}{'p95':>9}{'p99':>9}{'TTFT p95':>11}")
    print("-" * 62)
    for endpoint in ("faq", "summarize", "classify"):
        subset = [row for row in rows if row["endpoint"] == endpoint]
        totals = [row["total_ms"] for row in subset]
        ttfts = [row["ttft_ms"] for row in subset]
        print(f"{endpoint:<14}{len(subset):>6}{percentile(totals, 50):>8.0f}ms"
              f"{percentile(totals, 95):>8.0f}ms{percentile(totals, 99):>8.0f}ms"
              f"{percentile(ttfts, 95):>10.0f}ms")

    all_totals = [row["total_ms"] for row in rows]
    print(f"\n全体: p50 {percentile(all_totals, 50):.0f}ms / "
          f"p95 {percentile(all_totals, 95):.0f}ms / p99 {percentile(all_totals, 99):.0f}ms / "
          f"平均 {sum(all_totals) / len(all_totals):.0f}ms")
    print("→ 平均は p95 より小さい。平均だけを SLO にすると、遅い 5% が見えなくなる。")

    print("\nタイムアウト設定のトレードオフ:")
    print(f"{'上限':>8}{'失敗率':>10}{'成功分の p95':>15}")
    print("-" * 34)
    for limit in (5000, 15000, 30000):
        failed = [row for row in rows if row["total_ms"] > limit]
        ok = [row["total_ms"] for row in rows if row["total_ms"] <= limit]
        print(f"{limit:>7}ms{len(failed) / len(rows):>9.2%}"
              f"{percentile(ok, 95):>13.0f}ms")


def stats_prod() -> None:
    section("Session 15: prod_logs_14d.jsonl（オンライン品質監視）")
    rows = load("prod_logs_14d.jsonl")
    print(f"総行数: {len(rows)}\n")

    by_day: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_day[row["ts"][:10]].append(row)

    # 「合格率」は評価データセットに対する指標なので、本番ログ側は ok 率と呼び分ける
    print(f"{'日付':<13}{'件数':>6}{'拒否率':>9}{'ok率':>9}")
    print("-" * 37)
    first_degraded = None
    for day in sorted(by_day):
        subset = by_day[day]
        refusals = sum(1 for r in subset if r["outcome"] == "model_refusal")
        ok = sum(1 for r in subset if r["outcome"] == "ok")
        degraded = refusals / len(subset) > 0.08
        if degraded and first_degraded is None:
            first_degraded = day
        marker = "  ← 劣化開始" if day == first_degraded else ""
        print(f"{day:<13}{len(subset):>6}{refusals / len(subset):>8.1%}"
              f"{ok / len(subset):>8.1%}{marker}")

    print("\n失敗の内訳（全期間）:")
    for outcome, count in Counter(row["outcome"] for row in rows).most_common():
        print(f"  {outcome:<20}{count:>6} 件 ({count / len(rows):>5.1%})")

    print("\nタグ別の judge 平均点（サンプリング分のみ）:")
    scored = [row for row in rows if "judge_score" in row]
    print(f"  サンプリング件数: {len(scored)} / {len(rows)} = {len(scored) / len(rows):.1%}")
    for tag in ("事実", "手順", "境界", "拒否", "PII"):
        before = [r["judge_score"] for r in scored if r["tag"] == tag and r["ts"][:10] < "2026-07-22"]
        after = [r["judge_score"] for r in scored if r["tag"] == tag and r["ts"][:10] >= "2026-07-22"]
        if before and after:
            delta = sum(after) / len(after) - sum(before) / len(before)
            print(f"  {tag}: 前 {sum(before) / len(before):.2f} → 後 {sum(after) / len(after):.2f} "
                  f"（{delta:+.2f}）")


def stats_incidents() -> None:
    section("Session 14 / 16: incident_logs.jsonl（障害シナリオ）")
    rows = load("incident_logs.jsonl")
    for scenario in ("refusal_spike", "cost_spike", "data_leak"):
        subset = [row for row in rows if row["scenario"] == scenario]
        traces = len({row["trace_id"] for row in subset})
        print(f"\n[{scenario}] {len(subset)} イベント / {traces} トレース")

        if scenario == "refusal_spike":
            for version in ("v6", "v7"):
                calls = [r for r in subset if r["name"] == "llm_call" and r["prompt_version"] == version]
                refused = sum(1 for r in calls if r["stop_reason"] == "refusal")
                print(f"  prompt_version={version}: {len(calls)} 件中 拒否 {refused} 件"
                      f" ({refused / len(calls):.0%})")
            print("  → 原因はプロンプト v7 のデプロイ。ロールバック対象が 1 つに絞れる")

        if scenario == "cost_spike":
            for version in ("2026.07.25", "2026.07.26"):
                calls = [r for r in subset if r["name"] == "llm_call" and r["code_version"] == version]
                avg = sum(r["input_tokens"] for r in calls) / len(calls)
                print(f"  code_version={version}: 平均入力トークン {avg:,.0f}")
            print("  → 履歴の刈り込みが外れて入力が約 9 倍。キャッシュ読み出しも 0 に落ちている")

        if scenario == "data_leak":
            leaked = sum(1 for r in subset if r.get("guardrail_pii") == "detected")
            keys = {r["context_cache_key"] for r in subset}
            print(f"  PII 検出: {leaked} / {len(subset)} 件、キャッシュキーの種類: {keys}")
            print("  → 全ユーザーが同じキャッシュキーを共有している。ユーザーID が入っていない")


def main() -> None:
    stats_raw_logs()
    stats_annotation()
    stats_judge_bias()
    stats_usage()
    stats_latency()
    stats_prod()
    stats_incidents()
    print()


if __name__ == "__main__":
    main()
