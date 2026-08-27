#!/usr/bin/env python3
"""runbook の生成と必須項目の検査（中間プロジェクト1）。

runbook は「当番が、作った人に連絡できない状況で読むもの」である。したがって
検査するのは文章の巧拙ではなく、**判断に必要な項目が埋まっているか**だけである。

    必須 9 項目 : 対象と連絡先 / SLO と測定方法 / 現在の設定値 / 検知 /
                  症状別の切り分け / 対処（暫定）/ 対処（恒久）/
                  元に戻す手順 / 記録すること

エラーがあれば呼び出し側が非0で終了できるよう、検出結果を返すだけにしてある
（`handover.py --lint` が終了コードにする）。**エラー 0 件は「読める runbook」で
あることを保証しない。** 中身の質は人が読んで判断する。
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.session08.budget import Assumptions  # noqa: E402
from src.mid01.capacity import Plan  # noqa: E402
from src.mid01.slo import (  # noqa: E402
    DEFAULT_SLOS, MAX_TOKENS, REQUIREMENTS, Slo, tpot_budget_ms,
)

HEADING = re.compile(r"^#{1,6}\s+(.*)$")
NUMBERED = re.compile(r"^\s*\d+\.\s+\S")
TARGET_MS = re.compile(r"\d[\d,]*\s*ms")
DATE = re.compile(r"20\d\d-\d\d-\d\d")


@dataclass(frozen=True)
class Section:
    """必須項目1つぶん。`key` が見出しに含まれていればよい（表記の揺れを許す）。"""

    key: str
    label: str


REQUIRED_SECTIONS: tuple[Section, ...] = (
    Section("対象と連絡先", "対象と連絡先"),
    Section("SLO", "SLO と測定方法"),
    Section("設定値", "現在の設定値"),
    Section("検知", "検知（何を見るか）"),
    Section("切り分け", "症状別の切り分け"),
    Section("暫定", "対処（暫定）"),
    Section("恒久", "対処（恒久）"),
    Section("元に戻す", "元に戻す手順"),
    Section("記録", "記録すること"),
)


@dataclass(frozen=True)
class Finding:
    """検出1件。エラーは直す、警告は理由が書けるなら残してよい。"""

    level: str
    message: str

    def __str__(self) -> str:
        mark = "エラー" if self.level == "error" else "警告"
        return f"[{mark}] {self.message}"


def sections(text: str) -> dict[str, list[str]]:
    """見出し -> その見出しの下にある行、に分解する。"""
    found: dict[str, list[str]] = {}
    current = ""
    for line in text.splitlines():
        m = HEADING.match(line)
        if m:
            current = m.group(1).strip()
            found[current] = []
            continue
        if current:
            found[current].append(line)
    return found


def _body_of(found: dict[str, list[str]], key: str) -> list[str] | None:
    for heading, lines in found.items():
        if key in heading:
            return lines
    return None


def lint_runbook(text: str) -> list[Finding]:
    """runbook を検査する。返り値が空なら必須項目はすべて埋まっている。"""
    found = sections(text)
    findings: list[Finding] = []

    for section in REQUIRED_SECTIONS:
        if _body_of(found, section.key) is None:
            findings.append(Finding("error",
                                    f"必須の項目がありません: {section.label}"))

    revert = _body_of(found, "元に戻す")
    if revert is not None and not any(NUMBERED.match(x) for x in revert):
        findings.append(Finding(
            "error", "「元に戻す手順」に番号付きの手順がありません"))

    slo = _body_of(found, "SLO")
    if slo is not None and not any(TARGET_MS.search(x) for x in slo):
        findings.append(Finding(
            "error", "「SLO と測定方法」に目標値（数値 + ms）がありません"))

    triage = _body_of(found, "切り分け")
    if triage is not None and not any(x.lstrip().startswith("|") for x in triage):
        findings.append(Finding(
            "warn", "「症状別の切り分け」に表がありません"
            "（症状・根拠・次にやることの表を書いてください）"))

    if not DATE.search(text):
        findings.append(Finding(
            "warn", "測定条件の日付（YYYY-MM-DD）が書かれていません"))

    return findings


def counts(findings: list[Finding]) -> tuple[int, int]:
    """(エラー件数, 警告件数)。"""
    errors = sum(1 for f in findings if f.level == "error")
    return errors, len(findings) - errors


# ---------------------------------------------------------------------------
# 成果物⑤ runbook
# ---------------------------------------------------------------------------


def runbook_markdown(plan: Plan, slos: tuple[Slo, ...] = DEFAULT_SLOS,
                     max_tokens: int = MAX_TOKENS) -> str:
    """引き継げる形（Markdown）の runbook。

    数値は容量計画と SLO から引く。**手で書き写さない**（片方だけ古くなる）。
    """
    ttft, total = slos[0], slos[1]
    ttft_req, total_req = REQUIREMENTS[0], REQUIREMENTS[1]
    tpot = tpot_budget_ms(total.target_ms, ttft.target_ms, max_tokens)
    load_ms = plan.memory.weights_mib / Assumptions().disk_read_mbps * 1000.0
    return f"""# runbook：{plan.title}

最終更新: 2026-08-15
測定条件: 2026-08-15 実測 / aarch64 / CPU 2コア / メモリ 5.8GB / Python 3.12.13 /
llama.cpp -t 2 / Q4_K_M / -c {plan.total_ctx} -np {plan.slots} / max_tokens={max_tokens} / 20 リクエスト

## 1. 対象と連絡先

| 項目 | 値 |
| :--- | :--- |
| サービス | 社内ヘルプデスク回答 API |
| 構成 | 利用者 → ゲートウェイ（FastAPI）→ 推論サーバ（llama.cpp・CPU） |
| 一次対応 | 情報システム部 当番（この runbook で完結させる） |
| オーナー | 情報システム部 基盤担当（恒久対応の判断） |
| 対象時間 | {ttft.window} |

## 2. SLO と測定方法

| 指標 | 目標値 | 測定 |
| :--- | --: | :--- |
| TTFT の p95 | {ttft.target_ms:,.0f} ms 以内 | 固定プロンプト 20 件・出力 {max_tokens} トークン・並列 {plan.point.concurrency} |
| 総時間の p95 | {total.target_ms:,.0f} ms 以内 | 同上 |

- 判定: 20 件のうち 19 件目までが目標内なら達成。2 日連続で超えたら違反。
- 確認: src/session04/sweep.py --label slo_check --concurrency {plan.point.concurrency} --max-tokens {max_tokens} --prompts 20
- 要件の天井は TTFT {ttft_req.ceiling_ms:,.0f} ms / 総時間 {total_req.ceiling_ms:,.0f} ms。余裕が薄いのは総時間（{total_req.ceiling_ms / total.target_ms:.2f} 倍）。

## 3. 現在の設定値

| 項目 | 値 |
| :--- | :--- |
| モデル | {plan.model_file}（{plan.memory.weights_mib} MiB） |
| 並列スロット -np | {plan.slots} |
| コンテキスト -c | {plan.total_ctx}（1スロット {plan.ctx_per_slot}） |
| スレッド -t | 2（CPU 割り当てと同じ） |
| 出力上限 | {max_tokens} トークン |
| ゲートウェイ MAX_INFLIGHT | {plan.slots} |
| ゲートウェイ RATE_LIMIT_RPS / BURST | 2 / 4 |
| 待ち行列 | 上限 {plan.slots} 件・期限 1,000 ms |
| メモリ要求 | {plan.memory.quantity()}（requests と limits を同値） |
| インスタンス数 | {plan.peak_instances}（計画）／検証環境では 1 |

## 4. 検知（何を見るか）

| 見るもの | 正常 | 異常のしるし |
| :--- | :--- | :--- |
| /health | 200 | 200 以外ならロード中か起動失敗 |
| /slots | 使用中が {plan.slots} 以下 | {plan.slots} 本とも使用中が続く（飽和の入口） |
| ゲートウェイのステータス内訳 | 200 が大半 | 429 が増える（相手が速い）／503 が増える（こちらが手一杯） |
| 朝の SLO 確認 | 目標内 | 2 日連続で超過 |
| 利用者からの申告 | なし | 「遅い」の申告（数値が無いので必ず自分で測る） |

常時監視の仕組み（メトリクス収集とダッシュボード）はこの時点では未整備。
当番は上の 5 つを手で確認する。申告だけで設定を変えないこと。

## 5. 症状別の切り分け

| 症状 | 根拠の取り方 | 次にやること |
| :--- | :--- | :--- |
| 比較対象と条件が違う | max_tokens・モデル・-np・-c を突き合わせる | 条件を揃えて測り直す（ここで止まる） |
| 429 が出ている | ゲートウェイのステータス内訳 | そのキーの rate と burst の配分を見直す |
| 503 が出ている | 同上 | MAX_INFLIGHT と待ち行列の上限・期限を確認する |
| TTFT が目標超過・待ちが支配 | TTFT − 並列 1 の TTFT が並列 1 の TTFT より大きい | 同時実行を飽和点の手前まで下げる（-np を上げるのは最後） |
| TTFT が目標超過・待ちは小さい | 同じ引き算が小さい | 入力の長さを削るか、長すぎる入力を断る |
| TPOT が目標超過 | TPOT p50 > {tpot:.1f} ms | 量子化を -c {plan.total_ctx} -np {plan.slots} の条件で測り直す／出力上限を下げる |
| どれも目標内 | 測り直しても目標内 | 何もしない。条件つきの記録を残す |

切り分けの補助: src/review01/triage.py に観測値を渡すと、候補と根拠と
次の手が表で返る。

## 6. 対処（暫定）

5 分以内にできること。**1 回に 1 つだけ実施し、実施時刻を記録する。**

1. MAX_INFLIGHT が {plan.slots} かを確認する。4 以上なら {plan.slots} に直してゲートウェイを再起動する（3 分）
2. 応答キャッシュの TTL を 300 → 900 秒に延ばす（1 分）
3. 待ち行列の期限が 1,000 ms かを確認する（超過分は 503 で断る）（1 分）

推論サーバの再起動は暫定対応に含めない。重みのロードだけで {load_ms:,.1f} ms の
見積りがあり、進行中のリクエストを全部切ることになる。

## 7. 対処（恒久）

次の営業日までにやること。オーナーが判断する。

1. src/review01/triage.py で支配要因を確定させる（10 分）
2. キュー待ちが支配的なら、04-capacity.md の数え方でインスタンスを増やす（30 分）
3. デコードが支配的なら、-c {plan.total_ctx} -np {plan.slots} の条件で量子化を測り直す（2 時間）
4. プリフィルが支配的なら、受け入れ判定で長すぎる入力を断る（1 時間）
5. 前提が変わっていたら 01-slo.md の見直し条件に照らして SLO を再検討する

## 8. 元に戻す手順

1. 変更前の設定値を控えたメモ（第 3 節の表のコピー）を開く
2. ゲートウェイの環境変数を変更前の値に戻し、docker compose up -d gateway を実行する
3. 推論サーバの設定を戻す場合は .env の MODEL_FILE・CTX・SLOTS を戻し、
   docker compose up -d llama を実行する
4. Kubernetes 上では、直前のイメージのダイジェストを指定して置き換える
   （maxUnavailable: 0 なので古い Pod は準備完了まで残る）
5. /health が 200 を返し、/slots の使用中が 0 に戻るのを確認する
6. 並列 {plan.point.concurrency} で 20 件測り、SLO の目標内に戻ったことを確認する
7. 戻した理由と時刻を第 9 節の記録に残す

## 9. 記録すること

対応が終わったら、次の 6 点を残す。次の当番が同じ調査を繰り返さないための記録である。

1. 発生時刻と検知の経路（申告・朝の確認・ステータス内訳のどれか）
2. 測った数値と測定条件（条件のない数値は残さない）
3. 支配要因の判定と、その根拠になった計算
4. 実施した対処（1 回に 1 つ・実施時刻つき）
5. 対処の前後の測定結果
6. 未解決の宿題（測っていないこと）
"""


__all__ = ["REQUIRED_SECTIONS", "Finding", "Section", "counts", "lint_runbook",
           "runbook_markdown", "sections"]
