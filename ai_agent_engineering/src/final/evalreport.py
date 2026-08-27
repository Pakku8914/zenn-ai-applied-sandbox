#!/usr/bin/env python3
"""最終プロジェクト・成果物④：評価レポート（品質とコストを1枚に並べる）。

    python src/final/evalreport.py

引き継ぐ人が知りたいのは「賢いか」ではない。**いまどれくらいの確率で成功し、
1件いくらかかり、悪化したときにどの数字が動くか**である。だからこの1枚には
4つの数字を必ず載せる。

  ① タスク成功率       … 期待した結果に到達した割合
  ② ツール選択正解率   … 再現率（呼ぶべきものを呼んだか）と適合率（余計を呼ばなかったか）
  ③ 手数               … 平均だけでなく分布（上限を決める根拠になる）
  ④ 1件あたり単価      … 仮の単価表 × 近似トークン数

品質は S13 の指標実装（`src/session13/scoreboard.py`）をそのまま使う。
コストは `tools/traj_stats.py` の実測値に単価を掛ける。**この2つは別の実行の
測定値なので、足し合わせたり突き合わせたりしない。**
"""

from __future__ import annotations

import statistics

from final_paths import setup

ROOT = setup()

from scoreboard import TRAJ_STATS, summarize  # noqa: E402  (S13)

from suite import GROUP_OF, run_suite  # noqa: E402

# --- 仮の単価表 -------------------------------------------------------------
# 実在するモデルの料金ではない。**各自の契約に合わせて差し替える前提の値**である。
# 整数だけで計算するために「微円（＝ 1/10,000 円）」を単位にする。
# 端数の丸めが入らないので、何度計算しても同じ値になる。
PRICE_NOTE = "仮の単価表"
TOKEN_NOTE = "近似トークン数（比較用）＝プロンプトの文字数 ÷ 3"
IN_YEN_PER_1K = "30 円 / 1,000 近似トークン（入力）"
OUT_YEN_PER_1K = "150 円 / 1,000 近似トークン（出力）"
IN_MICRO_PER_TOKEN = 300     # 30 円 / 1,000 トークン = 300 微円 / トークン（復習04と同じ仮の単価表）
OUT_MICRO_PER_TOKEN = 1500   # 150 円 / 1,000 トークン = 1500 微円 / トークン（復習04と同じ仮の単価表）

# レポートに必ず載せる4つの数字（引き継ぎパッケージの採点でも同じ文字列を探す）
METRIC_HEADS = ("タスク成功率", "ツール選択正解率", "手数", "1件あたり単価")


def cost_micro(tokens_in: int, tokens_out: int) -> int:
    """1件のコストを微円で返す。整数演算なので丸め誤差が出ない。"""
    return tokens_in * IN_MICRO_PER_TOKEN + tokens_out * OUT_MICRO_PER_TOKEN


def yen(micro: int) -> str:
    return f"{micro / 10000:.4f}"


def cost_rows() -> list[dict]:
    """`tools/traj_stats.py` の実測値に仮の単価を掛けた表。"""
    rows = []
    for name, steps, tin, tout in TRAJ_STATS:
        micro = cost_micro(tin, tout)
        rows.append({"name": name, "steps": steps, "in": tin, "out": tout,
                     "micro": micro, "per_step": micro // steps})
    return rows


def cost_summary(rows: list[dict] | None = None) -> dict:
    rows = rows if rows is not None else cost_rows()
    values = [r["micro"] for r in rows]
    median = int(statistics.median(values))
    ceiling = median * 2
    return {
        "n": len(rows),
        "total": sum(values),
        "mean": sum(values) // len(values),
        "median": median,
        "max": max(values),
        "min": min(values),
        "ceiling": ceiling,
        "over": [r["name"] for r in rows if r["micro"] > ceiling],
        "worst": max(rows, key=lambda r: r["micro"])["name"],
    }


def quality(rows: list[dict] | None = None) -> dict:
    """品質の集計。S13 の `summarize` をそのまま使う（指標を作り直さない）。"""
    rows = rows if rows is not None else run_suite()
    pairs = [(r["case"], r["traj"]) for r in rows]
    return summarize(pairs)


# ---------------------------------------------------------------------------
def render_quality_md(summary: dict) -> str:
    lines = ["| ケース | 群 | 判定 | 期待 | 再現率 | 適合率 | 余計 | 手数 | 停止理由 |",
             "| :--- | :--- | :--- | :--- | --: | --: | --: | --: | :--- |"]
    for r in summary["rows"]:
        lines.append(" | ".join([
            f"| {r['case']}", GROUP_OF.get(r["case"], "—"),
            "成功" if r["success"] else "失敗",
            "成功すべき" if r["expect"] else "失敗すべき",
            f"{r['recall']:.3f}", f"{r['precision']:.3f}", str(r["extra"]),
            str(r["steps"]), f"{r['stop_reason']} |"]))
    return "\n".join(lines)


def render_cost_md(rows: list[dict]) -> str:
    lines = ["| シナリオ | 手数 | 近似in | 近似out | 1件あたり（円） | 1手あたり（円） |",
             "| :--- | --: | --: | --: | --: | --: |"]
    for r in rows:
        lines.append(f"| {r['name']} | {r['steps']} | {r['in']} | {r['out']} | "
                     f"{yen(r['micro'])} | {yen(r['per_step'])} |")
    return "\n".join(lines)


def report_md(rows: list[dict] | None = None) -> str:
    rows = rows if rows is not None else run_suite()
    summary = quality(rows)
    costs = cost_rows()
    cs = cost_summary(costs)
    worst = max(costs, key=lambda r: r["micro"])
    cheapest = min(costs, key=lambda r: r["micro"])
    return "\n".join([
        "# 評価レポート：みなと商事オペレーション代行エージェント",
        "",
        "## 0. この数字の出どころ",
        "",
        "- 品質（1〜2節）: この章の走行 6 ケース。モデルは `ScriptedClient`、"
        "時刻は `FixedClock` で固定してあるので、何度実行しても同じ値になります",
        f"- コスト（3〜4節）: `tools/traj_stats.py` の実測値（2026-08-15 実測 / aarch64 / "
        f"CPU 2コア / メモリ 5.8GB / Python 3.12.13）に{PRICE_NOTE}を掛けたもの",
        f"- {TOKEN_NOTE}。実 API の計測値ではありません",
        "- **1〜2節と3〜4節は別の実行の測定値です。足し合わせたり突き合わせたりしないでください**",
        "",
        "## 1. 品質",
        "",
        render_quality_md(summary),
        "",
        f"- タスク成功率: {summary['success_rate']:.3f}"
        f"（{sum(r['success'] for r in summary['rows'])}/{summary['n']}）",
        f"- 期待整合率: {summary['declared_rate']:.3f}"
        "（「失敗すべきケースが期待どおり失敗したか」まで含めた割合）",
        f"- ツール選択正解率: 再現率 {summary['recall']:.3f} / "
        f"適合率 {summary['precision']:.3f}（余計な呼び出し {summary['extra']} 回）",
        "",
        "> 再現率が 1.000 でも成功率は 1.000 になりません。"
        "**正しい道具を使っても、禁止された操作をすれば失敗です。**"
        "2つを分けて測る理由がこれです。",
        "",
        "## 2. 手数の分布",
        "",
        f"- 平均 {summary['mean_steps']:.2f} / 最小 {summary['min_steps']} / "
        f"中央値 {summary['median_steps']:.1f} / 最大 {summary['max_steps']}",
        f"- 分布: {summary['dist']}",
        "",
        "手数の上限は平均ではなく分布から決めます。"
        "成功したケースの最大手数に余裕を足した値が上限の根拠になります。",
        "",
        f"## 3. コスト（{PRICE_NOTE}）",
        "",
        f"- 入力: {IN_YEN_PER_1K}",
        f"- 出力: {OUT_YEN_PER_1K}",
        f"- **{PRICE_NOTE}です。実在するモデルの料金ではありません。**"
        "契約している単価に置き換えて使ってください",
        "",
        render_cost_md(costs),
        "",
        f"- 合計 {yen(cs['total'])} 円 / 1件あたり単価の平均 {yen(cs['mean'])} 円 / "
        f"中央値 {yen(cs['median'])} 円",
        f"- 最も高い1件は「{worst['name']}」の {yen(worst['micro'])} 円で、"
        f"最も安い「{cheapest['name']}」（{yen(cheapest['micro'])} 円）の "
        f"{worst['micro'] * 100 // cheapest['micro'] / 100:.2f} 倍です",
        "",
        "> 最も高いのは**失敗した1件**です。手数が伸びると履歴が毎回送り直されるため、"
        "コストは手数に比例せず二次的に膨らみます。",
        "",
        "## 4. 1タスクあたり単価の上限",
        "",
        f"- 上限 = 1件あたり単価の中央値 × 2 = {yen(cs['ceiling'])} 円",
        f"- この上限で打ち切られるのは {len(cs['over'])} 件（{', '.join(cs['over'])}）",
        "- 上限に当たったジョブは `limited` に落ち、引き継ぎ書を出して人に渡します。"
        "**キュー全体は止めません**",
        "",
        "## 5. 引き継いだ人が毎週見る4つの数字",
        "",
        f"| 数字 | いまの値 | 動いたら疑うこと |",
        "| :--- | :--- | :--- |",
        f"| {METRIC_HEADS[0]} | {summary['success_rate']:.3f} | 機能の回帰、データの変化 |",
        f"| {METRIC_HEADS[1]}（再現率／適合率） | "
        f"{summary['recall']:.3f} / {summary['precision']:.3f} | "
        "道具の説明文の変更、余計な呼び出しの増加 |",
        f"| {METRIC_HEADS[2]}（平均） | {summary['mean_steps']:.2f} | "
        "計画の劣化、同じ操作の反復 |",
        f"| {METRIC_HEADS[3]}（平均） | {yen(cs['mean'])} 円 | "
        "履歴の肥大、打ち切りの増加 |",
        "",
    ])


def main() -> None:
    rows = run_suite()
    print(report_md(rows))
    from evalspec import reset_data  # noqa: PLC0415

    reset_data()


if __name__ == "__main__":
    main()
