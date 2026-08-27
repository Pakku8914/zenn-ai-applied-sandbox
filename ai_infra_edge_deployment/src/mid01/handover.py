#!/usr/bin/env python3
"""引き継ぎ資料5点を書き出す CLI（中間プロジェクト1）。

    python src/mid01/handover.py --list                      # 成果物の一覧
    python src/mid01/handover.py --out reports/mid01_model    # 5点を書き出す
    python src/mid01/handover.py --lint reports/mid01/05-runbook.md

**書き出し先の既定は `reports/mid01_model/` である**（自分の答案を置く
`reports/mid01/` を上書きしないため）。

01・04・05 は SLO と容量計画のデータから組み立てる（前提を変えれば中身が変わる）。
02・03 は 2026-08-15 の測定に対する**記録そのもの**なので固定の文章である。
自分の環境で測ったら、この2つは自分の数値で書き直すこと。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.mid01.capacity import Demand, Plan, plan_for  # noqa: E402
from src.mid01.runbook import (  # noqa: E402
    REQUIRED_SECTIONS, counts, lint_runbook, runbook_markdown,
)
from src.mid01.slo import (  # noqa: E402
    DEFAULT_SLOS, MEASURED, MEASURED_CONDITIONS, operating_point, slo_document,
)

DEFAULT_OUT = "reports/mid01_model"

DELIVERABLES: tuple[tuple[str, str], ...] = (
    ("01-slo.md", "SLO 定義（指標・目標値・測定方法・超えたときの行動）"),
    ("02-load-report.md", "負荷試験レポート（測定条件つき）"),
    ("03-bottleneck.md", "ボトルネックの特定と対処の記録"),
    ("04-capacity.md", "容量計画（同時実行数と必要インスタンス数）"),
    ("05-runbook.md", "runbook（検知・切り分け・対処・元に戻す手順）"),
)

LOAD_REPORT = """# 負荷試験レポート：ヘルプデスク回答 API（初期構成）

## 1. 測定条件

測定日: 2026-08-15 / aarch64 / CPU 2コア / メモリ 5.8GB / Python 3.12.13 /
llama.cpp -t 2 / Q4_K_M（qwen05b-q4_k_m.gguf・379.4 MiB） /
-c 2048 -np 2（1スロット 1024 トークン） / max_tokens=48 / 温度 0 /
プロンプト 20 件（tools/prompts.py の共通接頭辞つき） / ウォームアップ 2 回

- 測定対象: 推論サーバに直接（ゲートウェイは経由しない）
- 再現コマンド: src/session04/sweep.py --label mid01_q4_np2 --concurrency 1 2 4 --max-tokens 48 --prompts 20
- 生データ: reports/sweep_mid01_q4_np2.json、reports/load_sweep_mid01_q4_np2_c{1,2,4}.json

## 2. 結果

### 2-1. 同時実行を振ったとき（上の条件・エラー 0 件）

| 並列 | TTFT p50 | TTFT p95 | TTFT max | 総時間 p50 | 総時間 p95 | TPOT p50 | スループット | rps |
| --: | --: | --: | --: | --: | --: | --: | --: | --: |
| 1 | 155 ms | 194 ms | 292 ms | 1,034 ms | 1,212 ms | 19.19 ms | 45.0 tok/s | 0.96 |
| 2 | 52 ms | 100 ms | 261 ms | 1,737 ms | 2,126 ms | 36.74 ms | 53.0 tok/s | 1.13 |
| 4 | 1,772 ms | 2,064 ms | 2,100 ms | 3,379 ms | 3,737 ms | 36.15 ms | 53.9 tok/s | 1.15 |

飽和点: 並列 4（判定条件: スループットの伸びが 10% 未満、かつ TTFT p50 が悪化）

### 2-2. 刻みを粗くした場合（別条件・比較不可）

max_tokens=24 / 8 リクエストで並列 1 と 4 だけを測ると、
並列 1 が TTFT p50 81 ms・52.0 tok/s、並列 4 が TTFT p50 633 ms・73.8 tok/s。
スループットが 41.9% 伸びて見えるため、飽和点は検出されない。

### 2-3. 量子化形式の比較（別条件: -c 1024 -np 1・並列 1・max_tokens=48・20 件）

| 形式 | サイズ | TTFT p50 | TTFT p95 | 総時間 p50 | TPOT p50 | スループット |
| :--- | --: | --: | --: | --: | --: | --: |
| f16 | 948.1 MiB | 124 ms | 174 ms | 1,353 ms | 26.54 ms | 30.0 tok/s |
| Q8_0 | 506.5 MiB | 61 ms | 82 ms | 730 ms | 14.63 ms | 63.0 tok/s |
| Q4_K_M | 379.4 MiB | 144 ms | 189 ms | 1,051 ms | 19.58 ms | 43.7 tok/s |

## 3. 読み取れる事実

1. スロット数（2）を超えて流すと、スループットは 53.0 → 53.9 tok/s（+1.7%）しか
   伸びないのに、TTFT p50 は 52 → 1,772 ms（34.1 倍）に悪化する。ここが飽和点。
2. 並列 1 → 2 ではスループットが 45.0 → 53.0 tok/s（+17.8%）伸びる。
   スロットを使い切るまでは連続バッチが効いている。
3. 並列 2 で TTFT が改善して見える（155 → 52 ms）が、総時間は
   1,034 → 1,737 ms（1.68 倍）に伸びている。TPOT が 19.19 → 36.74 ms（1.91 倍）に
   なっているためで、スロットを分け合うと 1 トークンあたりの生成が遅くなる。
4. 量子化はサイズが小さいほど速いわけではない。Q8_0 はサイズが Q4_K_M より
   33.5% 大きいが、スループットは 43.7 → 63.0 tok/s（1.44 倍）速い。
   f16 と比べると 2.1 倍である。

## 4. 読み取れないこと（測っていないこと）

- 量子化形式の比較は -c 1024 -np 1 の条件でしか測っていない。
  本番構成（-c 2048 -np 2）での比較は未測定。2-1 と 2-3 の数値を同じ表に
  並べてはいけない。
- ゲートウェイ経由の測定をしていないため、レート制限・応答キャッシュ・
  待ち行列の効果は含まれない。429 と 503 の件数はすべて 0 件だが、これは
  「入口を通っていない」ためであって「入口が正しい」ことの証明ではない。
- 入力長を振っていない。プロンプトは 20 件とも同程度の長さなので、
  長い入力（社内文書の貼り付けなど）でのプリフィル時間は未測定。
- 3 回測って中央値を採る規約に対し、今回は各条件 1 回のみ。絶対値のぶれ幅は
  この測定からは分からない（別日の測定では並列 1 の TTFT p50 が 88 ms だった）。
- 連続運転していない。1 時間流し続けたときのメモリ増加は未測定。
"""

BOTTLENECK = """# ボトルネックの特定と対処の記録：初期構成

## 1. 症状

測定条件は 02-load-report.md の 2-1 節と同じ（2026-08-15 / CPU 2コア /
メモリ 5.8GB / Q4_K_M / -c 2048 -np 2 / max_tokens=48 / 20 件）。

- 同時 4 リクエストで TTFT p50 が 1,772 ms（並列 1 の 11.4 倍）
- 同じ条件で総時間 p50 が 3,379 ms（並列 1 の 3.27 倍）
- 一方でスループットは 53.0 → 53.9 tok/s（+1.7%）しか増えていない
- エラーは 0 件。処理はすべて成功している（遅いだけ）

## 2. 切り分け

| 観点 | 判定 | 根拠 |
| :--- | :--- | :--- |
| キュー待ち | 支配的 | TTFT 1,772 − 基準 155 = 1,617 ms（TTFT の 91%） |
| プリフィル | 問題なし | 基準（並列 1）の TTFT p50 は 155 ms で目標内 |
| デコード | 悪化はあるが主因ではない | TPOT 19.19 → 36.74 ms（1.91 倍）。総時間の増分より小さい |
| 入口 | 関与なし | 429・503 が 0 件（サーバ直で測っており入口を通っていない） |

## 3. 判断の根拠

1. スループットが伸びずに待ち時間だけが伸びているので、サーバの処理能力の
   問題ではなく「入れすぎ」である。飽和点（並列 4）を超えた分は、計算されずに
   並んでいるだけになる。
2. キュー待ちの近似値には、同じプロンプト集・同じ max_tokens で並列 1 のときに
   測った TTFT を基準として使った。条件の違う値を引くと、プリフィルが遅い状態を
   待ちと誤診する。
3. TPOT の 1.91 倍は「スロットを分け合っている」ことの表れであり、
   これ自体は連続バッチの正常な挙動である。並列 2 と並列 4 の TPOT が
   36.74 ms と 36.15 ms でほぼ同じことから、スロット 2 本を使い切った時点で
   デコードの速度は決まっており、それ以上の同時実行は待ちに化けている。
4. CPU 使用率は判断に使っていない。デコードはメモリ帯域律速なので、
   飽和していても CPU 使用率は上がりきらないことがある。

## 4. 変えたこと（1回に1つ）

| # | 変更 | 変更前 | 変更後 | 変えた理由 |
| --: | :--- | --: | --: | :--- |
| 1 | ゲートウェイの MAX_INFLIGHT | 4 | 2 | 上流の並列スロット数に合わせる（入口が上流の2倍を流していた） |

同時に変えたものは無い。RATE_LIMIT_RPS と RATE_LIMIT_BURST は既定値
（2 / 4）のまま据え置き、キューは上限 2・期限 1,000 ms を新設した。

## 5. 変更後の状態

- サーバから見た同時実行は 2 以下に固定される。よって動作点は
  02-load-report.md 2-1 節の「並列 2」の行になる
  （TTFT p95 100 ms・総時間 p95 2,126 ms・1.13 rps）。
- 絞らない場合の動作点は「並列 4」の行（TTFT p95 2,064 ms）。
  入口の1つの数字で TTFT p95 が 20.6 倍変わる。
- 超過分は 503 + Retry-After で断る。断った件数はゲートウェイの
  ステータスコード内訳で記録する。
- ゲートウェイ経由での実測は未実施（宿題）。サーバ直の測定から
  動作点を読み替えているだけであることを明記する。

## 6. 採用／不採用の判断

| 候補 | 判断 | 理由 |
| :--- | :--- | :--- |
| A 入口の max_inflight を 2 に | 採用 | 症状（キュー待ち 91%）に直接効き、設定1つで戻せる |
| B 量子化を Q8_0 に | 条件付き保留 | 同条件では速いが本番構成で未測定。メモリ 768Mi → 896Mi |
| C -np を 4 に | 不採用 | 受けられる入力が 448 トークンに縮む。コンテキスト維持なら 832Mi 必要 |
| D 出力上限を下げる | 不採用 | 回答が途中で切れる。SLO ではなく品質の問題になる |
| E 応答キャッシュ | 次フェーズ以降 | キーに可視範囲を含める設計が先。ヒット率も未測定 |

宿題（次に測ること）:
1. -c 2048 -np 2 の条件で Q4_K_M と Q8_0 を比較する
2. ゲートウェイ経由で並列 4 を流し、200 / 429 / 503 の件数と 200 のレイテンシを測る
3. 長い入力（1,000 トークン級）でのプリフィル時間を測る
"""


def default_plan() -> Plan:
    """本書の実測と前提値から組み立てた計画（模範解答の入力）。"""
    return plan_for(Demand(peak_rps=2.0, baseline_rps=0.4),
                    operating_point(MEASURED, DEFAULT_SLOS),
                    slots=2, total_ctx=2048, headroom=0.30)


def documents(plan: Plan) -> dict[str, str]:
    """成果物5点の中身。キーはファイル名。"""
    return {
        "01-slo.md": slo_document(plan.point, DEFAULT_SLOS),
        "02-load-report.md": LOAD_REPORT,
        "03-bottleneck.md": BOTTLENECK,
        "04-capacity.md": plan.markdown(DEFAULT_SLOS),
        "05-runbook.md": runbook_markdown(plan, DEFAULT_SLOS),
    }


def show_list() -> None:
    print(f"中間プロジェクト1の成果物（{len(DELIVERABLES)}点）")
    for i, (name, desc) in enumerate(DELIVERABLES, start=1):
        print(f"  {i}. {name:<17} {desc}")


def write_all(out_dir: str) -> int:
    plan = default_plan()
    docs = documents(plan)
    findings = lint_runbook(docs["05-runbook.md"])
    errors, warns = counts(findings)

    p = plan.point
    print(f"=== {plan.title}：引き継ぎ資料 ===")
    print(f"測定条件: {MEASURED_CONDITIONS}")
    print(f"SLO     : {' / '.join(s.describe() for s in DEFAULT_SLOS)}")
    print(f"動作点  : 並列 {p.concurrency}（{p.throughput_rps} rps・"
          f"TTFT p95 {p.ttft_p95_ms:.0f} ms・総時間 p95 {p.total_p95_ms:.0f} ms）")
    print(f"容量    : 1インスタンス {plan.per_instance_rps:.2f} rps → "
          f"ピーク {plan.demand.peak_rps:.2f} rps に {plan.peak_instances} 本"
          f"（{plan.memory.quantity()}/本・合計 {plan.total_memory_mib}Mi）")
    status = (f"必須 {len(REQUIRED_SECTIONS)} 項目すべて充足"
              if not findings else "検査で指摘あり")
    print(f"runbook : {status}（エラー {errors} 件 / 警告 {warns} 件）")

    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    for name, _ in DELIVERABLES:
        path = target / name
        path.write_text(docs[name], encoding="utf-8")
        print(f"-> {path}")
    return 1 if errors else 0


def lint_file(path: str) -> int:
    target = Path(path)
    print(f"=== {path} ===")
    if not target.exists():
        print("ファイルがありません。先に runbook を書いてください。")
        return 1
    findings = lint_runbook(target.read_text(encoding="utf-8"))
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
    print("runbook の必須項目はすべて埋まっています。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="中間プロジェクト1の引き継ぎ資料")
    parser.add_argument("--list", action="store_true", help="成果物の一覧を表示する")
    parser.add_argument("--out", default=DEFAULT_OUT, help="書き出し先のディレクトリ")
    parser.add_argument("--lint", help="runbook の必須項目を検査する")
    args = parser.parse_args(argv)

    if args.list:
        show_list()
        return 0
    if args.lint:
        return lint_file(args.lint)
    return write_all(args.out)


if __name__ == "__main__":
    sys.exit(main())
