#!/usr/bin/env python3
"""runbook の生成と検査（最終プロジェクト）。

    python src/final/runbook_final.py                          # 模範の runbook を表示
    python src/final/runbook_final.py --lint reports/final/06-runbook.md

中間プロジェクト1 の runbook（9項目）に、本章で2つ足す。

  8. モデル更新時の手順（配る前の門・段階展開・配った後の門）
  9. ロールバックの手順（**戻すのにかかる時間**を書く）

検査も2段にしてある。まず中間プロジェクト1 の `lint_runbook` を通し、そのうえで
本章の追加項目を見る。**エラー 0 件は「読める runbook」であることを保証しない。**
中身の質は人が読んで判断する。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SANDBOX = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SANDBOX))

from src.final.design import Design  # noqa: E402
from src.final.slo_alerts import objectives  # noqa: E402
from src.mid01.runbook import Finding, counts, lint_runbook, sections  # noqa: E402
from src.mid02.compare import MEASURED_CONDITIONS  # noqa: E402
from src.session15.fleet import (  # noqa: E402
    CLIENT_TIMEOUT_S, EQ_MAX_DIFF, EQ_MAX_DIFF_LIMIT, EQ_MARGIN,
    FAILURE_TOLERANCE, MIN_INFERENCES, FP32_MB, INT8_MB, transfer_seconds,
)

EXTRA_KEYS: tuple[tuple[str, str], ...] = (
    ("モデル更新", "モデル更新時の手順"),
    ("ロールバック", "ロールバックの手順"),
)
"""本章で足す2項目。見出しにこの語が含まれていればよい（表記の揺れは許す）。"""

VERDICTS = ("続行", "保留", "中止")
"""配った後の門は3値にする。2値にすると良い版を捨てるか悪い版を配る。"""

BANNED = ("様子を見る", "適宜", "都度判断", "追って連絡")
"""当番が読んでも動けない表現。**1つでもあれば手順として不成立。**"""

DURATION = re.compile(r"\d[\d,\.]*\s*(秒|分|時間)")


def lint_runbook_final(text: str) -> list[Finding]:
    """中間プロジェクト1 の検査に、本章の2項目と禁止語の検査を足す。"""
    findings = list(lint_runbook(text))
    found = sections(text)

    for key, label in EXTRA_KEYS:
        if not any(key in heading for heading in found):
            findings.append(Finding("error", f"必須の項目がありません: {label}"))

    body: list[str] = []
    for heading, lines in found.items():
        if "ロールバック" in heading:
            body = lines
            break
    if body and not DURATION.search("\n".join(body)):
        findings.append(Finding(
            "error", "ロールバックの節に「戻すのにかかる時間」がありません"))

    if not all(v in text for v in VERDICTS):
        missing = [v for v in VERDICTS if v not in text]
        findings.append(Finding(
            "error", "配った後の門が3値になっていません（欠け: "
            + " / ".join(missing) + "）"))

    for word in BANNED:
        if word in text:
            findings.append(Finding(
                "warn", f"当番が動けない表現があります: 「{word}」"))
    return findings


def runbook_markdown(design: Design | None = None) -> str:
    """成果物⑥（runbook）。数値は Design と SLO から引く。**手で書き写さない。**"""
    d = design or Design()
    objs = objectives(d)
    ttft, total = objs[1], objs[2]
    stages = d.stages
    stage_rows = "\n".join(
        f"| {s.index} | {s.added} | {s.seconds:,.1f} 秒 | {s.observe_hours:.0f} 時間 |"
        for s in stages)
    fp32_ratio = transfer_seconds(FP32_MB, d.devices, d.line_mbps) / d.distribution_seconds
    return f"""# runbook：{d.plan.title}

最終更新: 2026-08-15 / 対象: 本社の回答 API ＋ 工場の一次判定（端末 {d.devices:,} 台）
測定条件: {MEASURED_CONDITIONS} / Q4_K_M / -c {d.total_ctx} -np {d.slots} /
max_tokens={d.max_tokens} / 20 リクエスト

## 1. 対象と連絡先

| 項目 | 値 |
| :--- | :--- |
| サービス | 社内ヘルプデスク回答 API（本社）＋ 問い合わせの一次判定（工場） |
| 構成 | 端末 → 分類器 → （難しい件だけ）ゲートウェイ → 推論サーバ |
| 一次対応 | 情報システム部 当番（この runbook で完結させる） |
| オーナー | 情報システム部 基盤担当（恒久対応と展開の判断） |
| 対象時間 | 本社は営業日 9:00〜18:00 / 工場は 24 時間 |

## 2. SLO と測定方法

| 指標 | 目標値 | 測定 |
| :--- | :--- | :--- |
| {ttft.label} | {ttft.target} | {ttft.how} |
| {total.label} | {total.target} | 同上 |
| {objs[0].label} | {objs[0].target} | {objs[0].how} |
| {objs[3].label} | {objs[3].target} | {objs[3].how} |

- 判定: 20 件のうち 19 件目までが目標内なら達成。2 日連続で超えたら違反
- 確認: src/session04/sweep.py --label slo_check --concurrency {d.point.concurrency} --max-tokens {d.max_tokens} --prompts 20
- 完結率の下限は {d.completion_floor:.1%}。下回ると台数が {d.instances} → {d.instances + 1} 本になる

## 3. 現在の設定値

| 項目 | 値 | 出どころ |
| :--- | :--- | :--- |
| モデル（クラウド） | {d.model_file}（{d.plan.memory.weights_mib} MiB） | 03-load-capacity.md |
| 並列スロット -np / コンテキスト -c | {d.slots} / {d.total_ctx}（1スロット {d.plan.ctx_per_slot}） | 同上 |
| スレッド -t | 2（CPU 割り当てと同じ） | 同上 |
| インスタンス数 | {d.instances} 本（検証環境では 1 本） | 同上（**正典**） |
| メモリ要求 | {d.memory_per_instance}（requests と limits を同値） | 同上 |
| ゲートウェイ MAX_INFLIGHT | {d.slots}（上流のスロット数と同じ） | 02-implementation.md |
| ゲートウェイ RATE_LIMIT_RPS / BURST | 2 / 4 | 同上 |
| 待ち行列 | 上限 {d.slots} 件・期限 1,000 ms | 同上 |
| 応答キャッシュ | TTL 300 秒・キーに可視範囲（部署）を含める | 同上 |
| エッジのモデル | classifier_int8.onnx（{INT8_MB:.2f} MB） | 同上 |
| 振り分けのしきい値 | マージン {d.threshold:.2f}（送信率 {d.send_ratio:.1%}） | 01-architecture.md |

## 4. 検知（何を見るか）

| 見るもの | 正常 | 異常のしるし |
| :--- | :--- | :--- |
| inference_queue_length | 1本あたり 1.0 件未満 | 1.0 件以上が 5 分続く（飽和の入口） |
| inference_slot_utilization | 1.0 未満 | 1.0 が続く（スロットを使い切っている） |
| ゲートウェイのステータス内訳 | 200 が大半 | 429 が増える（相手が速い）／503 が増える（こちらが手一杯） |
| edge_completion_ratio | {d.completion_ratio:.1%} 前後 | {d.completion_floor:.1%} 未満が 1 日続く |
| 端末の版別分布 | 全台が同じ版 | 旧版が 5% を超えて 7 日続く |
| 端末の p95 のバケット | {objs[0].target} | 1段悪いバケットに落ちる |
| 端末のオフライン率 | 10% 前後 | 増え続ける（回線か端末の問題） |

## 5. 症状別の切り分け

| 症状 | 根拠の取り方 | 次にやること |
| :--- | :--- | :--- |
| 比較対象と条件が違う | max_tokens・モデル・-np・-c を突き合わせる | 条件を揃えて測り直す（ここで止まる） |
| 429 が出ている | ゲートウェイのステータス内訳 | そのキーの rate と burst の配分を見直す |
| 503 が出ている | 同上 | MAX_INFLIGHT と待ち行列の上限・期限を確認する |
| TTFT が目標超過・待ちが支配 | TTFT − 並列1 の TTFT が並列1 の TTFT より大きい | 同時実行を飽和点の手前まで下げる |
| TTFT が目標超過・待ちは小さい | 同じ引き算が小さい | 長すぎる入力を受け入れ判定で断る |
| TPOT が目標超過 | TPOT p50 が内部目標を超える | 本番構成で量子化を測り直す／出力上限を下げる |
| クラウドの件数が増えた | edge_completion_ratio | しきい値の変更とモデルの版を確認する（第8節へ） |
| 端末だけ遅い | 版別の p95 バケット | 新版だけなら第9節へ。全版なら端末の資源競合 |

切り分けの補助: src/review01/triage.py に観測値を渡すと、候補と根拠と次の手が表で返る。

## 6. 対処（暫定）

5 分以内にできること。**1 回に 1 つだけ実施し、実施時刻を記録する。**

1. MAX_INFLIGHT が {d.slots} かを確認する。違っていれば {d.slots} に直してゲートウェイを再起動する（3 分）
2. 応答キャッシュの TTL を 300 → 900 秒に延ばす（1 分）
3. 待ち行列の期限が 1,000 ms かを確認する（超過分は 503 で断る）（1 分）
4. しきい値を一段下げて送信率を落とす（エッジ側・5 分。**下げた値と時刻を記録する**）

推論サーバの再起動は暫定対応に含めない。重みのロードだけで 1,335.9 ms の見積りがあり、進行中のリクエストを全部切ることになる。

## 7. 対処（恒久）

次の営業日までにやること。オーナーが判断する。

1. src/review01/triage.py で支配要因を確定させる（10 分）
2. キュー待ちが支配的なら、03-load-capacity.md の数え方で台数を増やす（30 分）
3. デコードが支配的なら、-c {d.total_ctx} -np {d.slots} の条件で量子化を測り直す（2 時間）
4. 完結率が下がっているなら、モデルの版と入力の分布を点検する（半日）
5. 前提が変わっていたら 04-slo-alerts.md の見直し条件に照らして SLO を再検討する

## 8. モデル更新時の手順

**配る前の門**（1つでも外れたら配らない。理由は全部記録する）

1. 確率の最大差 ≦ {EQ_MAX_DIFF_LIMIT:.2f} か（前回の実測は {EQ_MAX_DIFF:.6f}）
2. マージン {EQ_MARGIN:.2f} 以上の件が全件一致するか
3. 入力次元 384 と出力 6 クラスが変わっていないか
4. 署名が検証できるか

**段階展開**（各段の観察は {stages[0].observe_hours:.0f} 時間）

| 段 | 台数 | この段の配布（下限） | 観察 |
| --: | --: | --: | --: |
{stage_rows}

- 全台への配布の下限: {d.distribution_seconds:,.1f} 秒（{d.distribution_seconds / 60:.1f} 分）
  ＝ {INT8_MB:.2f} MB × {d.devices:,} 台 ÷ {d.line_mbps:.1f} Mbps
- fp32 を配ると {fp32_ratio:.1f} 倍かかる（サイズ比の逆数）
- 同時ダウンロードの上限: {d.max_parallel_downloads} 台（タイムアウト {CLIENT_TIMEOUT_S:.0f} 秒）
- 所要（配布 ＋ 観察）: {d.rollout_hours:.1f} 時間（約 {d.rollout_hours / 24:.1f} 日）

**配った後の門**（各段の終わりに判定する。判定は3値）

1. 件数が {MIN_INFERENCES:,} 件未満 → 「保留」（観察を延ばす。**中止にしない**）
2. 新版の失敗率 > 現行版 × {FAILURE_TOLERANCE} → 「中止」（第9節へ）
3. どちらでもない → 「続行」（次の段へ）

件数の検査を先に置く理由: 3 件中1件失敗（33.3%）のような揺れた値で「中止」を出すと、良い版を捨てることになる。

## 9. ロールバックの手順（元に戻す）

1. 変更前の設定値を控えたメモ（第3節の表のコピー）を開く
2. クラウド側: 直前のイメージのダイジェスト（@sha256:）を指定して置き換える
   （maxUnavailable: 0 なので古い Pod は準備完了まで残る。{d.instances} 本なので {d.instances} 波）
3. エッジ側: 二面構成の「既知正常版」に切り替える（原子的な置き換え・再ダウンロード不要）
4. 新版の配布を止める（配布中に戻すと、戻した端末が再び新版を取る）
5. /health が 200 を返し、/slots の使用中が 0 に戻るのを確認する
6. 版別分布・失敗率・レイテンシのバケットが元の値に戻ったことを確認する
7. 戻した理由と時刻を第10節の記録に残す

**戻すのにかかる時間**: エッジ側は既知正常版への切り替えなので再ダウンロードが不要で、
指示が届いた端末はその場で戻る。一方「1つ前の版を配り直す」形にすると
{d.distribution_seconds:,.1f} 秒（{d.distribution_seconds / 60:.1f} 分）以上かかる。
**二面構成にしておくかどうかで復旧時間が桁で変わる。**

## 10. 記録すること

1. 発生時刻と検知の経路（アラート・日次確認・申告のどれか）
2. 測った数値と測定条件（条件のない数値は残さない）
3. 支配要因の判定と、その根拠になった計算
4. 実施した対処（1 回に 1 つ・実施時刻つき）
5. 対処の前後の測定結果（版別に分ける）
6. 未解決の宿題（測っていないこと）
"""


def lint_file(path: str) -> int:
    target = Path(path)
    print(f"=== {path} ===")
    if not target.exists():
        print("ファイルがありません。先に runbook を書いてください。")
        return 1
    findings = lint_runbook_final(target.read_text(encoding="utf-8"))
    for finding in findings:
        print(f"  {finding}")
    errors, warns = counts(findings)
    print(f"検出: エラー {errors} 件 / 警告 {warns} 件")
    if errors:
        print("エラーを 0 件にしてから提出してください。")
        return 1
    if warns:
        print("警告は理由が書けるなら残してよいものです。")
        return 0
    print("必須項目はすべて埋まっています。"
          "**読めるかどうかは人が判断します。**")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="runbook の生成と検査")
    parser.add_argument("--lint", help="runbook の必須項目を検査する")
    args = parser.parse_args(argv)

    if args.lint:
        return lint_file(args.lint)
    print(runbook_markdown(), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
