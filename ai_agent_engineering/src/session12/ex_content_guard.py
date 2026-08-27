#!/usr/bin/env python3
"""練習問題の参照解：出口を「宛先」から「内容」まで広げる出力検査。

多層防御を全部積んでも、`write_file` という出口が残る（`tools/bench_injection.py` の
⑦の行で「書き出し 1」が消えない）。宛先しか見ていない検査は、宛先を持たない操作を
素通しするからである。ここでは**外へ出る本文そのもの**を検査対象にする。

    python src/session12/ex_content_guard.py

自分で書いてから読むこと。答えを読んでから書くと「なぜその条件なのか」が残らない。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.models import ToolCall  # noqa: E402
from defenses import EXIT_TOOLS, ExactRecipientInspector, first_secret  # noqa: E402
from layers import COLUMNS, STACK, Config, render, reset, run_config  # noqa: E402


class ContentInspector:
    """宛先に加えて、外へ出ていく本文そのものを検査する。

    設計上の判断が3つある。
      1. 宛先の検査は既存の実装（`ExactRecipientInspector`）に委ねる（車輪を作り直さない）
      2. 検査対象の出口は `EXIT_TOOLS` として**列挙**する（暗黙に全ツールを対象にしない）
      3. 機密の一覧はデータから作る（`first_secret`）。人が手で書いた定数にしない
    """

    label = "宛先＋内容"

    def __init__(self, recipients=None) -> None:
        self.recipients = recipients or ExactRecipientInspector()

    def check(self, call: ToolCall) -> str | None:
        reason = self.recipients.check(call)
        if reason is not None:
            return reason
        if call.name not in EXIT_TOOLS:
            return None
        # 送信は body、ファイル書き込みは content。出口ごとに「外へ出る文字列」は別の引数にある
        text = str(call.args.get("body") or call.args.get("content") or "")
        hit = first_secret(text)
        if hit is None:
            return None
        return (f"外へ出る本文に機密（{hit}）が含まれています。"
                "個人情報を含む持ち出しは所属長と情報セキュリティ室の二者承認が必要です。")


WITH_CONTENT = Config("⑧ ＋内容検査", prompt=True, detect=True, separate=True,
                      privilege=True, inspector=ContentInspector)


def main() -> None:
    print("=== 出力検査の対象を広げる（3ケース）===")
    print(render([run_config(STACK[5]), run_config(WITH_CONTENT)],
                 COLUMNS + ("禁止された結果",)))

    print("\n=== 誤検出の確認：機密を含まない正当な書き込みは通す ===")
    ok = ToolCall("t-ok", "write_file",
                  {"path": "report.md", "content": "月次レポートの下書きです。合計は 285,400 円でした。"})
    ng = ToolCall("t-ng", "write_file",
                  {"path": "s12_outbox.md", "content": "EMP-001 佐藤 健 東京都港区1-1-1 評価B"})
    inspector = ContentInspector()
    print(f"住所を含まない下書き | {inspector.check(ok) or '通す'}")
    print(f"住所を含む書き出し | {'止める' if inspector.check(ng) else '通す'}")
    reset()


if __name__ == "__main__":
    main()
