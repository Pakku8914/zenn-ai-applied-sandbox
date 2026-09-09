#!/usr/bin/env python3
"""セッション18: 品質ゲート（しきい値を割ったら非0で終了する）。

    docker compose exec app python src/session18/gate.py                    # ベースライン
    docker compose exec app python src/session18/gate.py --profile target   # 目標（いまは赤）

CI に置けるのは「人が読んで判断する表」ではなく、**終了コードで答えるプログラム**です。
ゲートは2本持ちます。役割が違うので、しきい値も運用も分けます。

    baseline  いまの姿を守る。割ったら **CI を落とす**（回帰の検知）
    target    目指す姿。いまは赤でよい。落とさずダッシュボードに出す（改善の的）

ベースラインを「目標値」で置くと、初日から赤いゲートができ、赤は無視されるようになります。
**ゲートは「良くする」ためではなく「悪くしない」ために置きます。**

環境で値が変わる指標（レイテンシ）は、同じゲートに厳しく入れません。緩い上限で持ち、
実測値は表示しません（測るたびに変わる数字を本文や合否条件に固定できないため）。
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/workspace")
for _dir in ("session04", "session05", "session06", "session14", "session15", "session18"):
    sys.path.insert(0, f"/workspace/src/{_dir}")

import eval_harness as harness  # noqa: E402

# 指標の並び順（出力とレビューの順序を固定する）
METRICS: tuple[str, ...] = (
    "retrievalRecall",
    "generationGrounded",
    "generationFactual",
    "supportRatio",
    "refusalRate",
    "hallucinationRate",
    "retrievalLatencyMsP95",
)

# 小さいほど良い指標（上限として判定する）
LOWER_IS_BETTER: tuple[str, ...] = ("hallucinationRate", "retrievalLatencyMsP95")

# 実測値を表示しない指標（環境で変わるため、本文にも合否表にも固定しない）
HIDDEN: tuple[str, ...] = ("retrievalLatencyMsP95",)

PROFILES: dict[str, dict[str, float]] = {
    # いまの姿。q-09 / q-10 が答えられていない状態をそのまま固定してある。
    # **これは「正しい姿」ではなく「いまの姿」です。** 直したときに気づくために置く
    "baseline": {
        "retrievalRecall": 1.0,
        "generationGrounded": 0.8,
        "generationFactual": 0.8,
        "supportRatio": 0.8,
        "refusalRate": 1.0,
        "hallucinationRate": 0.0,
        "retrievalLatencyMsP95": 5000.0,
    },
    # 目指す姿。カタカナ語だけで聞かれた質問にも答えられるようにしたい
    "target": {
        "retrievalRecall": 1.0,
        "generationGrounded": 0.9,
        "generationFactual": 0.9,
        "supportRatio": 0.9,
        "refusalRate": 1.0,
        "hallucinationRate": 0.0,
        "retrievalLatencyMsP95": 5000.0,
    },
}


def decide(metrics: dict[str, float], profile: str = "baseline") -> dict:
    """しきい値と突き合わせる。**判定はここだけ**（表示と分離しておく）。"""
    thresholds = PROFILES[profile]
    rows: list[dict] = []
    for name in METRICS:
        measured = metrics[name]
        threshold = thresholds[name]
        lower_is_better = name in LOWER_IS_BETTER
        passed = measured <= threshold if lower_is_better else measured >= threshold
        rows.append(
            {
                "metric": name,
                "measured": measured,
                "threshold": threshold,
                "bound": "上限" if lower_is_better else "下限",
                "hidden": name in HIDDEN,
                "passed": passed,
            }
        )
    failed = [row["metric"] for row in rows if not row["passed"]]
    return {"profile": profile, "rows": rows, "failed": failed, "passed": not failed}


def exit_code(verdict: dict) -> int:
    """CI が読む値。**しきい値を割ったら 1**（人に読ませない）。"""
    return 0 if verdict["passed"] else 1


def report_line(row: dict) -> str:
    measured = "(非表示)" if row["hidden"] else f"{row['measured']:.4f}"
    return (
        f"  {row['metric']} 実測 {measured} / {row['bound']} {row['threshold']:.4f}"
        f" -> {'OK' if row['passed'] else 'NG'}"
    )


def main(argv: list[str]) -> int:
    profile = "baseline"
    if "--profile" in argv:
        profile = argv[argv.index("--profile") + 1]
    if profile not in PROFILES:
        print(f"profile は {sorted(PROFILES)} のいずれかです: {profile}")
        return 2

    harness.reset_mock()
    metrics = harness.measure()
    verdict = decide(metrics, profile)
    code = exit_code(verdict)

    print(f"=== 品質ゲート（profile={profile} / しきい値を割ったら非0で終了する） ===")
    for row in verdict["rows"]:
        print(report_line(row))
    if verdict["passed"]:
        print("  判定: 合格（終了コード 0）")
    else:
        print(
            f"  判定: 不合格（終了コード 1）/ 割った指標: {', '.join(verdict['failed'])}"
        )
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
