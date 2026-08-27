#!/usr/bin/env python3
"""SLO 4本とアラート10件（最終プロジェクト）。

    python src/final/slo_alerts.py            # SLO とアラートを表示する
    python src/final/slo_alerts.py --markdown # 成果物④（Markdown）を出す

中間プロジェクト1 で作った SLO の導出手順（測った p95 × 係数 → 切り上げ →
要件の天井と比べる）は**作り直さない**。ここで足すのは2つだけである。

1. **エッジ側の SLO はバケットで表す。** パーセンタイルは足せないので、
   1,000 台から p95 を集めても意味のある数にならない（セッション15）。
2. **系としての SLO（完結率）。** エッジで完結した割合が下がるとクラウドの
   需要が増え、台数・メモリ・単価が上がる。速さではなく**コストと
   プライバシーの約束**である。

アラートは5要素（指標・しきい値・観測期間・アクション・担当）を強制する。
1つでも欠けたら「鳴ったが誰も動かない」ものになる。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

SANDBOX = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SANDBOX))

from src.final.design import Design  # noqa: E402
from src.mid01.slo import (  # noqa: E402
    DEFAULT_SLOS, MEASURED_CONDITIONS, REQUIREMENTS, derive_floor,
    tpot_budget_ms,
)
from src.session15.fleet import BUCKET_LABELS, FAILURE_TOLERANCE  # noqa: E402

MARGIN = 1.5
"""③ 前提値：測った p95 に掛ける係数（中間プロジェクト1 と同じ）。"""

ROUND_TO = 100.0
"""③ 前提値：目標値の丸め幅（運用で覚えられる粒度）。"""

EDGE_BUCKET = BUCKET_LABELS[1]
"""エッジの一次応答の目標バケット（「1.0 ms 未満」）。境界は SLO 側で固定する。"""

EDGE_MEASURED_P50_MS = 0.29
"""① 実測：int8 分類器の定常 p50（2026-08-15）。絶対値は環境で変わる。"""


@dataclass(frozen=True)
class Objective:
    """SLO 1本。**導き方を持たない SLO は作れないようにしてある。**

    値だけが書かれた目標は、達成できるかどうか分からない願望である。
    """

    key: str
    label: str
    target: str
    derivation: str
    how: str
    window: str
    ceiling: str
    on_breach: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.target:
            raise ValueError("目標値が空です")
        if not self.derivation:
            raise ValueError("目標値の導き方が書かれていません")
        if not self.on_breach:
            raise ValueError("超えたときにやることが1つも書かれていません")


@dataclass(frozen=True)
class Alert:
    """アラート1件。**5要素すべてが埋まっていないと作れない。**

    セッション16 の再判断のトリガーと同じ規律である。指標だけのアラートは
    「鳴ったが誰も動かない」ものになり、鳴りっぱなしのまま無視される。
    """

    metric: str      # 何を見るか
    threshold: str   # どうなったら
    window: str      # どれだけ続いたら
    action: str      # 何をするか
    owner: str       # 誰がやるか
    guard: str = ""  # 誤検知を抑える条件（件数の下限など）

    def __post_init__(self) -> None:
        missing = [name for name, value in (("指標", self.metric),
                                            ("しきい値", self.threshold),
                                            ("観測期間", self.window),
                                            ("アクション", self.action),
                                            ("担当", self.owner)) if not value]
        if missing:
            raise ValueError("アラートに欠けている要素があります: "
                             + " / ".join(missing))


PROVISIONAL = (
    "ゲートウェイの MAX_INFLIGHT が上流のスロット数と同じかを確認する（3 分）",
    "応答キャッシュの TTL を 300 → 900 秒に延ばす（1 分）",
    "しきい値を一段下げて送信率を落とす（エッジ側・5 分）",
)
"""暫定対応（当番・5 分以内）。**1 回に 1 つだけ実施する。**"""

PERMANENT = (
    "src/review01/triage.py に観測値を渡し、支配要因を確定させる（10 分）",
    "キュー待ちが支配的なら、容量計画に従って台数を1本増やす（30 分）",
    "デコードが支配的なら、本番構成（-c 2048 -np 2）で量子化を測り直す（2 時間）",
    "完結率が下がっているなら、モデルの版と入力の分布を点検する（半日）",
)
"""恒久対応（オーナー・次営業日まで）。"""


def objectives(design: Design | None = None) -> tuple[Objective, ...]:
    """SLO 4本。3本は中間プロジェクト1 の導出、4本目が本章で足すもの。"""
    d = design or Design()
    ttft, total = DEFAULT_SLOS[0], DEFAULT_SLOS[1]
    ttft_req, total_req = REQUIREMENTS[0], REQUIREMENTS[1]
    point = d.point
    tpot = tpot_budget_ms(total.target_ms, ttft.target_ms, d.max_tokens)
    return (
        Objective(
            key="edge_latency",
            label="エッジの一次応答（p95 のバケット）",
            target=f"「{EDGE_BUCKET}」に入る",
            derivation=(
                f"定常 p50 {EDGE_MEASURED_P50_MS:.2f} ms（実測）に対し、"
                "境界 0.5 / 1.0 / 2.0 / 5.0 ms を SLO 側で固定する。"
                "**パーセンタイルは足せない**ので端末からは件数（バケット）で"
                "受け取り、合計してから分位を求める"),
            how="端末の集約指標（1日1回）を版ごとに合計してから分位を求める",
            window="1 日",
            ceiling=f"{d.edge_slo_ms:,.0f} ms（前提値）",
            on_breach=("版ごとに分けて見る（新版だけ悪化していないか）",
                       "端末の資源競合を疑う（スレッド数・他アプリ）",
                       "悪化が新版だけなら展開を中止して既知正常版へ戻す")),
        Objective(
            key="cloud_ttft",
            label="クラウドの TTFT p95",
            target=f"{ttft.target_ms:,.0f} ms 以内",
            derivation=(
                f"実測 p95 {point.ttft_p95_ms:,.0f} ms × {MARGIN} = "
                f"{point.ttft_p95_ms * MARGIN:,.0f} → {ROUND_TO:.0f} ms 単位で"
                f"切り上げて {derive_floor(point.ttft_p95_ms, MARGIN, ROUND_TO):,.0f} ms"),
            how=f"固定プロンプト 20 件 / 出力 {d.max_tokens} トークン / 温度 0 / "
                f"並列 {point.concurrency}",
            window="営業日 9:00〜18:00",
            ceiling=f"{ttft_req.ceiling_ms:,.0f} ms（前提値）",
            on_breach=PROVISIONAL + PERMANENT),
        Objective(
            key="cloud_total",
            label="クラウドの総時間 p95",
            target=f"{total.target_ms:,.0f} ms 以内",
            derivation=(
                f"実測 p95 {point.total_p95_ms:,.0f} ms × {MARGIN} = "
                f"{point.total_p95_ms * MARGIN:,.0f} → 切り上げて "
                f"{derive_floor(point.total_p95_ms, MARGIN, ROUND_TO):,.0f} ms。"
                f"内部目標として TPOT ≦ ({total.target_ms:,.0f} − "
                f"{ttft.target_ms:,.0f}) ÷ ({d.max_tokens} − 1) = {tpot:.1f} ms"),
            how="同上",
            window="営業日 9:00〜18:00",
            ceiling=f"{total_req.ceiling_ms:,.0f} ms（前提値）",
            on_breach=PROVISIONAL + PERMANENT),
        Objective(
            key="completion_ratio",
            label="エッジの完結率（系としての SLO）",
            target=f"{d.completion_ratio:.1%} 以上",
            derivation=(
                f"送信率 {d.send_ratio:.1%} の裏返し。下限は "
                f"{d.completion_floor:.1%}（これを下回ると合計ピークが能力 "
                f"{d.capacity_rps:.3f} rps を超え、台数が {d.instances + 1} 本になる）"),
            how="端末の集約指標から edge_completion_ratio を日次で集計する",
            window="1 日",
            ceiling=f"下限 {d.completion_floor:.1%}（台数が増える境界）",
            on_breach=("台数を数え直す（src/final/design.py）",
                       "しきい値が変更されていないかを確認する",
                       "モデルの版と入力の分布を点検する",
                       "台数を増やす場合はコスト試算を作り直す")),
    )


def alerts(design: Design | None = None) -> tuple[Alert, ...]:
    """アラート10件。**同じ原因で複数鳴ることを前提に、読む順序を決めておく。**"""
    d = design or Design()
    ttft, total = DEFAULT_SLOS[0], DEFAULT_SLOS[1]
    return (
        Alert("inference_queue_length（1本あたり）", "1.0 件", "5 分継続",
              f"台数を1本増やす（上限 {d.instances + 1}）", "当番",
              "瞬間値で鳴らさない"),
        Alert("TTFT p95", f"{ttft.target_ms:,.0f} ms 超", "2 日連続",
              "SLO 違反として恒久対応に入る", "オーナー",
              "20 件以上で測った値のみ"),
        Alert("総時間 p95", f"{total.target_ms:,.0f} ms 超", "2 日連続",
              "SLO 違反として恒久対応に入る", "オーナー", "同上"),
        Alert("inference_gateway_rejected_total の率（503）", "1% 超",
              "15 分継続", "MAX_INFLIGHT とキューの期限を確認する", "当番",
              "総件数 100 件以上"),
        Alert("429 の率", "5% 超", "15 分継続",
              "そのキーの rate と burst の配分を見直す", "当番",
              "キー単位で見る"),
        Alert("edge_completion_ratio", f"{d.completion_floor:.1%} 未満",
              "1 日継続", "台数を数え直し、しきい値とモデルを点検する",
              "オーナー", "1,000 件以上の判定があるとき"),
        Alert("旧版の端末の割合", "5% 超", "7 日継続",
              "取り残しの原因を調べる（回線・容量・タイムアウト）", "オーナー",
              "オフライン端末を分母から外さない"),
        Alert("新版の失敗率", f"現行版の {FAILURE_TOLERANCE} 倍超",
              "段の観察期間内", "展開を中止し、既知正常版へ戻す", "オーナー",
              "件数 1,000 件未満なら「保留」（中止にしない）"),
        Alert("端末の p95 のバケット", f"「{EDGE_BUCKET}」から悪化", "1 日継続",
              "端末の資源競合を疑う（スレッド数・他アプリ）", "当番",
              "版ごとに分けて見る"),
        Alert("利用率", f"{d.utilization:.1%} を下回る", "2 週間継続",
              "停止スケジュールか台数の見直しを検討する", "オーナー",
              "月末月初の偏りを除く"),
    )


GUARDS = (
    "件数の下限を先に見る（3 件中1件失敗を 33.3% と読むと良い版を捨てる）",
    "観測期間を必ず付ける（瞬間値で鳴らすとロールアウト中に鳴る）",
    "同じ原因のアラートを束ねる（飽和では 1・2・3・4 が同時に鳴る。"
    "当番が最初に読むのは 1 番と決めておく）",
)

REVIEW_CONDITIONS = (
    "量子化形式・-np・-c のいずれかを変えた",
    "モデルを載せ替えた（0.5B から 8B 級へなど）",
    "出力上限（max_tokens）を変えた",
    "しきい値を変えた（送信率が動くので完結率の目標も動く）",
    "応答キャッシュのヒット率が大きく変わった",
    "端末を置き換えた（メモリの上限が変わる）",
)


def markdown(design: Design | None = None) -> str:
    """成果物④（SLO とアラート設計）。"""
    d = design or Design()
    lines = [
        "# SLO とアラート設計：みなと商事 ハイブリッド推論基盤",
        "",
        "最終更新: 2026-08-15 / 次回見直し: 構成変更時、または3か月後",
        f"測定条件: {MEASURED_CONDITIONS}",
        "",
        "## 1. SLO（指標・目標値・導き方・測定方法・超えたときの行動）",
        "",
        "| # | 指標 | 目標値 | 導き方 | 天井（要件） |",
        "| --: | :--- | :--- | :--- | :--- |",
    ]
    objs = objectives(d)
    for i, o in enumerate(objs, start=1):
        lines.append(f"| {i} | {o.label} | {o.target} | {o.derivation} | "
                     f"{o.ceiling} |")
    lines += ["", "測定方法と超えたときの行動:", ""]
    for i, o in enumerate(objs, start=1):
        lines.append(f"{i}. **{o.label}**（測定: {o.how} / 窓: {o.window}）")
        for action in o.on_breach:
            lines.append(f"   - {action}")
    completion = objs[-1]
    lines += [
        "",
        "## 2. 系としての SLO（完結率）",
        "",
        f"- 目標: {completion.target}（下限 {d.completion_floor:.1%}）",
        f"- 意味: これは速さの約束ではなく、**コストとプライバシーの約束**である。"
        f"完結率が下がるとクラウドへ回る件数が増え、合計ピークが能力 "
        f"{d.capacity_rps:.3f} rps を超えた時点で台数が {d.instances} → "
        f"{d.instances + 1} 本になる",
        "- 下がる原因: モデルの劣化 / 入力の分布の変化 / しきい値の変更",
        f"- 波及: 台数が1本増えるとメモリ要求は {d.total_memory_mib:,} MiB → "
        f"{d.total_memory_mib + d.plan.memory_per_instance_mib:,} MiB になる",
        "",
        "## 3. アラート（5要素すべてを埋める）",
        "",
        "| # | 指標 | しきい値 | 観測期間 | アクション | 担当 | 誤検知を抑える条件 |",
        "| --: | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for i, a in enumerate(alerts(d), start=1):
        lines.append(f"| {i} | {a.metric} | {a.threshold} | {a.window} | "
                     f"{a.action} | {a.owner} | {a.guard or '—'} |")
    lines += ["", "## 4. 誤検知を抑える仕掛け", ""]
    lines += [f"{i}. {g}" for i, g in enumerate(GUARDS, start=1)]
    lines += ["", "## 5. この SLO を見直す条件", ""]
    lines += [f"{i}. {c}" for i, c in enumerate(REVIEW_CONDITIONS, start=1)]
    return "\n".join(lines) + "\n"


def _pad(label: str, width: int = 30) -> str:
    used = sum(2 if ord(ch) > 0x2E80 else 1 for ch in label)
    return label + " " * max(width - used, 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SLO とアラート")
    parser.add_argument("--markdown", action="store_true",
                        help="成果物④（Markdown）を出す")
    args = parser.parse_args(argv)

    design = Design()
    if args.markdown:
        print(markdown(design), end="")
        return 0

    print("=== SLO（4本。3本は中間プロジェクト1 の導出、4本目が本章で足すもの）===")
    for i, o in enumerate(objectives(design), start=1):
        print(f"{i}. {_pad(o.label)}: {o.target}  ← 天井 {o.ceiling}")
    print()
    print("=== アラート（5要素すべて埋まっているものだけ作れる）===")
    for i, a in enumerate(alerts(design), start=1):
        print(f"{i:>2}. {_pad(a.metric, 42)} {a.threshold} / {a.window} / "
              f"{a.action}（{a.owner}）")
    print()
    print("-> 5要素のどれかを空にすると Alert は作れない（ValueError になる）。")
    print("-> 完結率は速さの約束ではなく、コストとプライバシーの約束である。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
