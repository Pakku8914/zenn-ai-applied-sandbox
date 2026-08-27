#!/usr/bin/env python3
"""コストと手数の測定（成果物⑤）。

    python src/mid01/metrics.py

数えるのは、環境に依存しない整数だけにする。

  手数   … モデルを呼んだ回数（状態から決めた手は数えない）
  段数   … 直列に並ぶモデル呼び出しの段数。単体構成なので段数＝手数（S08）
  呼出   … ツール呼び出しの総数（拒否したものも含む。軌跡に残る）
  失敗   … 失敗したツール結果の数
  採点   … 成果物の採点（4項目・`score.py` が機械判定する）
  ファイル … 実際に残ったファイル（副作用は軌跡ではなくデータ側で数える）

近似トークン数（比較用）＝プロンプトの文字数÷3 である。実 API の計測値ではないので、
**大小関係だけ**を根拠に使う。絶対値を設計の根拠にしてはいけない。
"""

from __future__ import annotations

from _paths import setup

ROOT = setup()

from diagnose import cause_label, diagnose, is_trustworthy_done  # noqa: E402  (復習01)
from failure_modes import classify  # noqa: E402  (S02)

from cases import run_all  # noqa: E402

# 「正常に終わるのに必要なステップ数」の見積り（正常系の実測 = 6）。
# 軌跡だけでは上限不足と暴走を区別できないので、設計時の見積りを外から渡す（復習01）。
NEEDED_STEPS = 6

COLUMNS = ("シナリオ", "手数", "段数", "呼出", "失敗", "停止理由", "結果", "採点", "ファイル")


def render_table(rows: list[dict]) -> str:
    """比較表。桁揃えはしない（全角が混ざると表示幅が環境で変わるため）。"""
    lines = [" | ".join(COLUMNS)]
    for row in rows:
        score = row["score"]
        lines.append(" | ".join([
            row["case"].name, str(row["llm_calls"]), str(row["stages"]),
            str(row["tool_calls"]), str(row["failed_calls"]), row["stop_reason"],
            row["outcome"], f"{score['passed']}/{score['total']}",
            ",".join(row["files"]) or "（なし）",
        ]))
    return "\n".join(lines)


def render_tokens(rows: list[dict]) -> str:
    """近似トークン（比較用）。手数が増えると入力は手数以上の比率で増える。"""
    lines = ["シナリオ | 手数 | 近似in合計 | 1手ごとの近似in | 近似out合計"]
    for row in rows:
        lines.append(f"{row['case'].name} | {row['llm_calls']} | "
                     f"{sum(row['input_tokens'])} | "
                     f"{' → '.join(str(n) for n in row['input_tokens'])} | "
                     f"{sum(row['output_tokens'])}")
    return "\n".join(lines)


def render_trust(rows: list[dict]) -> str:
    """停止理由を鵜呑みにせず、失敗モードと原因を並べる（S02・復習01）。"""
    lines = ["シナリオ | 停止理由 | 失敗モード | 原因（6分類） | done を信用できるか"]
    for row in rows:
        registry = row["registry"]
        allowed = registry.names()
        traj = row["traj"]
        modes = classify(traj, allowed_tools=set(allowed), registry=registry)
        causes = diagnose(traj, registry=registry, allowed_tools=allowed,
                          needed_steps=NEEDED_STEPS)
        trust = is_trustworthy_done(traj, registry=registry, allowed_tools=allowed)
        lines.append(f"{row['case'].name} | {traj.stop_reason} | "
                     f"{', '.join(modes) or '検出なし'} | "
                     f"{cause_label(causes, trust)} | {'はい' if trust else 'いいえ'}")
    return "\n".join(lines)


def render_batches(rows: list[dict]) -> str:
    lines = ["シナリオ | ステップごとの実行のしかた"]
    for row in rows:
        lines.append(f"{row['case'].name} | {', '.join(row['batches']) or '（なし）'}")
    return "\n".join(lines)


def main() -> None:
    rows = run_all()
    print("=== 手数・呼び出し・結果・採点 ===")
    print(render_table(rows))
    print()
    print("=== 近似トークン（比較用＝文字数÷3。実 API の計測値ではない） ===")
    print(render_tokens(rows))
    print()
    print("=== 停止理由・失敗モード・原因・信用できるか ===")
    print(render_trust(rows))
    print()
    print("=== ツールの実行のしかた（読み取りだけを並列にする） ===")
    print(render_batches(rows))


if __name__ == "__main__":
    main()
