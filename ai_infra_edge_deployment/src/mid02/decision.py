#!/usr/bin/env python3
"""成果物5点を書き出す（中間プロジェクト2）。

    python src/mid02/decision.py --list                    # 成果物の一覧
    python src/mid02/decision.py --out reports/mid02_model # 5点を書き出す

**書き出し先の既定は reports/mid02_model/ である**（自分の答案を置く
reports/mid02/ を上書きしないため）。

判断・逆転条件・リスクは、compare.py と hybrid.py の計算から組み立てる。
**前提を変えれば文書の数字も変わる**のが要点で、電卓で作った文書は
前提が変わったときに必ずどこかを直し忘れる。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SANDBOX = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SANDBOX))

from src.mid02.compare import (  # noqa: E402
    CLOUD_RPS, DEVICES, EDGE_FIXED_COST, MEASURED_CONDITIONS, SIZE_INT8_MB,
    breakeven_requests, cloud_cost_per_1k, distribution_seconds,
    latency_breakdown,
)
from src.mid02.edge_side import DEVICE_D_LIMIT_MB, RUNTIME_MB  # noqa: E402
from src.mid02.hybrid import DEMO_MARGINS, sweep  # noqa: E402
from src.mid02.task import BORDERLINE, CATEGORIES, REFERENCE_LABELS  # noqa: E402

DEFAULT_OUT = "reports/mid02_model"
CHOSEN_THRESHOLD = 0.10
DECISION = "ハイブリッド（エッジ主・しきい値 0.10）"
DECIDERS = ("オフライン耐性", "プライバシー", "レイテンシ")

DELIVERABLES: tuple[tuple[str, str], ...] = (
    ("01-implementations.md", "両構成の実装（入出力の契約と実装メモ）"),
    ("02-comparison.md", "比較表（7軸・測定条件つき・揃えられない条件も明記）"),
    ("03-decision.md", "判断と根拠（前提が変われば結論が変わる条件つき）"),
    ("04-hybrid.md", "ハイブリッド案（しきい値の感度分析）"),
    ("05-risks.md", "移行時のリスク一覧（検知方法と戻し方つき）"),
)

REVERSAL: tuple[tuple[str, str, str], ...] = (
    ("総リクエスト数", "1,000,000 件と仮定",
     "分岐点を下回るとコストはクラウドが有利"),
    ("回線の可用性", "不安定（前提値）",
     "99.9% 以上で安定するならオフライン耐性の重みが下がり、案Aが再浮上"),
    ("拠点との距離", "500 km（前提値）",
     "50 km なら往復下限は 0.50 ms、エッジであることの効き幅は 2.7 倍まで落ちる"),
    ("プライバシー要件", "本文を出せない部署がある",
     "要件が外れると案Aの最大の弱点が消える"),
    ("区分の数", f"{len(CATEGORIES)} 区分",
     "増えるとモデルを作り直して全台に配り直す必要がある"),
    ("エッジの固定費", f"{EDGE_FIXED_COST:g}（相対単位）",
     "2 倍なら分岐点も 2 倍になる"),
    ("端末の資源", f"分類器で {SIZE_INT8_MB + RUNTIME_MB:.2f} MB",
     "端末で他の重いアプリが動くなら測り直す"),
)

RISKS: tuple[tuple[str, str, str, str], ...] = (
    ("版の混在", "配布中（下限を上回る時間がかかる）",
     "端末が報告するモデルのサイズとハッシュを集計", "全台を1つ前の版に戻す"),
    ("区分の追加でモデルが読めない", "6→7 区分に増やす",
     "出力次元の検査（起動時）", "旧区分表と旧モデルに戻す"),
    ("精度の劣化に気づけない", "エッジ判定を誰も検算しない",
     "日次で N 件をクラウドと突き合わせる", "しきい値を上げてクラウド比率を増やす"),
    ("プライバシーの後退", "しきい値を上げる運用変更",
     "送信率を記録し、上限を超えたら警報", "しきい値を元の値に戻す"),
    ("クラウド側の形式違反の増加", "プロンプトやモデルの変更",
     "形式違反率を記録（0% でも記録する）", "プロンプトを直前の版に戻す"),
    ("端末の資源競合", "端末で他の重いアプリが動く",
     "端末側の定常 p50 を記録し、閾値超過を報告",
     "スレッド数を1に戻す／判定を保留する"),
    ("回線断中の保留キューが溢れる", "断が長時間続く",
     "キューの長さを記録", "既定の区分に落として人に回す"),
)


def _chosen_row() -> dict:
    rows = sweep(DEMO_MARGINS, (CHOSEN_THRESHOLD,))
    return rows[0]


def implementations_md() -> str:
    counts = [REFERENCE_LABELS.count(i) for i in range(len(CATEGORIES))]
    return f"""# 実装メモ：問い合わせの一次分類

## 1. 入出力の契約（両実装で共通）

- 入力: tools/prompts.py の QUESTIONS {len(REFERENCE_LABELS)} 件（順序固定）
- 出力: 区分 ID（0-{len(CATEGORIES) - 1}）と確度（0.0-1.0）
- 区分: {" / ".join(f"{s} {n}" for s, n in CATEGORIES)}
- 件数の分布: {counts}
- 境界事例: {len(BORDERLINE)} 件（別の区分でも説明が付く件を宣言済み）
- 失敗の表し方: 区分に落とせないときは category_id を None にする
  （**既定の区分に寄せない**。寄せると形式違反が表から消える）

## 2. 案A クラウド側の実装

- プロンプトで区分の記号（A-F）だけを出させる。max_tokens=8・温度 0
- 出力の解釈: 記号が 0 個でも 2 個以上でも「形式違反」として数える
- 確度: 解釈できたら 1.0、できなければ 0.0 の**2 値しか作れない**
  （言語モデルから確率を取っていない）

## 3. 案B エッジ側の実装

- 特徴量化: 文字 2-gram の符号付きハッシュ 384 次元・L2 正規化（決定的）
- モデル: classifier_int8.onnx（{SIZE_INT8_MB:.2f} MB・動的 int8 量子化）
- 確度: softmax の最大値。マージン（1位と2位の差）も返す
- 端末の占有: 重み {SIZE_INT8_MB:.2f} + KVキャッシュ 0.00 + 実行時 {RUNTIME_MB:.2f}
  = {SIZE_INT8_MB + RUNTIME_MB:.2f} MB（端末D の上限 {DEVICE_D_LIMIT_MB:.1f} MB に収まる）

## 4. 共通にできなかったところ（そしてなぜ）

1. **モデルの規模**（0.5B の言語モデル ⇔ 18.37M の分類器）。案Bは端末に載る
   大きさでなければならないため、揃えられない。
2. **ネットワーク往復**（含む ⇔ 含まない）。含まないことが案Bの価値そのもの
   なので、揃えると比較の意味が消える。
3. **確度の粒度**（2 値 ⇔ 連続値）。案Aは言語モデルなので確率が取れない。
   このため**一次判定を案Aに置くハイブリッドは作れない**。
4. **特徴量化は意味を捉えない**（埋め込みモデルを使っていない）。したがって
   参照ラベルに対する正解率は意味のある数字にならない。ここで作ったのは
   **評価の枠組み**であり、精度の値ではない。
"""


def comparison_md() -> str:
    b = latency_breakdown()
    dist = distribution_seconds(SIZE_INT8_MB)
    return f"""# 比較表：クラウド案 vs エッジ案（問い合わせの一次分類）

## 1. 測定条件

共通: 入力は tools/prompts.py の QUESTIONS {len(REFERENCE_LABELS)} 件（順序固定）/
      出力は区分 ID と確度 / 測定点はアプリが区分 ID を受け取るまで /
      3 回測って中央値

案A（クラウド）: {MEASURED_CONDITIONS} / Q4_K_M / -c 2048 -np 2 / 並列1 /
  max_tokens=8 / 温度 0 / ウォームアップ 2 回 / ネットワーク往復を含む

案B（エッジ）: 同日・同機 / classifier_int8.onnx（{SIZE_INT8_MB:.2f} MB）/
  intra_op=1 / inter_op=1 / 固定入力（featurize は決定的）/
  ウォームアップ 3 回 / 1 回の計測は 50 回の中央値 / 往復を含まない

揃えられない条件（宣言）:
  - モデル規模: 0.5B の言語モデル ⇔ 18.37M の分類器
  - ネットワーク往復: 含む ⇔ 含まない
  - ウォームアップ回数: 2 回 ⇔ 3 回（どちらも定常状態を測るための回数）

## 2. 7軸の比較表

| # | 軸 | 案A クラウド | 案B エッジ | 出どころ |
| --: | :--- | :--- | :--- | :--- |
| 1 | 区分IDまで p50 / p95 | 自分の測定値 | 自分の測定値 | 実測 |
| 1' | 最初の反応（TTFT） | 自分の測定値 | —（注1） | 実測 |
| 2 | スループット | {CLOUD_RPS:g} rps（動作点・並列2） | 逐次の上限（注2） | 実測＋式 |
| 3 | 1000件単価 | {cloud_cost_per_1k():.4f}（件数に依存しない） | 固定費 ÷ 件数 × 1000 | 式 |
| 3' | 分岐点 | — | {breakeven_requests():,.0f} 件でクラウドと同額 | 式 |
| 4 | 精度（同値性） | —（注3） | 最大差／マージン別一致率 | 実測 |
| 4' | 精度（形式違反率） | 自分の測定値（件数を書く） | 0%（構造的に起きない） | 実測＋構造 |
| 5 | オフライン耐性 | 0 件（回線断で全滅） | 全件 | 構成から自明 |
| 6 | プライバシー | 本文が全件端末外へ出る | 出ない | 実装の契約 |
| 7 | 運用の手間 | 1 回のデプロイで全員に反映 | {DEVICES:,} 台に配布（下限 {dist / 60:.1f} 分） | 式＋前提値 |

注1: 分類器は確率を一度に返すので「最初のトークン」が存在しない。
注2: 1 ÷ 定常 p50 から出した逐次実行の上限。端末が他の仕事もしていれば下がる。
     案Aの rps はサーバ全体の値で、**単位が違うものを同じ列に置いている**。
注3: 案Aには基準となる fp32 版が存在しないため、同値性の概念が当てはまらない。

## 3. 揃えられなかった条件と、差の内訳

  全体の比 = {b['total_ratio']:.1f} 倍（155 ms ÷ 0.29 ms。ともに 2026-08-15 実測）
    ① エッジであること : {b['edge_effect']:.1f} 倍
       （往復の物理下限 {b['rtt_floor_ms']:.2f} ms・距離 {b['distance_km']:.0f} km は前提値）
    ② タスクの切り出し : {b['task_effect']:.1f} 倍（0.5B ⇔ 18.37M）
    ③ 待ち行列         : 並列1 ではほぼ 0。並列4 なら +1,617 ms が乗る

② が支配的である。つまり「エッジに移したから速い」のではなく
「小さいモデルで足りる仕事を切り出したから速い」。

## 4. 測っていないこと

- 入力長を振っていない。長い問い合わせでのプリフィル時間は未測定
- 端末が他のアプリで混んでいる状態では測っていない
- 学習済みモデルでは測っていない（乱数重みの雛形である）
- 案Aの形式違反率は {len(REFERENCE_LABELS)} 件でしか測っていない
- 応答キャッシュを有効にした状態では測っていない
- 案Aを max_tokens=48 で測っていないので、セッション3・4 の表と同じ行に置けない
"""


def decision_md() -> str:
    rows = ["| # | 前提 | いまの値 | 変わったら |", "| --: | :--- | :--- | :--- |"]
    for i, (name, now, then) in enumerate(REVERSAL, start=1):
        rows.append(f"| {i} | {name} | {now} | {then} |")
    return f"""# 判断：問い合わせの一次分類をどこで解くか

## 1. 結論

**{DECISION}を採る。** エッジで一次判定し、マージンが
{CHOSEN_THRESHOLD:.2f} 未満の件だけクラウドへ回す。

## 2. 決め手になった軸（と、決め手にしなかった軸）

決め手（この順）: {" → ".join(DECIDERS)}

  1. オフライン耐性: 案A単独では回線断の時間帯に 0 件しか処理できない。
     案Bは全件処理できる。**これは他の軸で埋められない。**
  2. プライバシー: 本文を外に出せない部署がある。案Aは全件が端末外に出る。
  3. レイテンシ: 案Bが速い。ただし一次分類の SLO を 100 ms
     （セッション11 の前提値）とすると案Aでも間に合う可能性があるので、3 番目。

決め手にしなかった軸とその理由:
  - 単位コスト: 分岐点が {breakeven_requests():,.0f} 件で、件数の見積もりに依存しすぎる。
    見積もりが 2 倍ずれれば結論が変わる軸を、第一の理由にはできない。
  - スループット: どちらも要求（ピーク 2.0 rps・前提値）を満たす。差がつかない。
  - 精度: 本書のモデルは学習していない雛形なので、この演習では比較できない。
    **比較できない軸を決め手にしてはいけない。**

## 3. 却下した案の却下理由

| 案 | 却下理由 |
| :--- | :--- |
| 案A単独 | 回線断で 0 件。プライバシー要件を満たせない |
| 案B単独 | マージンが小さい件の判定を誰も検算できない |
| 言語モデルをエッジに載せる | セッション11・14 の結論。本章では検討対象外 |

## 4. 前提が変われば結論が変わる条件

{chr(10).join(rows)}

## 5. 次に測ると判断が変わりうること

1. 案Aを max_tokens=8 で実測する（本書の 1,034 ms は max_tokens=48 の値）
2. 端末が混んでいる状態でのエッジのレイテンシ
3. 長い問い合わせ（1,000 トークン級）でのプリフィル時間（案Aだけに効く）
4. 学習済みモデルでの参照ラベルとの一致率（案A・案B両方）
5. 応答キャッシュを有効にしたときの案Aの実効単価（ヒット率 h なら (1 − h) 倍）
"""


def hybrid_md() -> str:
    rows = ["| しきい値 | クラウドへ | エッジで | 送信率 | 1000件単価 | "
            "本文が出る件数 | 回線断でも処理 |",
            "| --: | --: | --: | --: | --: | --: | --: |"]
    for row in sweep(DEMO_MARGINS):
        rows.append(f"| {row['threshold']:.2f} | {row['to_cloud']} | "
                    f"{row['on_edge']} | {row['send_ratio']:.1%} | "
                    f"{row['cost_per_1k']:.4f} | {row['leaked_per_1k']:.0f} | "
                    f"{row['offline_ok_per_1k']:.0f} |")
    chosen = _chosen_row()
    return f"""# ハイブリッド案：エッジで一次判定し、確度の低いものだけクラウドへ

## 1. 振り分けの規則

  マージン（1位と2位の確率の差）が {CHOSEN_THRESHOLD:.2f} 未満の件だけクラウドへ送る。
  {CHOSEN_THRESHOLD:.2f} 以上はエッジで完結させ、本文を端末から出さない。

  **逆向きは作れない。** 案Aの確度は「区分に落とせた／落とせなかった」の
  2 値しかなく、しきい値で連続的に振り分けることができない。

## 2. しきい値を振ったときの感度

マージンは例示の固定値（実測ではない）。総件数 1,000,000 件・固定費
{EDGE_FIXED_COST:g}・クラウドの1000件単価 {cloud_cost_per_1k():.4f}（相対単位）。

{chr(10).join(rows)}

## 3. 選んだしきい値と理由

  {CHOSEN_THRESHOLD:.2f} を選んだ。送信率 {chosen['send_ratio']:.1%}、
  1000件単価 {chosen['cost_per_1k']:.4f}、本文が出る件数は 1000 件あたり
  {chosen['leaked_per_1k']:.0f} 件、回線断でも {chosen['offline_ok_per_1k']:.0f} 件を処理できる。
  0.05 では送信率がさらに下がるが、セッション12 の判定条件が
  「マージン 0.05 以上は全件一致」なので、**判定条件と同じ値をしきい値に
  するのは危険**である（境界の件が両側に落ちる）。1 段上から始める。

## 4. この案が成り立たなくなる条件

  - クラウド側のほうが正しいという前提が崩れたとき
  - マージンの分布が偏っているとき（ほぼ全件がしきい値未満なら送信率は
    100% に近づき、単価はクラウド単独より高くなる）
  - 回線が断のとき。マージン未満の件を**保留キューに積むか、既定の区分に
    落として人に回すか**を先に決めていないと、その件だけ静かに落ちる
"""


def risks_md() -> str:
    rows = ["| # | リスク | 起きる条件 | 検知方法 | 戻し方 |",
            "| --: | :--- | :--- | :--- | :--- |"]
    for i, (name, when, detect, revert) in enumerate(RISKS, start=1):
        rows.append(f"| {i} | {name} | {when} | {detect} | {revert} |")
    return f"""# 移行時のリスク一覧

{chr(10).join(rows)}

**モデルを段階的に配る仕組みと、失敗したときに戻す仕組みそのものの設計は
本章の範囲外。** セッション15 で扱う。ここでは検知方法と戻し方の**方針**
までを決めた。
"""


def documents() -> dict[str, str]:
    return {"01-implementations.md": implementations_md(),
            "02-comparison.md": comparison_md(),
            "03-decision.md": decision_md(),
            "04-hybrid.md": hybrid_md(),
            "05-risks.md": risks_md()}


def show_list() -> None:
    print(f"中間プロジェクト2の成果物（{len(DELIVERABLES)}点）")
    for i, (name, desc) in enumerate(DELIVERABLES, start=1):
        print(f"  {i}. {name:<21}  {desc}")


def write_all(out_dir: str) -> int:
    docs = documents()
    print("=== 中間プロジェクト2：意思決定の資料 ===")
    print(f"判断      : {DECISION}")
    print(f"決め手    : {' → '.join(DECIDERS)}")
    print(f"逆転条件  : {len(REVERSAL)} 件（総件数 "
          f"{breakeven_requests():,.0f} 件 / "
          + " / ".join(n for n, _, _ in REVERSAL[1:]) + "）")
    print(f"リスク    : {len(RISKS)} 件（全行に検知方法と戻し方あり）")

    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    for name, _ in DELIVERABLES:
        path = target / name
        path.write_text(docs[name], encoding="utf-8")
        print(f"-> {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="中間プロジェクト2の成果物")
    parser.add_argument("--list", action="store_true", help="成果物の一覧")
    parser.add_argument("--out", default=DEFAULT_OUT, help="書き出し先")
    args = parser.parse_args(argv)

    if args.list:
        show_list()
        return 0
    return write_all(args.out)


if __name__ == "__main__":
    sys.exit(main())
