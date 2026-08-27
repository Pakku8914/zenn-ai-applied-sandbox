#!/usr/bin/env python3
"""区分表・参照ラベル・特徴量化・測定プロトコル（中間プロジェクト2）。

2つの実装を比べるには、**入力と出力の形を先に固定する**必要がある。
このファイルはその契約で、案A（クラウド）と案B（エッジ）の両方が読む。

    python src/mid02/task.py --list        # 6区分と参照ラベル
    python src/mid02/task.py --protocol    # 測定プロトコル 8 項目
    python src/mid02/task.py --features    # 特徴量化が決定的であることの確認

数値の3分類（セッション11で決めたもの）:
  ① 実測値  : reports/ の測定結果（測定条件つきで引用する）
  ② 物理計算: 定数から計算できるもの（往復の下限など）
  ③ 前提値  : 読者が入れるもの（参照ラベル・端末数・距離・固定費）

**参照ラベルは③である。** 一致率が低いとき、原因はモデルとは限らない。
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import numpy as np

SANDBOX = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SANDBOX))

from tools.prompts import QUESTIONS  # noqa: E402

INPUT_DIM = 384
"""特徴量の次元。models/onnx の分類器の入力に合わせる（変えるとモデルが読めない）。"""

N_CLASSES = 6

CATEGORIES: tuple[tuple[str, str], ...] = (
    ("A", "勤怠・休暇"),
    ("B", "経費・精算"),
    ("C", "PC・アカウント"),
    ("D", "セキュリティ"),
    ("E", "設備・備品"),
    ("F", "規程・手続き"),
)

SYMBOLS: tuple[str, ...] = tuple(sym for sym, _ in CATEGORIES)
NAMES: tuple[str, ...] = tuple(name for _, name in CATEGORIES)

REFERENCE_LABELS: tuple[int, ...] = (
    0, 1, 2, 2, 4, 3, 1, 2, 4, 5,
    0, 4, 3, 0, 5, 4, 0, 3, 4, 0,
)
"""③ 前提値。QUESTIONS と同じ順序で並べた参照ラベル（人が決めたもの）。"""

BORDERLINE: dict[int, tuple[int, str]] = {
    9: (2, "PC の返却手続きなので C とも読める"),
    11: (3, "紛失は情報資産の事故なので D とも読める"),
    18: (1, "料金の話なので B とも読める"),
}
"""境界事例。**別の区分でも説明が付く件をあらかじめ宣言しておく。**

こう書いておくと、一致率が低いときに「境界事例で外したのか」「明らかな件で
外したのか」を分けて数えられる。分けずに1つの正解率だけを見ると、
ラベル設計の問題をモデルの問題と誤診する。
"""

PROTOCOL: tuple[tuple[str, str], ...] = (
    ("入力集合", "tools/prompts.py の QUESTIONS 20 件（順序固定）"),
    ("出力の形", "区分 ID（0-5）と確度（0.0-1.0）"),
    ("件数", "20 件以上（p95 を出すため）"),
    ("ウォームアップ", "クラウド 2 回 / エッジ 3 回（どちらも定常状態を測る）"),
    ("測定点", "アプリが区分 ID を受け取るまで"),
    ("代表値", "3 回測って中央値"),
    ("条件の記録", "conditions に両方の条件を残す"),
    ("揃えられない条件", "モデル規模 / ネットワーク往復（揃えず、差の内訳に分解する）"),
)


def label_counts() -> list[int]:
    return [REFERENCE_LABELS.count(i) for i in range(N_CLASSES)]


def featurize(text: str) -> np.ndarray:
    """文字列を 384 次元のベクトルにする（**決定的なハッシュ特徴**）。

    埋め込みモデルは使わない。読者に外部からのダウンロードを要求しないためで、
    その代わり**意味は捉えない**。参照ラベルに対する正解率が意味を持たないのは
    ここが理由であり、成果物には必ずこの制約を書く。

    ・文字 2-gram を SHA-256 で 384 個の枠に割り振る
    ・ハッシュの 5 バイト目で符号を決める（符号付きハッシュ特徴）
    ・L2 ノルムを 1 に正規化する（入力のスケールを揃える）

    組み込みの hash() を使ってはいけない。文字列に対する hash() は
    プロセスごとに変わるので、**過去に測った数字と比較できなくなる**。
    """
    vec = np.zeros(INPUT_DIM, dtype=np.float32)
    grams = [text[i:i + 2] for i in range(len(text) - 1)] or [text]
    for gram in grams:
        digest = hashlib.sha256(gram.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % INPUT_DIM
        vec[idx] += 1.0 if digest[4] % 2 == 0 else -1.0
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm > 0.0 else vec


def feature_matrix(questions: tuple[str, ...] | list[str] = QUESTIONS) -> np.ndarray:
    return np.stack([featurize(q) for q in questions])


def show_list() -> None:
    print("=== 6区分（本章で定義。参照ラベルは人が決めた前提値です）===")
    print("| ID | 記号 | 区分名 | 件数 |")
    print("| --: | :--- | :--- | --: |")
    for i, ((sym, name), n) in enumerate(zip(CATEGORIES, label_counts())):
        print(f"| {i} | {sym} | {name} | {n} |")
    print(f"合計 {len(REFERENCE_LABELS)} 件"
          "（tools/prompts.py の QUESTIONS と 1 対 1）")
    print(f"\n境界事例 {len(BORDERLINE)} 件"
          "（別の区分でも説明が付く。判断が割れたら記録する）")
    for idx in sorted(BORDERLINE):
        alt, why = BORDERLINE[idx]
        ref = REFERENCE_LABELS[idx]
        print(f"  #{idx + 1:<2} {SYMBOLS[ref]} {NAMES[ref]} ⇔ "
              f"{SYMBOLS[alt]} {NAMES[alt]} : {QUESTIONS[idx]}")
        print(f"      理由: {why}")


def show_protocol() -> None:
    print("=== 測定プロトコル（両方の実装に同じものを適用する）===")
    for i, (name, value) in enumerate(PROTOCOL, start=1):
        print(f"{i:>2}. {name:<9}: {value}")


def show_features() -> None:
    mat = feature_matrix()
    again = feature_matrix()
    norms = np.linalg.norm(mat, axis=1)
    uniq = len({tuple(row.tolist()) for row in mat})
    print("=== 特徴量化の確認（誰の環境でも同じ結果になります）===")
    print(f"形状          : {mat.shape}")
    print(f"決定的か      : {'はい' if np.array_equal(mat, again) else 'いいえ'}"
          "（2回作って完全一致）")
    print(f"異なるベクトル: {uniq} / {len(mat)} 件")
    print(f"L2 ノルム     : 最小 {norms.min():.6f} / 最大 {norms.max():.6f}")
    print("-> 意味は捉えません。ここで測るのは枠組みであって精度の値ではない。")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="中間プロジェクト2のタスク定義")
    parser.add_argument("--list", action="store_true", help="6区分と参照ラベル")
    parser.add_argument("--protocol", action="store_true", help="測定プロトコル")
    parser.add_argument("--features", action="store_true", help="特徴量化の確認")
    args = parser.parse_args(argv)

    if args.protocol:
        show_protocol()
    elif args.features:
        show_features()
    else:
        show_list()
    return 0


if __name__ == "__main__":
    sys.exit(main())
