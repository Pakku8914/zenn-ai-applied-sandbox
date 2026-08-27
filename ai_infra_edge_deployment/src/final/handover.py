#!/usr/bin/env python3
"""成果物7点の生成と、文書間の整合検査（最終プロジェクト）。

    python src/final/handover.py --list                     # 成果物の一覧
    python src/final/handover.py --out reports/final_model   # 7点を書き出す
    python src/final/handover.py --check reports/final_model # 文書間の整合を検査

**書き出し先の既定は reports/final_model/ である**（自分の答案を置く
reports/final/ を上書きしないため）。

このファイルの中心は `cross_check` である。7つの文書には同じ数字が何度も出る
（台数を1つ直すと4か所が動く）。**正典を1つ決めて、他は引用にする**という
規律を、機械で検査できる形にしてある。人が目で追うのは無理である。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, replace
from pathlib import Path

SANDBOX = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SANDBOX))

from src.final.design import (  # noqa: E402
    DEVICES, Design, REQUESTS_PER_DEVICE_HOUR, TITLE, trace,
)
from src.final.runbook_final import runbook_markdown  # noqa: E402
from src.final.slo_alerts import markdown as slo_markdown  # noqa: E402
from src.mid01.slo import DEFAULT_SLOS, MEASURED, MEASURED_CONDITIONS  # noqa: E402
from src.session11.edge_budget import fits  # noqa: E402
from src.session15.fleet import INT8_MB  # noqa: E402
from src.session16.decision import (  # noqa: E402
    DEVICE_D, Inputs, OPTIONS, Scenario, WEIGHTS, gate_reasons, survivors,
    weighted_score,
)

ARCH = "01-architecture.md"
IMPL = "02-implementation.md"
CAPACITY = "03-load-capacity.md"
SLO = "04-slo-alerts.md"
COST = "05-cost.md"
RUNBOOK = "06-runbook.md"
DECISION = "07-decision.md"

DEFAULT_OUT = "reports/final_model"

DELIVERABLES: tuple[tuple[str, str], ...] = (
    (ARCH, "アーキテクチャ図と設計書（境界の契約つき）"),
    (IMPL, "実装メモ（5つの部品と、部品間で守る約束）"),
    (CAPACITY, "負荷試験と容量計画（測定条件つき）"),
    (SLO, "SLO とアラート設計（5要素すべて埋める）"),
    (COST, "コスト試算と損益分岐（相対単位）"),
    (RUNBOOK, "runbook（飽和時・モデル更新時・ロールバック）"),
    (DECISION, "意思決定文書（再判断のトリガーつき）"),
)

REQUIRED_SECTIONS: dict[str, tuple[str, ...]] = {
    ARCH: ("## 1. 構成図", "## 2. 部品の責務", "## 3. 境界の契約",
           "## 4. 却下した構成", "## 5. 前提値と実測値"),
    IMPL: ("## 1. 推論サーバ", "## 2. ゲートウェイ", "## 3. 応答キャッシュ",
           "## 4. メトリクス", "## 5. エッジ側", "## 6. 動かし方"),
    CAPACITY: ("## 1. 測定条件", "## 2. 結果", "## 3. 動作点",
               "## 4. 台数とメモリ", "## 5. マニフェスト",
               "## 6. 前提が変わったとき"),
    SLO: ("## 1. SLO", "## 2. 系としての SLO", "## 3. アラート",
          "## 4. 誤検知", "## 5. この SLO を見直す条件"),
    COST: ("## 1. 前提", "## 2. 単価", "## 3. 損益分岐", "## 4. 感度",
           "## 5. 打ち手"),
    RUNBOOK: tuple(f"## {i}." for i in range(1, 11)),
    DECISION: ("## 1. 前提", "## 2. 選択肢", "## 3. 評価軸と重み", "## 4. 数字",
               "## 5. 結論", "## 6. 再判断のトリガー",
               "## 7. 前提が変わったとき"),
}


# ---------------------------------------------------------------------------
# 文書間の整合検査
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Shared:
    """複数の文書に出る数字。**正典（source）を1つ決めるのが要点。**"""

    key: str
    value: str                 # 文書に現れるべき文字列（同じ書式で書く）
    source: str                # この数字の出どころの文書
    files: tuple[str, ...]     # この数字が現れるべき文書


def cross_check(docs: dict[str, str], shared: tuple[Shared, ...]) -> list[str]:
    """文書間の食い違いを探す。**空リストなら整合している。**

    「片方だけ古い」を検出するための検査である。値が見つからない文書を
    報告するだけで、正しい値を書き込んだりはしない（直すのは人の仕事で、
    直す順序は必ず「正典の文書 -> 引用側」である）。
    """
    findings: list[str] = []
    for item in shared:
        for name in item.files:
            text = docs.get(name)
            if text is None:
                findings.append(f"文書がありません: {name}（{item.key}）")
            elif item.value not in text:
                findings.append(
                    f"{name} に {item.key} の値 {item.value} がありません"
                    f"（正典: {item.source}）")
    return findings


def shared_values(design: Design | None = None) -> tuple[Shared, ...]:
    """7つの文書で共有する数字。**書式まで揃える**（1,000 と 1000 は別物）。"""
    d = design or Design()
    ttft, total = DEFAULT_SLOS[0], DEFAULT_SLOS[1]
    return (
        Shared("しきい値", f"{d.threshold:.2f}", ARCH, (ARCH, IMPL, DECISION)),
        Shared("送信率", f"{d.send_ratio:.1%}", ARCH,
               (ARCH, CAPACITY, COST, DECISION)),
        Shared("台数", f"{d.instances} 本", CAPACITY,
               (CAPACITY, COST, RUNBOOK)),
        Shared("メモリ / 本", d.memory_per_instance, CAPACITY,
               (CAPACITY, RUNBOOK)),
        Shared("TTFT p95 の目標", f"{ttft.target_ms:,.0f} ms", SLO,
               (SLO, RUNBOOK)),
        Shared("総時間 p95 の目標", f"{total.target_ms:,.0f} ms", SLO,
               (SLO, RUNBOOK)),
        Shared("系全体の1000件単価", f"{d.hybrid_cost_per_1k:.4f}", COST,
               (COST, DECISION)),
        Shared("損益分岐", f"{d.breakeven_requests:,.0f} 件", COST,
               (COST, DECISION)),
    )


def missing_sections(docs: dict[str, str]) -> list[str]:
    """必須の節が欠けている文書を報告する。"""
    findings: list[str] = []
    for name, markers in REQUIRED_SECTIONS.items():
        text = docs.get(name, "")
        for marker in markers:
            if marker not in text:
                findings.append(f"{name} に節がありません: {marker}")
    return findings


# ---------------------------------------------------------------------------
# 成果物①：アーキテクチャ図と設計書
# ---------------------------------------------------------------------------

ARCH_MERMAID = """```mermaid
flowchart LR
    D1["端末（工場・1,000 台）"] --> C1["ONNX int8 分類器"]
    C1 -->|"マージン >= しきい値：完結"| D1
    C1 -->|"マージン < しきい値：引き継ぎ"| G["ゲートウェイ"]
    U["本社・支店の利用者"] --> G
    G --> K["応答キャッシュ（可視範囲つき）"]
    K --> Q["待ち行列"]
    Q --> S["推論サーバ llama.cpp"]
    S --> M["メトリクス"]
    O["OTA 配布（二面構成）"] -.-> C1
    A["集約指標"] -.-> M
```"""

CONTRACTS: tuple[tuple[str, str, str], ...] = (
    ("端末 → 分類器", "384 次元のベクトル", "決定的（同じ文字列なら同じベクトル）"),
    ("分類器 → 端末", "区分 ID・確度・マージン",
     "必ず6クラスの確率が返る（形式違反が無い）"),
    ("端末 → ゲートウェイ", "問い合わせ本文＋部署（可視範囲）",
     "マージン < しきい値の件だけ。回線断なら保留キューへ"),
    ("ゲートウェイ → 推論サーバ", "プロンプト・max_tokens",
     "同時実行は上流のスロット数まで。超過分は 503 で断る"),
    ("推論サーバ → メトリクス", "/metrics の項目",
     "名前はアダプタ層で翻訳する（上流の名前に依存しない）"),
    ("配布元 → 端末", "署名つきモデル", "段階展開・二面構成・原子的な置き換え"),
)

RESPONSIBILITIES: tuple[tuple[str, str, str], ...] = (
    ("エッジの分類器", "区分 ID・確度・マージンを返す", "回答文の生成（載らない）"),
    ("エッジの振り分け", "しきい値で完結／引き継ぎ／保留を決める",
     "既定の区分に寄せること"),
    ("ゲートウェイ", "レート制限・同時実行の上限・キューの期限・キャッシュ・観測",
     "推論そのもの"),
    ("推論サーバ", "プリフィルとデコード", "入口の防御"),
    ("メトリクス", "名前の翻訳とヒストグラム", "判断（しきい値は SLO 側が持つ）"),
    ("OTA", "段階展開・二面構成・原子的な置き換え", "品質の判定（門が持つ）"),
)


def architecture_md(d: Design) -> str:
    llm = d.llm_footprint
    ok_d, margin_d = fits(DEVICES["端末D"], llm)
    resp = "\n".join(f"| {a} | {b} | {c} |" for a, b, c in RESPONSIBILITIES)
    contracts = "\n".join(f"| {a} | {b} | {c} |" for a, b, c in CONTRACTS)
    return f"""# 設計書：{TITLE}

作成 2026-08-15 / 作成者 インフラ課 / 次回棚卸し 3か月後

## 1. 構成図

{ARCH_MERMAID}

エッジで一次判定し、マージンがしきい値 {d.threshold:.2f} 未満の件だけを
クラウドへ引き継ぐ（送信率 {d.send_ratio:.1%}）。

## 2. 部品の責務（1部品1行）

| 部品 | 責務 | やらないこと |
| :--- | :--- | :--- |
{resp}

## 3. 境界の契約（何を渡し、何を守るか）

| 境界 | 渡すもの | 守る約束 |
| :--- | :--- | :--- |
{contracts}

**障害のときは、まずどの境界で止まっているかを決める。** 境界が決まれば
どちら側を直すかが決まり、runbook の切り分けに入れる。

## 4. 却下した構成と却下理由

| 構成 | 却下理由（数字で） |
| :--- | :--- |
| クラウドAPI 単独 | オフライン必須／生データを端末から出せない（ゲート2つ） |
| 自前ホスティング単独 | 同上 |
| 言語モデルを端末に置く | 0.5B Q4_K_M の占有 {llm.total_mb:.1f} MB > 端末D の上限 {DEVICES['端末D'].limit_mb:,.1f} MB（{-margin_d:.1f} MB 不足・{'収まる' if ok_d else '収まらない'}） |
| マイコン級に載せる | int8 の重み {INT8_MB * 1024:,.2f} KB > Flash の上限 563.20 KB（31.9 倍） |

**上限が {llm.total_mb:.1f} MB を超える端末に置き換わったら、3行目は再判断する。**

## 5. 前提値と実測値の一覧（出どころつき）

| 数字 | 種別 | 正典 |
| :--- | :--- | :--- |
| 動作点 {d.point.throughput_rps} rps・TTFT p95 {d.point.ttft_p95_ms:,.0f} ms・総時間 p95 {d.point.total_p95_ms:,.0f} ms | ①実測 | {CAPACITY} |
| 重み {d.plan.memory.weights_mib} MiB・KVキャッシュ {d.plan.memory.kv_mib:.1f} MiB | ①実測＋②物理計算 | {CAPACITY} |
| 台数 {d.instances} 本・メモリ {d.memory_per_instance} | 計算 | {CAPACITY} |
| 利用率 {d.utilization:.1%}・1000件単価 {d.cloud_cost_per_1k:.4f} | 計算 | {COST} |
| SLO の目標値 {DEFAULT_SLOS[0].target_ms:,.0f} ms / {DEFAULT_SLOS[1].target_ms:,.0f} ms | 計算 | {SLO} |
| ピーク {d.hq_peak_rps:.1f} rps・端末 {d.devices:,} 台・固定費 {d.edge_fixed_cost:g} | ③前提値 | {ARCH} |
| しきい値 {d.threshold:.2f}・送信率 {d.send_ratio:.1%} | ③前提値＋計算 | {ARCH} |

測定条件: {MEASURED_CONDITIONS}
"""


# ---------------------------------------------------------------------------
# 成果物②：実装メモ
# ---------------------------------------------------------------------------

METRICS: tuple[tuple[str, str, str, str], ...] = (
    ("inference_queue_length", "gauge", "スロットに載れず待っている件数",
     "llamacpp:requests_deferred"),
    ("inference_slot_utilization", "gauge", "使用中スロット ÷ 総スロット",
     "requests_processing から計算"),
    ("inference_gateway_rejected_total", "counter", "503 で断った件数",
     "ゲートウェイの /stats"),
    ("inference_gateway_cache_hits_total", "counter", "応答キャッシュのヒット件数",
     "同上"),
    ("edge_handoff_total", "counter", "**本章で追加**。引き継がれた件数",
     "ゲートウェイのラベル"),
    ("edge_completion_ratio", "gauge", "**本章で追加**。エッジで完結した割合",
     "端末の集約指標から計算"),
)


def implementation_md(d: Design) -> str:
    metrics = "\n".join(f"| `{a}` | {b} | {c} | {e} |" for a, b, c, e in METRICS)
    return f"""# 実装メモ：{TITLE}

## 1. 推論サーバ（設定値と、その根拠）

| 設定 | 値 | 根拠 |
| :--- | :--- | :--- |
| コンテキスト -c | {d.total_ctx} | 1スロット {d.plan.ctx_per_slot} トークン。コンテキストはスロット数で等分される |
| 並列スロット -np | {d.slots} | 動作点（並列 {d.point.concurrency}）と揃える |
| スレッド -t | 2 | CPU の割り当てと揃える。超えると切り替えの分だけ遅くなる |
| モデル | {d.model_file} | 既定のまま据え置き。**本番構成での量子化比較は未測定**（宿題） |

Q4_K_M を選んだ理由を「小さいから」にしてはいけない。セッション3の実測
（-c 1024 -np 1・並列1・max_tokens=48・20 件）では TPOT p50 が Q8_0 14.63 ms /
Q4_K_M 19.58 ms / f16 26.54 ms で、**より小さい Q4_K_M のほうが遅い**。

## 2. ゲートウェイ（入口の3つの上限）

| 上限 | 値 | 超えたときの応答 |
| :--- | :--- | :--- |
| レート（1キー） | RATE_LIMIT_RPS=2 / BURST=4 | 429（あなたが速すぎる） |
| 同時実行 | MAX_INFLIGHT={d.slots} | 503（こちらが手一杯） |
| 待ち行列の期限 | 上限 {d.slots} 件・1,000 ms | 503 ＋ Retry-After |

MAX_INFLIGHT を上流のスロット数と揃える理由: 入口の1つの数字で TTFT p95 が
20.6 倍変わる（並列2 の 100 ms と並列4 の 2,064 ms・2026-08-15 実測）。

## 3. 応答キャッシュ（キーに何を含めるか）

- 含める: プロンプト本文 / モデルの識別 / max_tokens などの生成条件 / **可視範囲（部署）**
- 含めない: 時刻・リクエストID（含めると必ずミスになる）
- 可視範囲を含めないと、工場の問い合わせに対する回答が別部署に返る
  （セッション6で再現した事故）。ヒット率の前提は {d.cache_hit_rate:.1%}

## 4. メトリクス（名前と、上流の名前からの翻訳）

| 本章の名前 | 種別 | 意味 | 上流の候補 |
| :--- | :--- | :--- | :--- |
{metrics}

- 上流の名前が変わってもアダプタ層だけを直せばよい（セッション10）
- ヒストグラムの境界は SLO から決め、**あとから変えない**（過去と合成できなくなる）
- 端末からはパーセンタイルではなく**件数**で受け取る（分位は足せない）

## 5. エッジ側（特徴量化・モデル・振り分け）

- 特徴量化: 文字 2-gram の符号付きハッシュ 384 次元・L2 正規化（決定的）
- モデル: classifier_int8.onnx（{INT8_MB:.2f} MB・fp32 の 25.0%）
- 占有: 重み {INT8_MB:.2f} ＋ KVキャッシュ 0.00 ＋ 実行時 50.0 = {d.edge_footprint.total_mb:.2f} MB
  （端末D の上限 {DEVICES['端末D'].limit_mb:,.1f} MB に収まる）
- 振り分け: マージン >= {d.threshold:.2f} は完結、未満はクラウドへ、
  **回線断のときは保留キューへ**（既定の区分に寄せない）
- スレッド数はコア数付近が最速。コア数を超えても速くならず、ばらつきが増える

## 6. 動かし方（誰の環境でも同じ手順）

1. docker compose up -d
2. docker compose exec app python src/mid02/edge_side.py --threads 1 2
3. docker compose exec app python src/final/design.py
4. docker compose exec app python src/final/handover.py --out reports/final
5. docker compose exec app python src/final/handover.py --check reports/final
"""


# ---------------------------------------------------------------------------
# 成果物③：負荷試験と容量計画
# ---------------------------------------------------------------------------


def capacity_md(d: Design) -> str:
    rows = "\n".join(
        f"| {p.concurrency} | {p.ttft_p50_ms:,.0f} ms | {p.ttft_p95_ms:,.0f} ms | "
        f"{p.total_p95_ms:,.0f} ms | {p.tpot_p50_ms} ms | {p.throughput_tps} tok/s | "
        f"{p.throughput_rps} |"
        for p in sorted(MEASURED, key=lambda x: x.concurrency))
    m = d.plan.memory
    return f"""# 負荷試験と容量計画：{TITLE}

## 1. 測定条件（これが無い数値は比較できない）

{MEASURED_CONDITIONS} / Q4_K_M / -c {d.total_ctx} -np {d.slots} /
max_tokens={d.max_tokens} / 温度 0 / 固定プロンプト 20 件 / ウォームアップ 2 回 /
測定対象は推論サーバに直接（ゲートウェイは経由しない）

引き継がれた件の分類は max_tokens=8 で呼ぶ。**この2つを同じ行に置かない。**

## 2. 結果（p50・p95・スループット）

| 並列 | TTFT p50 | TTFT p95 | 総時間 p95 | TPOT p50 | スループット | rps |
| --: | --: | --: | --: | --: | --: | --: |
{rows}

読み取れる事実:

1. スロット数（{d.slots}）を超えると、スループットは 53.0 → 53.9 tok/s（+1.7%）しか
   伸びないのに TTFT p50 は 52 → 1,772 ms（34.1 倍）に悪化する。ここが飽和点
2. 並列2 で TPOT が並列1 の約1.9倍（19.19 → 36.74 ms）になる。TTFT が改善して
   見えるのに総時間が伸びる理由がこれ

測っていないこと: 入力長を振っていない / ゲートウェイ経由で測っていない /
本番構成での量子化比較をしていない / 連続運転していない

## 3. 動作点（実測から選んだ点と、その理由）

並列 {d.point.concurrency}（{d.point.throughput_rps} rps・TTFT p95 {d.point.ttft_p95_ms:,.0f} ms・
総時間 p95 {d.point.total_p95_ms:,.0f} ms）。**SLO を満たす中で最も rps が高い点**であって、
rps が最大の点ではない（並列4 は rps 1.15 だが TTFT p95 が目標の 10 倍以上）。

## 4. 台数とメモリの数え方

| 段 | 計算 | 結果 |
| :--- | :--- | --: |
| クラウドへ回る件数 | {d.edge_requests_per_month:,.0f} × {d.send_ratio:.3f}（送信率 {d.send_ratio:.1%}） | {d.cloud_requests_per_month:,.0f} 件/月 |
| キャッシュ後 | × (1 − {d.cache_hit_rate:.2f}) | {d.cloud_requests_after_cache:,.0f} 件/月 |
| エッジ由来の平均 | ÷ 2,592,000 秒 | {d.edge_avg_rps:.4f} rps |
| エッジ由来のピーク | × {d.peak_factor:.1f}（前提値・未実測） | {d.edge_avg_rps * d.peak_factor:.3f} rps |
| 合計ピーク | 本社 {d.hq_peak_rps:.1f} ＋ 上の値 | {d.peak_rps:.3f} rps |
| 1本の能力 | {d.point.throughput_rps} × (1 − {d.headroom:.2f}) | {d.per_instance_rps:.3f} rps |
| ピークに必要な本数 | {d.peak_rps:.3f} ÷ {d.per_instance_rps:.3f} = {d.peak_rps / d.per_instance_rps:.2f}（切り上げ） | **{d.instances} 本** |
| 同時実行の合計 | {d.instances} 本 × {d.slots} スロット | {d.instances * d.slots} |
| メモリ / 本 | {d.plan.memory_formula()}（64 MiB 単位で切り上げ） | **{d.memory_per_instance}** |
| メモリ合計 | {d.instances} 本 × {d.plan.memory_per_instance_mib} MiB | {d.total_memory_mib:,} MiB |

- 切り上げの理由: {d.peak_rps / d.per_instance_rps:.2f} 本を {d.instances - 1} 本に切り下げると、ピーク時に必ず飽和する
- ヘッドルーム {d.headroom:.0%} の理由: 実測 {d.point.throughput_rps} rps は理想条件の値。入力長のばらつき、
  ロールアウト中に1本抜ける状況、測定自体のぶれ（同一条件で2倍程度）を吸収する余白
- KVキャッシュ {m.kv_mib:.1f} MiB の内訳: 12,288 バイト/トークン × {d.total_ctx:,} トークン
- **検証環境との差**: 本書の検証環境はメモリ 5.8GB・CPU 2コアで、{d.instances} 本は計画上の数字。
  演習では1本しか立てない

## 5. マニフェストに反映する値

| 対象 | 値 | 根拠 |
| :--- | :--- | :--- |
| replicas | {d.instances} | {d.peak_rps:.3f} ÷ {d.per_instance_rps:.3f} の切り上げ |
| requests.memory / limits.memory | {d.memory_per_instance}（同値） | {d.plan.memory_formula()} |
| requests.cpu / limits.cpu | 2 | -t 2 と揃える |
| コンテナ引数 -c / -np | {d.total_ctx} / {d.slots} | 1スロット {d.plan.ctx_per_slot}。動作点は並列 {d.point.concurrency} |
| maxUnavailable / maxSurge | 0 / 1 | 古い Pod を落とさない。{d.instances} 波で置き換わる |
| terminationGracePeriodSeconds | 60 | preStop 15 ＋ 生成の最長 {d.plan.max_request_s:.1f} ＋ 余裕 5 = {d.plan.grace_required_s:.1f} 秒に収まる |
| HPA の指標 | inference_queue_length（1本あたり 1.0 件） | CPU 使用率では飽和が見えない |
| HPA の minReplicas / maxReplicas | 2 / {d.instances + 1} | 可用性の下限は 2。上は1本ぶんの余裕 |

検査: `python src/session08/lint_manifest.py --explain` と
`python src/session09/lint_hpa.py`（クラスタは立てない）。

## 6. 前提が変わったときの再計算手順

1. src/session04/sweep.py で同時実行を振って測り直す（1・スロット数・2倍以上）
2. SLO を満たす中で最も rps が高い点を動作点に採る
3. src/final/design.py の Design の該当フィールドを直す
4. python src/final/design.py で台数・メモリ・単価を出し直す
5. python src/final/handover.py --out reports/final で7点を再生成する
6. python src/final/handover.py --check reports/final で整合を確認する
7. マニフェストを直し、lint_manifest.py と lint_hpa.py を通す
"""


# ---------------------------------------------------------------------------
# 成果物⑤：コスト試算と損益分岐
# ---------------------------------------------------------------------------

LEVERS: tuple[tuple[str, str, str], ...] = (
    ("利用率を上げる", "単価は利用率に反比例する（10% と 90% で 9 倍）",
     "上限は 70%（ヘッドルーム 30%）"),
    ("停止スケジュール", "本社は営業時間（週 60 時間）だけ必要。夜間は1本で足りる",
     "起動に時間がかかる（重みのロードだけで 1,335.9 ms の見積り）"),
    ("応答キャッシュ", "ヒット率がそのままクラウドの件数を減らす",
     "キーに可視範囲を含める。ヒット率は測る"),
    ("しきい値を下げる", "送信率が下がりクラウドの件数が減る",
     "クラウド側の検算が減る（品質とのトレードオフ）"),
    ("量子化を測り直す", "1本の能力が上がれば台数が減る",
     "Q8_0 はメモリ要求が 768Mi → 896Mi に上がる"),
)


def cost_md(d: Design) -> str:
    rows = "\n".join(
        f"| {r['threshold']:.2f} | {r['send_ratio']:.1%} | {r['instances']} | "
        f"{r['utilization']:.1%} | {r['cloud_cost']:.4f} | {r['hybrid_cost']:.4f} |"
        for r in trace(d))
    levers = "\n".join(f"| {a} | {b} | {c} |" for a, b, c in LEVERS)
    peak4 = replace(d, peak_factor=4.0)
    peak5 = replace(d, peak_factor=5.0)
    below = replace(d, send_ratio=0.31)
    above = replace(d, send_ratio=0.33)
    return f"""# コスト試算と損益分岐：{TITLE}

**金額は書かない。** インスタンス1時間の値段を {d.hourly_cost:g} と置いた
相対単位で計算する。自分の契約の値を入れると自分の通貨の答えになる。

## 1. 前提（相対単位・利用率・件数）

| 入力 | 値 | 種別 |
| :--- | --: | :--- |
| 一次判定の月間件数 | {d.edge_requests_per_month:,.0f} 件 | ③前提値 |
| 送信率 | {d.send_ratio:.1%} | しきい値 {d.threshold:.2f} から |
| 応答キャッシュのヒット率 | {d.cache_hit_rate:.1%} | ③前提値 |
| 台数 | {d.instances} 本 | {CAPACITY} が正典 |
| 1本の rps（動作点） | {d.point.throughput_rps} rps | ①実測 |
| 利用率 | {d.utilization:.1%} | 平均 {d.avg_rps:.4f} ÷ 能力 {d.instances * d.point.throughput_rps:.2f} |
| エッジの固定費 | {d.edge_fixed_cost:g} | ③前提値（配布・検証・仕組み作り） |

## 2. 単価（クラウド／エッジ／ハイブリッド）

| 対象 | 1000件単価 | 性質 |
| :--- | --: | :--- |
| クラウド | {d.cloud_cost_per_1k:.4f} | 件数に依存しない。**利用率に反比例する** |
| エッジ | {d.edge_cost_per_1k:.4f} | 件数に反比例する（固定費 ÷ 件数） |
| 系全体（ハイブリッド） | {d.hybrid_cost_per_1k:.4f} | エッジ ＋ 送信率 × クラウド |

計算式:

- クラウド: ({d.hourly_cost:g} × {d.instances}) ÷ ({d.avg_rps:.4f} × 3600) × 1000 = {d.cloud_cost_per_1k:.4f}
- エッジ: {d.edge_fixed_cost:g} ÷ {d.edge_requests_per_month:,.0f} × 1000 = {d.edge_cost_per_1k:.4f}
- 系全体: {d.edge_cost_per_1k:.4f} ＋ {d.send_ratio:.3f} × {d.cloud_cost_per_1k:.4f} = {d.hybrid_cost_per_1k:.4f}

**中間プロジェクト2 の 0.3512 と値が違う理由**: 式は同じで、利用率の前提が違う。
あちらは 0.700、こちらは {d.utilization:.3f}。{d.cloud_cost_per_1k:.4f} ÷ 0.3512 = 5.18 で、
0.700 ÷ {d.utilization:.3f} = 5.18 と一致する（単価は利用率に反比例する）。
**同じ式で前提が違うときは、必ず比で検算する。**

## 3. 損益分岐と、いまの位置

```text
損益分岐 = エッジの固定費 ÷ クラウドの1リクエスト単価
         = {d.edge_fixed_cost:g} ÷ {d.cloud_cost_per_1k / 1000.0:.8f}
         = {d.breakeven_requests:,.0f} 件
```

月間 {d.edge_requests_per_month:,.0f} 件は分岐点の
**{d.edge_requests_per_month / d.breakeven_requests:.1f} 倍**。固定費は月初の数日で回収できる。
だから**コストは決め手にならない**（桁で離れている）。

分岐点が動く条件: 固定費が2倍なら分岐点も2倍 / クラウドの単価が下がると分岐点は上がる。

## 4. 感度（どの前提が結論を動かすか）

| 動かす前提 | 変えた値 | 合計ピーク | 台数 |
| :--- | --: | --: | --: |
| （現状） | ピーク倍率 {d.peak_factor:.1f} | {d.peak_rps:.3f} rps | {d.instances} 本 |
| ピーク倍率 | 4.0 | {peak4.peak_rps:.3f} rps | {peak4.instances} 本 |
| ピーク倍率 | 5.0 | {peak5.peak_rps:.3f} rps | {peak5.instances} 本 |
| 送信率 | 31.0% | {below.peak_rps:.3f} rps | {below.instances} 本 |
| 送信率 | 33.0% | {above.peak_rps:.3f} rps | {above.instances} 本 |

**台数を決めているのは本社のピーク {d.hq_peak_rps:.1f} rps である。** エッジ由来は
{d.edge_avg_rps * d.peak_factor:.3f} rps（合計の {d.edge_avg_rps * d.peak_factor / d.peak_rps:.1%}）しかないので、
ピーク倍率（未実測）を 5.0 にしても台数は変わらない。**未実測の前提が結論を
動かさないと分かったので、測る優先度は下げてよい。**

逆に送信率は台数を動かす。上限は
({d.instances} × {d.per_instance_rps:.3f} − {d.hq_peak_rps:.1f}) ÷ {d.peak_per_send_ratio:.4f} =
**{d.send_ratio_limit:.1%}**。いまのピークは能力 {d.capacity_rps:.3f} rps の {d.peak_headroom_ratio:.1%}。

しきい値を振ったときの単価:

| しきい値 | 送信率 | 台数 | 利用率 | クラウド単価 | 系全体の単価 |
| --: | --: | --: | --: | --: | --: |
{rows}

- 系全体の単価は単調に増える
- **クラウド単価は単調ではない**（台数が1本増える段で跳ねる）
- **送信率を下げるとクラウド単価は上がる**（台数は本社のピークで決まっていて、
  利用率だけが下がるため）。部分最適と全体最適が逆を向く

## 5. 打ち手（利用率・停止スケジュール・キャッシュ）

| 打ち手 | 効き方 | 注意 |
| :--- | :--- | :--- |
{levers}
"""


# ---------------------------------------------------------------------------
# 成果物⑦：意思決定文書
# ---------------------------------------------------------------------------


def scenario_of(d: Design) -> Scenario:
    """セッション16 のゲートと採点表に、この基盤の前提を入れる。"""
    return Scenario(
        "final", TITLE, Inputs(monthly_requests=d.edge_requests_per_month),
        offline_required=True, raw_data_may_leave=False, slo_ms=d.edge_slo_ms,
        distance_km=d.distance_km, model_class="classifier",
        device_name="端末D", device=DEVICE_D, staff=3, api_priced=False,
        payload_bytes=384 * 4, per_hour=REQUESTS_PER_DEVICE_HOUR,
        devices=d.devices, send_ratio=d.send_ratio)


DECIDERS: tuple[tuple[str, str], ...] = (
    ("タスクの網羅性",
     "回答文の生成はクラウド側にしか置けない（0.5B が端末D に載らない）"),
    ("オフライン耐性とプライバシー",
     "一次判定が端末で完結するので、回線断でも大半が処理でき、本文はごく一部しか出ない"),
    ("品質の検算",
     "マージンが小さい件をクラウドに回すことで、エッジの判定を検算する経路が残る"),
)


def decision_md(d: Design) -> str:
    sc = scenario_of(d)
    gates = "\n".join(
        f"| {o} | {'通過' if not gate_reasons(sc, o) else '失格'} | "
        + ("ゲートをすべて通過" if not gate_reasons(sc, o)
           else "／".join(gate_reasons(sc, o))) + " |"
        for o in OPTIONS)
    alive = survivors(sc)
    scores = "\n".join(
        f"| {o} | " + " | ".join(f"{weighted_score(sc, o, w):.2f}" for w in WEIGHTS)
        + " |" for o in alive)
    deciders = "\n".join(f"{i}. **{name}**：{why}"
                         for i, (name, why) in enumerate(DECIDERS, start=1))
    tops = [max(alive, key=lambda o: weighted_score(sc, o, w)) for w in WEIGHTS]
    flipped = len(set(tops)) > 1
    return f"""# 意思決定：どこで推論するか（{TITLE}）

作成 2026-08-15 / 作成者 インフラ課 / 次回棚卸し 3か月後

## 1. 前提

測定条件: {MEASURED_CONDITIONS}
**金額はすべて相対単位**（インスタンス1時間の値段を {d.hourly_cost:g} と置く）。

| 入力 | 値 | 種別 |
| :--- | --: | :--- |
| 一次判定の月間件数 | {d.edge_requests_per_month:,.0f} 件 | ③前提値 |
| しきい値 / 送信率 | {d.threshold:.2f} / {d.send_ratio:.1%} | ③前提値＋計算 |
| 本社のピーク | {d.hq_peak_rps:.1f} rps | ③前提値 |
| 一次応答の SLO | {d.edge_slo_ms:.0f} ms | 要件 |
| 対象端末 | 端末D（上限 {DEVICES['端末D'].limit_mb:,.1f} MB） | ③前提値 |
| 往復の物理下限 | {d.rtt_ms:.2f} ms（距離 {d.distance_km:.0f} km） | ②物理計算 |

## 2. 選択肢とゲート判定

| 案 | 判定 | 理由（全部書く） |
| :--- | :--- | :--- |
{gates}

## 3. 評価軸と重み

ゲート4軸（オフライン耐性・プライバシー・レイテンシ・モデルの大きさ）＋
重み付け4軸（単価・運用負荷・スケールの上限・障害の切り分けやすさ）。
重みは要件から決め、**案を見てから決めない**。

| 案 | {' | '.join(f'{w.key}（{w.name}）' for w in WEIGHTS)} |
| :--- | {' | '.join('--:' for _ in WEIGHTS)} |
{scores}

{'**重みで1位が入れ替わった。**' if flipped else '**どの重みでも1位が同じ。**'}
これは「スコアで決めてはいけない」ことの証拠であり、同時に
**採点表に足りない軸**を見つける手がかりでもある。足りない軸は
「タスクの網羅性」で、エッジ単独では回答文の生成ができない
（0.5B の占有 {d.llm_footprint.total_mb:.1f} MB > 端末D の上限 {DEVICES['端末D'].limit_mb:,.1f} MB）。
**そもそも依頼を満たしていない案が、採点表では1位になりうる。**

## 4. 数字

- 系全体の1000件単価 {d.hybrid_cost_per_1k:.4f}（クラウド {d.cloud_cost_per_1k:.4f} ＋ エッジ {d.edge_cost_per_1k:.4f}）
- 損益分岐 {d.breakeven_requests:,.0f} 件。月間件数はその {d.edge_requests_per_month / d.breakeven_requests:.1f} 倍
- 台数 {d.instances} 本・メモリ合計 {d.total_memory_mib:,} MiB・利用率 {d.utilization:.1%}
- 送信率の上限 {d.send_ratio_limit:.1%}（超えると台数が {d.instances + 1} 本になる）
- 全台への配布の下限 {d.distribution_seconds:,.1f} 秒（同時ダウンロード上限 {d.max_parallel_downloads} 台）

## 5. 結論

**ハイブリッド（エッジ主・しきい値 {d.threshold:.2f}）を採る。** 決め手になった軸は次の3つで、
**総合点は根拠にしていない**。

{deciders}

コスト（1000件単価 {d.hybrid_cost_per_1k:.4f}・損益分岐の {d.edge_requests_per_month / d.breakeven_requests:.1f} 倍上）は
決め手にしていない。分岐点から桁で離れていて、どちらを選んでも結論が変わらないため。

## 6. 再判断のトリガー

| # | 指標 | しきい値 | 観測期間 | アクション | 担当 |
| :-- | :--- | :--- | :--- | :--- | :--- |
| 1 | 送信率（完結率の裏） | {d.send_ratio_limit:.1%} を超える | 1 か月 | 台数を {d.instances + 1} 本に増やす前に、しきい値とモデルを点検する | インフラ課 |
| 2 | 本社のピーク rps | {d.capacity_rps:.3f} rps を超える | 2 週間 | 容量計画から数え直す（台数を決めている前提はここ） | インフラ課 |
| 3 | 月間の一次判定件数 | {d.breakeven_requests:,.0f} 件を下回る | 2 か月 | エッジの固定費が回収できない。クラウド単独を再試算する | インフラ課 |
| 4 | 端末の資源 | 上限が {d.llm_footprint.total_mb:.1f} MB を超える端末に置き換わる | 随時 | 端末で回答生成まで完結させる案を再検討する | インフラ課 |
| 5 | プライバシー要件 | 本文の社外送信が許可される | 随時 | 最も硬いゲートが消えるので全体を再判断する | インフラ課 |

**しきい値はすべて計算から出ている。** {d.send_ratio_limit:.1%} は
({d.instances} × {d.per_instance_rps:.3f} − {d.hq_peak_rps:.1f}) ÷ {d.peak_per_send_ratio:.4f}、
{d.capacity_rps:.3f} rps は {d.instances} × {d.per_instance_rps:.3f}、
{d.breakeven_requests:,.0f} 件は {d.edge_fixed_cost:g} ÷ {d.cloud_cost_per_1k / 1000.0:.8f}、
{d.llm_footprint.total_mb:.1f} MB は {d.plan.memory.weights_mib} ＋ {d.llm_footprint.kv_mb:.1f} ＋ 150.0 である。

## 7. 前提が変わったときの再計算手順

1. src/final/design.py の Design を直す（1か所）
2. python src/final/design.py で連鎖を出し直す
3. python src/final/handover.py --out reports/final で7点を再生成する
4. python src/final/handover.py --check reports/final で整合を確認する
5. 逆転条件が変わったら、第6節のしきい値を書き換える
"""


# ---------------------------------------------------------------------------
# 生成・検査・CLI
# ---------------------------------------------------------------------------


def documents(design: Design | None = None) -> dict[str, str]:
    """成果物7点。**すべて1つの Design から生成される。**"""
    d = design or Design()
    return {ARCH: architecture_md(d), IMPL: implementation_md(d),
            CAPACITY: capacity_md(d), SLO: slo_markdown(d), COST: cost_md(d),
            RUNBOOK: runbook_markdown(d), DECISION: decision_md(d)}


def show_list() -> None:
    print(f"最終プロジェクトの成果物（{len(DELIVERABLES)}点）")
    for i, (name, desc) in enumerate(DELIVERABLES, start=1):
        print(f"  {i}. {name:<21} {desc}")


def write_all(out_dir: str, design: Design | None = None) -> int:
    d = design or Design()
    docs = documents(d)
    missing = missing_sections(docs)

    print(f"=== {TITLE}：引き継ぎ資料 ===")
    print(f"しきい値 / 送信率: {d.threshold:.2f} / {d.send_ratio:.1%}")
    print(f"台数 / メモリ    : {d.instances} 本 / {d.memory_per_instance}"
          f"（合計 {d.total_memory_mib:,} MiB）")
    print(f"単価 / 損益分岐  : {d.hybrid_cost_per_1k:.4f} / "
          f"{d.breakeven_requests:,.0f} 件")
    print(f"必須の節         : "
          + ("すべて埋まっている" if not missing else f"欠落 {len(missing)} 件"))

    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    for name, _ in DELIVERABLES:
        path = target / name
        path.write_text(docs[name], encoding="utf-8")
        print(f"-> {path}")
    for item in missing:
        print(f"  [エラー] {item}")
    return 1 if missing else 0


def check_dir(out_dir: str, design: Design | None = None) -> int:
    d = design or Design()
    target = Path(out_dir)
    docs: dict[str, str] = {}
    for name, _ in DELIVERABLES:
        path = target / name
        if path.exists():
            docs[name] = path.read_text(encoding="utf-8")

    shared = shared_values(d)
    print(f"=== 文書間の整合検査（{out_dir}）===")
    print("| 数字 | 値 | 正典 | 現れるべき文書 |")
    print("| :--- | :--- | :--- | :--- |")
    for item in shared:
        print(f"| {item.key} | {item.value} | {item.source} | "
              + " / ".join(name[:2] for name in item.files) + " |")
    print()

    findings = cross_check(docs, shared) + missing_sections(docs)
    if not findings:
        print(f"整合しています（{len(shared)} 件の共有値・食い違い 0 件）")
        return 0
    for finding in findings:
        print(f"  [不整合] {finding}")
    print(f"\n不整合 {len(findings)} 件。**正典の文書を直してから引用側を直す。**")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="最終プロジェクトの成果物7点")
    parser.add_argument("--list", action="store_true", help="成果物の一覧")
    parser.add_argument("--out", default=DEFAULT_OUT, help="書き出し先")
    parser.add_argument("--check", help="文書間の整合を検査するディレクトリ")
    args = parser.parse_args(argv)

    if args.list:
        show_list()
        return 0
    if args.check:
        return check_dir(args.check)
    return write_all(args.out)


if __name__ == "__main__":
    sys.exit(main())
