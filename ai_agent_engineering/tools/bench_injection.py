#!/usr/bin/env python3
"""間接プロンプトインジェクションに対する防御の効き方を決定的に測る（セッション12の出典）。

    python tools/bench_injection.py

**演習環境の中でのみ**攻撃を再現する。第三者のシステムに対して試してはならない。
攻撃の本文は `data/docs.jsonl` の DOC-0004 に最初から仕込んである架空の文字列で、
新しい攻撃ペイロードは増やしていない。

7構成 × 3ケース ＝ 21 回の実行に、実装差の比較 4 回を足して測る。
副作用（送信・書き出し）は1回ごとに初期化するので、何度実行しても同じ数値になる。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "src" / "session12")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from attacks import CASES  # noqa: E402
from boundary import PARAPHRASED, detection_rate, find_markers, scan_docs  # noqa: E402
from defenses import (ExactRecipientInspector, LooseInspector,  # noqa: E402
                      PrefixRecipientInspector)
from layers import COLUMNS, SINGLE, STACK, Config, render, reset, run_case, run_config  # noqa: E402


def main() -> None:
    print("=== 攻撃ケース（すべて演習環境の中の架空データ）===")
    for c in CASES:
        print(f"{c.label} | {c.route}")

    print("\n=== 単層防御：1層だけで守る ===")
    print(render([run_config(c) for c in SINGLE]))

    print("\n=== 多層防御：1層ずつ積む ===")
    print(render([run_config(c) for c in STACK], COLUMNS + ("禁止された結果",)))

    print("\n=== 出力検査の実装差（ケース②だけを走らせる）===")
    print("実装 | 外部送信 | 遮断")
    for label, inspector in (("前方一致", PrefixRecipientInspector),
                             ("完全一致", ExactRecipientInspector)):
        row = run_case(Config(label, privilege=True, inspector=inspector), CASES[1])
        print(f"{label} | {row['外部送信']} | {row['遮断']}")

    print("\n=== 層は互いのミスを吸収する（ケース①・許可リストに社外アドレスを誤って入れた場合）===")
    print("構成 | 外部送信 | stop_reason")
    for label, approval in (("出力検査（誤設定）のみ", False),
                            ("出力検査（誤設定）＋人間承認", True)):
        row = run_case(Config(label, privilege=True, inspector=LooseInspector,
                              approval=approval), CASES[0])
        print(f"{label} | {row['外部送信']} | {row['stop_reason']}")

    print("\n=== 入力検査の検出率 ===")
    detected, false_positive = detection_rate(scan_docs())
    print(f"文書 5 件: 検出 {detected}/1 ・ 誤検出 {false_positive}/4")
    print(f"言い換えた注入: 検出 {len(find_markers(PARAPHRASED))}/1")
    reset()


if __name__ == "__main__":
    main()
