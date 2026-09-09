#!/usr/bin/env python3
"""セッション1の検証。

「資料あり／なし」で根拠提示率が変わることと、PoC の判定表の数値が
決定的であることを確認します。**期待値と一致しなければ非0で終了します。**

    docker compose exec app python src/session01/verify.py
"""

from __future__ import annotations

import json
import sys
import urllib.request

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session01")

from awskit import clients  # noqa: E402
from bedrock_mock import catalog  # noqa: E402

import poc_probe  # noqa: E402

FAILURES: list[str] = []

# 条件B（資料あり）の期待値: (入力トークン, 出力トークン, レイテンシ ms)
EXPECTED_GROUNDED = [(90, 66, 86), (78, 51, 71), (85, 58, 78)]

# 各質問の答えに必ず現れる、資料由来の数値表現
EXPECTED_FACTS = ["20日", "週3日", "15000円"]


def check(label: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        FAILURES.append(label)


def mock_post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{clients.mock_base_url()}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read())


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    # 前章・前セッションの障害注入設定が残っていると落ちるため必ずリセットする
    mock_post("/_mock/reset", {})

    runtime = clients.bedrock_runtime()

    # ------------------------------------------------------------------
    section("1. 合格条件が先に定義されている")
    check(
        "根拠提示率の合格条件がある",
        poc_probe.CRITERIA["grounded_rate_min"] == 0.90,
        poc_probe.CRITERIA,
    )
    check(
        "レイテンシとコストの合格条件がある",
        poc_probe.CRITERIA["avg_latency_ms_max"] > 0
        and poc_probe.CRITERIA["usd_per_1k_max"] > 0,
        poc_probe.CRITERIA,
    )
    check("質問は3件", len(poc_probe.QUESTIONS) == 3, len(poc_probe.QUESTIONS))
    check(
        "使うモデル ID はカタログにある",
        poc_probe.MODEL_ID in catalog.MODELS,
        poc_probe.MODEL_ID,
    )

    # ------------------------------------------------------------------
    section("2. 条件A: プロンプトのみ（資料を渡さない）")
    plain = poc_probe.run(runtime, with_source=False)
    check("3件すべて回答が返る", len(plain) == 3, len(plain))
    check(
        "1件も根拠を提示できない",
        all(not r["grounded"] for r in plain),
        [r["grounded"] for r in plain],
    )
    check(
        "資料を引用する言い回しが出ない",
        all("提供された資料" not in r["answer"] for r in plain),
        [r["answer"][:30] for r in plain],
    )
    check(
        "打ち切られてはいない（品質不足は長さの問題ではない）",
        all(r["stopReason"] == "end_turn" for r in plain),
        [r["stopReason"] for r in plain],
    )
    sa = poc_probe.summarize(plain)
    check("根拠提示率は 0.0", sa["groundedRate"] == 0.0, sa["groundedRate"])
    ok_a, why_a = poc_probe.judge(sa)
    check("判定は NO-GO", ok_a is False, (ok_a, why_a))
    check(
        "NO-GO の理由は必須条件の未達",
        why_a == "必須条件を満たさないため、トークンとレイテンシの計測は行いません",
        why_a,
    )

    # ------------------------------------------------------------------
    section("3. 条件B: 社内資料を1件渡す（グラウンディングあり）")
    grounded = poc_probe.run(runtime, with_source=True)
    check(
        "3件すべて根拠を提示する",
        all(r["grounded"] for r in grounded),
        [r["grounded"] for r in grounded],
    )
    for i, (fact, r) in enumerate(zip(EXPECTED_FACTS, grounded), start=1):
        check(f"Q{i} の回答に資料の値 {fact} が含まれる", fact in r["answer"], r["answer"])
    for i, (expected, r) in enumerate(zip(EXPECTED_GROUNDED, grounded), start=1):
        actual = (r["inputTokens"], r["outputTokens"], r["latencyMs"])
        check(f"Q{i} の計測値が決定的（入力/出力/ms）", actual == expected, actual)
    check(
        "レイテンシは 20 + 出力トークン",
        all(r["latencyMs"] == 20 + r["outputTokens"] for r in grounded),
        [(r["latencyMs"], r["outputTokens"]) for r in grounded],
    )

    sb = poc_probe.summarize(grounded)
    check("根拠提示率は 1.0", sb["groundedRate"] == 1.0, sb["groundedRate"])
    check(
        "平均出力トークンの表示が 58.3",
        f"{sb['avgOutputTokens']:.1f}" == "58.3",
        sb["avgOutputTokens"],
    )
    check(
        "平均レイテンシの表示が 78.3",
        f"{sb['avgLatencyMs']:.1f}" == "78.3",
        sb["avgLatencyMs"],
    )
    check(
        "3件の推定コストの表示が 0.000057 USD",
        f"{sb['usdTotal']:.6f}" == "0.000057",
        sb["usdTotal"],
    )
    check(
        "1,000件換算の表示が 0.019 USD",
        f"{sb['usdPer1k']:.3f}" == "0.019",
        sb["usdPer1k"],
    )
    ok_b, why_b = poc_probe.judge(sb)
    check("判定は GO", ok_b is True, (ok_b, why_b))

    # ------------------------------------------------------------------
    section("4. 資料あり／なしの差が「構成の差」として説明できる")
    check(
        "資料ありのほうが入力トークンは増える",
        sum(r["inputTokens"] for r in grounded) > sum(r["inputTokens"] for r in plain),
        (
            sum(r["inputTokens"] for r in grounded),
            sum(r["inputTokens"] for r in plain),
        ),
    )
    check(
        "根拠提示率は 0% から 100% へ改善する",
        sa["groundedRate"] == 0.0 and sb["groundedRate"] == 1.0,
        (sa["groundedRate"], sb["groundedRate"]),
    )
    check(
        "1,000件換算でも 1 USD に届かない（PoC のコスト規模）",
        sb["usdPer1k"] < 1.0,
        sb["usdPer1k"],
    )

    print()
    if FAILURES:
        print(f"NG: {len(FAILURES)} 件の検証に失敗しました -> {FAILURES}")
        return 1
    print("セッション1の検証に成功しました（課金は一切発生していません）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
