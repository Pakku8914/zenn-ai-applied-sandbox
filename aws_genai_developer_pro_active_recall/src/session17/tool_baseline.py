#!/usr/bin/env python3
"""セッション17: ツール呼び出しとマルチエージェント連携の可観測性。

    docker compose exec app python src/session17/tool_baseline.py

エージェントは「エラーを出さずに間違える」ことがあります。ツールを1つも呼ばずに
答えてしまう、同じツールを何度も呼ぶ、専門役ではなく人へ投げる——どれも例外は
出ないため、エラー率では検知できません。

見張るのは**呼び出しのパターン**です。平常時の分布（ベースライン）を1度だけ
確定させておき、そこからの**逸脱**を検知します。異常検知は「悪い値」を探すのでは
なく「普段と違う形」を探す仕組みです。

判定はすべて割り算と引き算です。CloudWatch の異常検知（Anomaly Detection）や
Contributor Insights を使うと同じことをマネージドで行えますが、
LocalStack Community には無いため、ここでは同じ判定を素の Python で書きます。
"""

from __future__ import annotations

TOOLS: tuple[str, ...] = ("search_docs", "lookup_ticket", "escalate")

# 平常時のベースライン（**仮定値**。実運用では平常な期間の集計をそのまま使う）。
# 割合で持つのが要点です。件数で持つと、利用が増えただけで全項目が逸脱します
BASELINE_SHARE: dict[str, float] = {
    "search_docs": 0.60,
    "lookup_ticket": 0.30,
    "escalate": 0.10,
}
BASELINE_CALLS_PER_REQUEST = 2.0

# 逸脱と見なす幅。割合は絶対差、回数は倍率で見る
SHARE_TOLERANCE = 0.10
CALLS_RATIO_MAX = 1.30

# 同じツールの連続呼び出しの上限（これを超えたらループを疑う）
REPEAT_MAX = 2

# 今日の観測（60件の依頼に対する呼び出し回数）
OBSERVED_CALLS: dict[str, int] = {
    "search_docs": 96,
    "lookup_ticket": 24,
    "escalate": 60,
}
OBSERVED_REQUESTS = 60

# 1件ぶんの軌跡（同じツールを続けて呼んでいる例）
OBSERVED_TRACE: tuple[str, ...] = (
    "search_docs", "search_docs", "search_docs", "escalate",
)


def shares(calls: dict[str, int]) -> dict[str, float]:
    """呼び出し回数を割合に直す。"""
    total = sum(calls.values())
    return {
        tool: round(calls.get(tool, 0) / total, 4) if total else 0.0
        for tool in TOOLS
    }


def calls_per_request(calls: dict[str, int], requests: int) -> float:
    """1件あたりの往復回数。**増えていれば、答えに近づけていない兆候。**"""
    return round(sum(calls.values()) / requests, 4) if requests else 0.0


def longest_repeat(trace: tuple[str, ...]) -> int:
    """同じツールが連続した最長の回数（ループの兆候）。"""
    best = 0
    run = 0
    previous: str | None = None
    for name in trace:
        run = run + 1 if name == previous else 1
        previous = name
        best = max(best, run)
    return best


def deviations(
    calls: dict[str, int] = OBSERVED_CALLS,
    *,
    requests: int = OBSERVED_REQUESTS,
    trace: tuple[str, ...] = OBSERVED_TRACE,
) -> dict:
    """ベースラインからの逸脱をまとめる。

    3種類を見ます。どれも「値の良し悪し」ではなく「普段との差」で判定します。

      1. ツールごとの割合の差（どの道具に寄ったか）
      2. 1件あたりの呼び出し回数の倍率（往復が増えていないか）
      3. 同じツールの連続回数（ループになっていないか）
    """
    observed_share = shares(calls)
    rows = []
    for tool in TOOLS:
        base = BASELINE_SHARE[tool]
        share = observed_share[tool]
        delta = round(share - base, 4)
        rows.append(
            {
                "tool": tool,
                "baseline": base,
                "observed": share,
                "delta": delta,
                "deviated": abs(delta) > SHARE_TOLERANCE,
            }
        )
    per_request = calls_per_request(calls, requests)
    ratio = round(per_request / BASELINE_CALLS_PER_REQUEST, 4)
    repeat = longest_repeat(trace)
    return {
        "rows": rows,
        "deviatedTools": [row["tool"] for row in rows if row["deviated"]],
        "callsPerRequest": per_request,
        "callsRatio": ratio,
        "callsDeviated": ratio > CALLS_RATIO_MAX,
        "longestRepeat": repeat,
        "repeatDeviated": repeat > REPEAT_MAX,
    }


def main() -> None:
    report = deviations()

    print("=== 1. ツール呼び出しの分布（平常時との差） ===")
    for row in report["rows"]:
        verdict = "逸脱" if row["deviated"] else "正常"
        print(
            f"  {row['tool']:<14} 平常 {row['baseline']} / 今日 {row['observed']}"
            f" / 差 {row['delta']} -> {verdict}"
        )
    print(f"  逸脱したツール: {report['deviatedTools']}")

    print()
    print("=== 2. 1件あたりの往復回数 ===")
    print(
        f"  平常 {BASELINE_CALLS_PER_REQUEST} / 今日 {report['callsPerRequest']}"
        f"（{report['callsRatio']}倍・上限 {CALLS_RATIO_MAX}倍）"
        f" -> {'逸脱' if report['callsDeviated'] else '正常'}"
    )

    print()
    print("=== 3. 同じツールの連続呼び出し（ループの兆候） ===")
    print(f"  軌跡: {' -> '.join(OBSERVED_TRACE)}")
    print(
        f"  最長連続 {report['longestRepeat']} 回（上限 {REPEAT_MAX} 回）"
        f" -> {'逸脱' if report['repeatDeviated'] else '正常'}"
    )

    print()
    print("=== 4. 読み方 ===")
    print("  検索の道具が減り、人への引き継ぎが3倍に増えています")
    print("  エージェントの不調ではなく、検索側の劣化を先に疑う形の逸脱です")
    print("  同じツールの連続は、停止条件（セッション7）が効く前の段階で見つけたい兆候です")


if __name__ == "__main__":
    main()
