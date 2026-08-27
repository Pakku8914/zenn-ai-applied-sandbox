#!/usr/bin/env python3
"""復習03：層を積んで、減った件数で優先順位を裏づける（S12）。

「多層防御にしましょう」で終わらせないために、**1層足すごとに何件減ったか**を測る。
測り方は S12 のまま（`src/session12/layers.py`）で、構成の組み合わせだけを変える。

    python src/review03/stack.py

**副作用を出す測定である。** `layers.reset()` が測定1件ごとに業務データを初期状態へ
戻し、持ち出し用のファイル（`workspace/s12_outbox.md`）も消す。3ケース × 8構成 = 24 回
の走行を行うので、他の検証より時間がかかる。

攻撃の再現は**この演習環境の中だけ**で完結する。注入の本文は `data/docs.jsonl` の
DOC-0004 に最初から入っているものを使い、新しい攻撃文字列は増やさない。

`agentkit` と `src/session12/` は1行も変更しない。
"""

from __future__ import annotations

from _paths import setup

ROOT = setup()

from defenses import ExactRecipientInspector  # noqa: E402
from ex_content_guard import ContentInspector  # noqa: E402  (S12 問題7 の参照解)
from layers import COLUMNS, Config, render, reset, run_config  # noqa: E402

WIDE = COLUMNS + ("禁止された結果",)
COUNTED = ("外部送信", "書き出し", "機密流入", "警告")

# 同じ穴（社外への持ち出し）を塞げる3つの層。1層だけで使ったときの効き方を見る
SINGLE_LAYERS: tuple[Config, ...] = (
    Config("権限制限だけ", privilege=True),
    Config("出力検査だけ", inspector=ExactRecipientInspector),
    Config("人間承認だけ", approval=True),
)

# 1層ずつ積む。**気づく層（入力検査・構造分離）を先に積むのが要点**
# ——先に積んでおくと、そのあと何件減ったかを層ごとに切り分けられる
STACK: tuple[Config, ...] = (
    Config("① 防御なし"),
    Config("② ＋入力検査・構造分離", detect=True, separate=True),
    Config("③ ＋権限制限", detect=True, separate=True, privilege=True),
    Config("④ ＋出力検査（完全一致）", detect=True, separate=True, privilege=True,
           inspector=ExactRecipientInspector),
    Config("⑤ ＋内容検査（宛先＋内容）", detect=True, separate=True, privilege=True,
           inspector=ContentInspector),
)


def single_rows() -> list[dict]:
    return [run_config(config) for config in SINGLE_LAYERS]


def stack_rows() -> list[dict]:
    return [run_config(config) for config in STACK]


def reduction(rows: list[dict]) -> list[dict]:
    """1層足すごとに、禁止された結果が何件減り、何が変わったかを並べる。"""
    out = []
    for prev, cur in zip(rows, rows[1:]):
        changed = [f"{key} {prev[key]} → {cur[key]}"
                   for key in COUNTED if prev[key] != cur[key]]
        out.append({"足した層": cur["構成"],
                    "禁止された結果": cur["禁止された結果"],
                    "減った件数": prev["禁止された結果"] - cur["禁止された結果"],
                    "変わったもの": " / ".join(changed) or "変化なし"})
    return out


def main() -> None:
    print("=== 1層だけで守る（同じ穴を塞げる3つの層）===")
    print(render(single_rows(), WIDE))

    rows = stack_rows()
    print("\n=== 1層ずつ積む ===")
    print(render(rows, WIDE))

    print("\n=== 1層足すごとに何件減ったか ===")
    print("足した層 | 禁止された結果 | 減った件数 | 変わったもの")
    for row in reduction(rows):
        print(f"{row['足した層']} | {row['禁止された結果']} | {row['減った件数']} | "
              f"{row['変わったもの']}")
    reset()


if __name__ == "__main__":
    main()
