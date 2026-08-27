#!/usr/bin/env python3
"""中間プロジェクト1の自己検証。

検証するのは**計算と判定のロジック**であって、レイテンシの絶対値ではない。

- SLO の目標値を測った値から導けること（切り上げ・丸め・要件との突き合わせ）
- 超えたときの行動が無い SLO を作れないこと
- 動作点の選び方（SLO を満たす中での最大。rps の最大ではない）
- 総時間の目標から TPOT を割り付けられること
- 容量計画（1インスタンスの能力 → 必要本数 → メモリ要求）
- runbook の必須 9 項目の充足
- 成果物5点を書き出せること

第8節だけは推論サーバを使う。**絶対値は期待値にしていない**（環境ごとに変わる）。
確かめるのは「スロット数を超えると TTFT が悪化する」「切り上げた目標は測った値
以上になる」という関係である。SKIP_SERVER=1 で飛ばせる。
"""

from __future__ import annotations

import contextlib
import io
import os
import re
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.mid01.capacity import Demand, plan_for  # noqa: E402
from src.mid01.handover import DELIVERABLES, documents, write_all  # noqa: E402
from src.mid01.runbook import (  # noqa: E402
    REQUIRED_SECTIONS, counts, lint_runbook, runbook_markdown,
)
from src.mid01.slo import (  # noqa: E402
    DEFAULT_SLOS, MEASURED, REQUIREMENTS, Point, Requirement, Slo, derive_floor,
    enough_samples, operating_point, propose, satisfies, saturation_of,
    throughput_gain, total_ms_for, tpot_budget_ms,
)

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    mark = "OK " if cond else "NG "
    print(f"{mark} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def raises(fn) -> str:
    """例外のメッセージを返す（何も起きなければ空文字）。"""
    try:
        fn()
    except (ValueError, TypeError) as exc:
        return str(exc)
    return ""


def bail() -> None:
    if failures:
        print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
        sys.exit(1)


SKELETON = """# runbook：テスト用（目標値を書き忘れた例）

最終更新: 2026-08-15

## 1. 対象と連絡先
- 当番: 情報システム部
## 2. SLO と測定方法
- 目標: 速いこと
## 3. 現在の設定値
- -np 2
## 4. 検知（何を見るか）
- /health
## 5. 症状別の切り分け
| 症状 | 根拠 | 次にやること |
| :--- | :--- | :--- |
| 遅い | 測る | 同時実行を下げる |
## 6. 対処（暫定）
1. 入口を絞る
## 7. 対処（恒久）
1. インスタンスを増やす
## 8. 元に戻す手順
1. 設定を戻す
## 9. 記録すること
- 発生時刻
"""

# --- 1. SLO の目標値を導く --------------------------------------------------
print("=== 1. SLO の目標値を導く ===")
floor = derive_floor(100.0, margin=1.5, round_to=100)
check("測った p95 に余裕を掛けて切り上げる", floor == 200.0,
      f"100 ms × 1.5 = {100.0 * 1.5:.0f} → {floor:.0f} ms")
fine = derive_floor(100.0, margin=1.5, round_to=50)
check("丸め幅を変えると床が動く", fine == 150.0, f"50 ms 単位なら {fine:.0f} ms")
msg = raises(lambda: derive_floor(100.0, margin=0.9))
check("余裕の係数は 1.0 未満にできない",
      msg == "margin は 1.0 以上を指定してください", msg)
tight = propose(Requirement("最初の反応", "ttft", 1000.0, "前提値"), 900.0)
check("要件の天井を超える床は成立しない", not tight.feasible, tight.verdict)
fit = propose(REQUIREMENTS[0], 100.0)
check("天井の内側なら成立する", fit.feasible, fit.verdict)

# --- 2. SLO の形 ------------------------------------------------------------
print("\n=== 2. SLO の形 ===")
msg = raises(lambda: Slo(metric="ttft", quantile=95, target_ms=200.0,
                         label="TTFT p95", window="営業日", how="固定 20 件",
                         why="体感を決めるため", on_breach=()))
check("超えたときの行動が無い SLO は作れない",
      msg == "目標を超えたときにやることが1つも書かれていません", msg)
ttft_slo = DEFAULT_SLOS[0]
check("目標内なら達成、超えたら違反",
      ttft_slo.judge(150.0) and not ttft_slo.judge(250.0),
      "150 ms は達成 / 250 ms は違反")
check("p95 には 20 件必要", enough_samples(20, 95) and not enough_samples(19, 95),
      "19 件では出せない")
check("p99 には 100 件必要", enough_samples(100, 99) and not enough_samples(99, 99),
      "99 件では出せない")

# --- 3. 動作点を選ぶ --------------------------------------------------------
print("\n=== 3. 動作点を選ぶ ===")
gains = dict(throughput_gain(MEASURED))
check("実測の飽和点は並列 4", saturation_of(MEASURED) == 4,
      f"スループットの伸び {gains[4] * 100:.1f}% で TTFT が悪化")
adopted = operating_point(MEASURED, DEFAULT_SLOS)
check("採用する動作点は並列 2", adopted.concurrency == 2,
      f"{adopted.throughput_rps} rps（TTFT p95 {adopted.ttft_p95_ms:.0f} ms / "
      f"総時間 p95 {adopted.total_p95_ms:.0f} ms）")
over = [p for p in MEASURED if p.concurrency == 4][0]
check("並列 4 は SLO を満たさない", not satisfies(over, DEFAULT_SLOS),
      f"TTFT p95 {over.ttft_p95_ms:.0f} ms > {DEFAULT_SLOS[0].target_ms:.0f} ms")
strict = (replace(DEFAULT_SLOS[0], target_ms=150.0), DEFAULT_SLOS[1])
solo = [p for p in MEASURED if p.concurrency == 1][0]
check("目標を 150 ms にすると並列 1 が落ちる",
      not satisfies(solo, strict)
      and operating_point(MEASURED, strict).concurrency == 2,
      f"並列 1 の TTFT p95 は {solo.ttft_p95_ms:.0f} ms")
impossible = (replace(DEFAULT_SLOS[0], target_ms=50.0), DEFAULT_SLOS[1])
msg = raises(lambda: operating_point(MEASURED, impossible))
check("誰も満たさない目標は例外にする",
      msg == "SLO を満たす動作点がありません", msg)

# --- 4. TPOT の割り付け -----------------------------------------------------
print("\n=== 4. TPOT の割り付け ===")
ttft_target = DEFAULT_SLOS[0].target_ms
total_target = DEFAULT_SLOS[1].target_ms
tpot48 = tpot_budget_ms(total_target, ttft_target, 48)
check("総時間の目標から TPOT の目標を出す", abs(tpot48 - 63.83) < 0.01,
      f"({total_target:.0f} − {ttft_target:.0f}) ÷ 47 = {tpot48:.1f} ms"
      f"（実測 {adopted.tpot_p50_ms} ms）")
tpot128 = tpot_budget_ms(total_target, ttft_target, 128)
check("出力上限を上げると目標が厳しくなる", tpot128 < tpot48,
      f"128 トークンなら {tpot128:.1f} ms")
long_total = total_ms_for(ttft_target, adopted.tpot_p50_ms, 128)
check("出力上限 128 では総時間の目標を割る", long_total > total_target,
      f"{ttft_target:.0f} + {adopted.tpot_p50_ms} × 127 = {long_total:.0f} ms > "
      f"{total_target:.0f} ms")

# --- 5. 容量計画 ------------------------------------------------------------
print("\n=== 5. 容量計画 ===")
demand = Demand(peak_rps=2.0, baseline_rps=0.4)
plan = plan_for(demand, adopted, slots=2, total_ctx=2048, headroom=0.30)
check("1インスタンスの安全な rps", abs(plan.per_instance_rps - 0.791) < 1e-9,
      f"{adopted.throughput_rps} × (1 − {plan.headroom:.2f}) = "
      f"{plan.per_instance_rps:.2f} rps")
check("ピークに必要な本数は切り上げる", plan.peak_instances == 3,
      f"{demand.peak_rps:.2f} ÷ {plan.per_instance_rps:.2f} = "
      f"{demand.peak_rps / plan.per_instance_rps:.2f} → {plan.peak_instances} 本")
check("平常時に必要な本数", plan.baseline_instances == 1,
      f"{demand.baseline_rps:.2f} ÷ {plan.per_instance_rps:.2f} = "
      f"{demand.baseline_rps / plan.per_instance_rps:.2f} → "
      f"{plan.baseline_instances} 本")
check("メモリ要求は式から出す", plan.memory.quantity() == "768Mi",
      plan.memory.explain())
no_headroom = plan_for(demand, adopted, headroom=0.0)
check("ヘッドルームを 0 にすると本数が減る", no_headroom.peak_instances == 2,
      f"{plan.peak_instances} 本 → {no_headroom.peak_instances} 本")
bigger = plan_for(Demand(peak_rps=4.0, baseline_rps=0.4), adopted)
check("ピークが 2 倍になると本数が増える", bigger.peak_instances == 6,
      f"{plan.peak_instances} 本 → {bigger.peak_instances} 本")
msg = raises(lambda: plan_for(demand, adopted, headroom=1.0))
check("不正な入力は受け付けない",
      msg == "headroom は 0 以上 1 未満で指定してください", msg)

# --- 6. runbook の必須項目 --------------------------------------------------
print("\n=== 6. runbook の必須項目 ===")
book = runbook_markdown(plan)
errors, warns = counts(lint_runbook(book))
check("模範 runbook はエラー 0 件・警告 0 件", errors == 0 and warns == 0,
      f"必須 {len(REQUIRED_SECTIONS)} 項目すべて充足")
without_revert = "\n".join(x for x in book.splitlines() if "元に戻す" not in x)
msg = "; ".join(f.message for f in lint_runbook(without_revert)
                if f.level == "error")
check("「元に戻す手順」を削るとエラーになる",
      msg == "必須の項目がありません: 元に戻す手順", msg)
flat = re.sub(r"(?m)^\d+\. ", "- ", book)
msg = "; ".join(f.message for f in lint_runbook(flat) if f.level == "error")
check("手順が番号付きでないとエラーになる",
      msg == "「元に戻す手順」に番号付きの手順がありません", msg)
msg = "; ".join(f.message for f in lint_runbook(SKELETON) if f.level == "error")
check("SLO の節に目標値が無いとエラーになる",
      msg == "「SLO と測定方法」に目標値（数値 + ms）がありません", msg)

# --- 7. 成果物5点 -----------------------------------------------------------
print("\n=== 7. 成果物5点 ===")
names = [name for name, _ in DELIVERABLES]
check("成果物は5点そろっている",
      len(names) == 5 and set(names) == set(documents(plan)),
      " / ".join(names))
buffer = io.StringIO()
with tempfile.TemporaryDirectory() as tmp:
    with contextlib.redirect_stdout(buffer):
        code = write_all(tmp)
    written = sorted(p.name for p in Path(tmp).iterdir())
check("5点すべてを書き出せる", code == 0 and written == sorted(names),
      "一時ディレクトリに 5 ファイル")

# --- 8. 推論サーバでの確認 --------------------------------------------------
print("\n=== 8. 推論サーバでの確認（SKIP_SERVER=1 で飛ばせる）===")
if os.environ.get("SKIP_SERVER") == "1":
    print("SKIP_SERVER=1 のため推論サーバを使う検証を飛ばします。")
else:
    from infrakit.client import LlamaClient  # noqa: E402
    from infrakit.load import run_load  # noqa: E402
    from src.session04.sweep import server_conditions  # noqa: E402
    from tools.prompts import with_shared_prefix  # noqa: E402

    client = LlamaClient()
    alive = client.health()
    check("推論サーバに接続できる", alive,
          "" if alive else "docker compose up -d llama を実行してください")
    bail()

    cond = server_conditions(client)
    slots = int(cond["slots"] or 2)
    prompts = with_shared_prefix()[:6]
    low = run_load(client, prompts, concurrency=1, max_tokens=16,
                   label="mid01_c1", conditions=cond)
    high = run_load(client, prompts, concurrency=slots * 2, max_tokens=16,
                    label=f"mid01_c{slots * 2}", conditions=cond)
    check(f"並列 1 と並列 {slots * 2} をエラーなく測れた",
          low.errors == 0 and high.errors == 0,
          f"エラー {low.errors + high.errors} 件")
    bail()

    check("スロット数を超えると TTFT が悪化する",
          high.ttft["p50"] > low.ttft["p50"],
          f"{low.ttft['p50']:.0f}ms -> {high.ttft['p50']:.0f}ms")

    p95 = low.ttft["p95"]
    target = derive_floor(p95) if p95 > 0 else 0.0
    check("測った p95 から導いた目標はその p95 以上になる",
          p95 > 0 and target >= p95,
          f"目標 {target:.0f} ms ≧ 実測 {p95:.0f} ms")

    live = Point(concurrency=1, ttft_p50_ms=low.ttft["p50"], ttft_p95_ms=p95,
                 total_p50_ms=low.total["p50"], total_p95_ms=low.total["p95"],
                 tpot_p50_ms=low.tpot["p50"], throughput_tps=low.throughput_tps,
                 throughput_rps=low.throughput_rps, n=low.n)
    live_plan = plan_for(Demand(peak_rps=2.0, baseline_rps=0.4), live)
    check("導いた目標で容量計画が立つ", live_plan.peak_instances >= 1,
          f"{live_plan.peak_instances} 本")

# --- [9] 実測表の重複が食い違っていないか -----------------------------------
# mid01 の MEASURED は、章の独立性を保つため（S09 のオートスケール概念を
# 持ち込まないため）セッション9の POINTS と**別に定義**している。値が同じである
# ことは人の注意ではなく機械で担保する。requirements.md の実測表を改訂したら
# ここが落ちるので、両方直すことに気づける。
print("\n=== 9. 実測表の重複（mid01 と セッション9）===")
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "session09"))
    from scaling import POINTS as S09_POINTS  # type: ignore

    mine = [(p.concurrency, p.ttft_p50_ms, p.ttft_p95_ms, p.total_p50_ms,
             p.total_p95_ms, p.tpot_p50_ms, p.throughput_tps, p.throughput_rps)
            for p in MEASURED]
    theirs = [(p.concurrency, p.ttft_p50_ms, p.ttft_p95_ms, p.total_p50_ms,
               p.total_p95_ms, p.tpot_p50_ms, p.throughput_tps, p.throughput_rps)
              for p in S09_POINTS]
    check("mid01 の MEASURED とセッション9の POINTS が一致する", mine == theirs,
          f"{len(mine)} 点を比較（食い違ったら requirements.md の実測表を正として両方を直す）")
except ImportError as exc:
    check("セッション9の POINTS を読める", False, f"import できない: {exc}")

bail()
print("\n中間プロジェクト1の検証はすべて成功しました。")
