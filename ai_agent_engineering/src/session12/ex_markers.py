#!/usr/bin/env python3
"""練習問題の参照解：言い換えられた注入を検出するマーカーを足す。

既定のマーカーは DOC-0004 を 5 個で検出するが、同じ狙いを言い換えた文（`PARAPHRASED`）は
1 個も検出できない。マーカーを足せば検出できるが、**誤検出を増やしてはいけない**。
「増やせば安全」ではなく「増やしても正当な文書を巻き込まない」までが入力検査の設計である。

    python src/session12/ex_markers.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from boundary import (INJECTION_MARKERS, PARAPHRASED, detection_rate,  # noqa: E402
                      find_markers, scan_docs)

# 追加するマーカー。言い換え文に固有の言い回しを選ぶ。
# 「一覧」「取得」のような業務で普通に使う語を入れると、正当な文書を巻き込む
# （DOC-0003「経費申請一覧を取得します」が誤検出になる）。
EXTRA_MARKERS: tuple[str, ...] = (
    "以前の案内は取り下げ",
    "利用者への報告は不要",
    "確認用アドレス",
)
EXTENDED_MARKERS: tuple[str, ...] = INJECTION_MARKERS + EXTRA_MARKERS

# 誤検出を起こす「やってしまいがちな」マーカー（比較用）
NAIVE_EXTRA: tuple[str, ...] = ("一覧", "取得")
NAIVE_MARKERS: tuple[str, ...] = INJECTION_MARKERS + NAIVE_EXTRA


def summarize(markers: tuple[str, ...]) -> tuple[int, int, int]:
    """(注入文書の検出, 誤検出, 言い換え文の検出語数) を返す。"""
    detected, false_positive = detection_rate(scan_docs(markers))
    return detected, false_positive, len(find_markers(PARAPHRASED, markers))


def main() -> None:
    print("マーカーの組 | 文書の検出 | 文書の誤検出 | 言い換え文の検出語数")
    for label, markers in (("既定の5語", INJECTION_MARKERS),
                           ("＋一覧・取得（やりがち）", NAIVE_MARKERS),
                           ("＋言い換えに固有の3語", EXTENDED_MARKERS)):
        detected, false_positive, para = summarize(markers)
        print(f"{label} | {detected}/1 | {false_positive}/4 | {para}")


if __name__ == "__main__":
    main()
