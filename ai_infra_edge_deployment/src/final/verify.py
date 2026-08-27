#!/usr/bin/env python3
"""最終プロジェクトの自己検証。

    python src/final/verify.py
    SKIP_SERVER=1 python src/final/verify.py

検証するのは**決定的な性質だけ**である。レイテンシの絶対値は1つも期待値に
書いていない（同じ環境でも実行ごとに2倍程度ぶれるため）。逆に、前提値から
計算で出るもの（台数・メモリ・単価・配布時間・逆転点）は誰の環境でも同じ値に
なるので、そこは値まで検証する。この線引きが本書の作法である。

**通ったことは、答案が引き継げることの証明にはならない。** 文書が読めるか
どうかは人が判断する。ここで確かめているのは計算と判定のロジックだけである。

外部ネットワークには一切触らない。推論サーバを使う節は SKIP_SERVER=1 で飛ばせる。
"""

from __future__ import annotations

import contextlib
import io
import math
import os
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.final.handover import (  # noqa: E402
    CAPACITY, DELIVERABLES, cross_check, documents, missing_sections,
    shared_values, write_all,
)
from src.final.design import (  # noqa: E402
    DEVICES, Design, HANDOFF_CLOUD, HANDOFF_EDGE, HANDOFF_QUEUE, PRESTOP_S,
    REQUESTS_PER_DEVICE_HOUR, SECONDS_PER_MONTH, design_for, handoff, trace,
)
from src.final.runbook_final import (  # noqa: E402
    BANNED, VERDICTS, lint_runbook_final, runbook_markdown,
)
from src.final.slo_alerts import Alert, Objective, alerts, objectives  # noqa: E402
from src.mid01.runbook import counts  # noqa: E402
from src.mid02.hybrid import DEMO_MARGINS, route  # noqa: E402
from src.session11.edge_budget import fits  # noqa: E402
from src.session15.fleet import (  # noqa: E402
    CLIENT_TIMEOUT_S, EQ_MAX_DIFF, FP32_MB, INT8_MB, fleet_totals,
    quantile_bucket, release_gate, rollout_gate, sample_fleet,
    transfer_seconds, version_mix,
)

failures: list[str] = []
checked = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global checked
    checked += 1
    print(f"{'OK' if cond else 'NG'} {label}" + (f" — {detail}" if detail else ""))
    if not cond:
        failures.append(label)


def bail() -> None:
    if failures:
        print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
        sys.exit(1)


D = Design()

# --- 1. 前提 ----------------------------------------------------------------
print("=== 1. 前提（③前提値）===")
derived = D.devices * REQUESTS_PER_DEVICE_HOUR * 24 * 30
check("月間件数は端末数 × 件数/時 × 24h × 30日",
      abs(derived - D.edge_requests_per_month) < 1e-6,
      f"{D.devices:,} × {REQUESTS_PER_DEVICE_HOUR:g} × 24 × 30 = "
      f"{D.edge_requests_per_month:,.0f} 件")
check(f"しきい値 {D.threshold:.2f} の送信率は {D.send_ratio:.1%}",
      abs(design_for(D.threshold).send_ratio - D.send_ratio) < 1e-12,
      f"例示のマージン {len(DEMO_MARGINS)} 件のうち "
      f"{route(DEMO_MARGINS, D.threshold).to_cloud} 件")
check("1か月は 30 日として数える", SECONDS_PER_MONTH == 30 * 24 * 3600,
      f"{SECONDS_PER_MONTH:,} 秒")

# --- 2. 連鎖 ----------------------------------------------------------------
print("\n=== 2. 連鎖 ===")
check("クラウドへ回る件数",
      abs(D.cloud_requests_per_month
          - D.edge_requests_per_month * D.send_ratio) < 1e-6,
      f"{D.edge_requests_per_month:,.0f} × {D.send_ratio:.3f} = "
      f"{D.cloud_requests_per_month:,.0f} 件/月")
check("応答キャッシュを引くと件数が減る",
      D.cloud_requests_after_cache < D.cloud_requests_per_month,
      f"{D.cloud_requests_per_month:,.0f} -> "
      f"{D.cloud_requests_after_cache:,.0f} 件/月")
check("合計ピークは本社ぶんとエッジ由来の和",
      abs(D.peak_rps - (D.hq_peak_rps + D.edge_avg_rps * D.peak_factor)) < 1e-12,
      f"{D.hq_peak_rps:.3f} + {D.edge_avg_rps * D.peak_factor:.3f} = "
      f"{D.peak_rps:.3f} rps")
check("台数は切り上げ",
      D.instances == math.ceil(D.peak_rps / D.per_instance_rps),
      f"{D.peak_rps:.3f} ÷ {D.per_instance_rps:.3f} = "
      f"{D.peak_rps / D.per_instance_rps:.2f} -> {D.instances} 本")
check("メモリは (重み + KV) × 1.20 + 256 を 64MiB 単位で切り上げ",
      D.memory_per_instance == "768Mi" and D.total_memory_mib == 2304,
      f"{D.plan.memory.required_mib:.1f} MiB -> {D.memory_per_instance}"
      f"（合計 {D.total_memory_mib:,} MiB）")
check("単価は台数 ÷ (平均 rps × 3600) × 1000",
      abs(D.cloud_cost_per_1k
          - D.hourly_cost * D.instances / (D.avg_rps * 3600) * 1000) < 1e-6,
      f"({D.hourly_cost:g} × {D.instances}) ÷ ({D.avg_rps:.4f} × 3600) × 1000 = "
      f"{D.cloud_cost_per_1k:.4f}")
check("エッジの単価は件数に反比例する",
      abs(replace(D, edge_requests_per_month=D.edge_requests_per_month * 2)
          .edge_cost_per_1k - D.edge_cost_per_1k / 2) < 1e-12,
      f"{D.edge_cost_per_1k:.4f} -> 件数2倍で半分")
check("系全体の単価はエッジ + 送信率 × クラウド",
      abs(D.hybrid_cost_per_1k
          - (D.edge_cost_per_1k + D.send_ratio * D.cloud_cost_per_1k)) < 1e-12,
      f"{D.edge_cost_per_1k:.4f} + {D.send_ratio:.3f} × "
      f"{D.cloud_cost_per_1k:.4f} = {D.hybrid_cost_per_1k:.4f}")
check("分岐点ではエッジとクラウドの単価が一致する",
      abs(replace(D, edge_requests_per_month=D.breakeven_requests)
          .edge_cost_per_1k - D.cloud_cost_per_1k) < 1e-9,
      f"{D.breakeven_requests:,.0f} 件（いまの件数はその "
      f"{D.edge_requests_per_month / D.breakeven_requests:.1f} 倍）")
check("固定費を2倍にすると分岐点も2倍",
      abs(replace(D, edge_fixed_cost=D.edge_fixed_cost * 2).breakeven_requests
          - 2 * D.breakeven_requests) < 1e-6,
      f"{D.breakeven_requests:,.0f} 件 -> "
      f"{replace(D, edge_fixed_cost=200.0).breakeven_requests:,.0f} 件")

# --- 3. しきい値を振ったときの向き ------------------------------------------
print("\n=== 3. しきい値を振ったときの向き ===")
rows = trace(D)
ratios = [r["send_ratio"] for r in rows]
counts_ins = [r["instances"] for r in rows]
hybrid = [r["hybrid_cost"] for r in rows]
cloud = [r["cloud_cost"] for r in rows]
check("送信率は単調に増える",
      all(a <= b for a, b in zip(ratios, ratios[1:])),
      f"{ratios[0]:.1%} -> {ratios[-1]:.1%}")
check("台数は単調に増える（減ることはない）",
      all(a <= b for a, b in zip(counts_ins, counts_ins[1:])),
      f"{counts_ins[0]} -> {counts_ins[-1]} 本")
check("系全体の単価は単調に増える",
      all(a <= b for a, b in zip(hybrid, hybrid[1:])),
      f"{hybrid[0]:.4f} -> {hybrid[-1]:.4f}")
check("クラウド単価は単調ではない（台数の段差で跳ねる）",
      cloud[4] > cloud[3] and counts_ins[4] > counts_ins[3],
      f"{cloud[3]:.4f} -> {cloud[4]:.4f}"
      f"（送信率 {ratios[3]:.0%} -> {ratios[4]:.0%}）")
zero = replace(D, send_ratio=0.0)
check("送信率を下げるとクラウド単価は上がる",
      zero.cloud_cost_per_1k > D.cloud_cost_per_1k
      and zero.instances == D.instances,
      f"{D.send_ratio:.1%} で {D.cloud_cost_per_1k:.4f} / "
      f"{zero.send_ratio:.1%} で {zero.cloud_cost_per_1k:.4f}")
check("系全体では送信率を下げたほうが安い",
      zero.hybrid_cost_per_1k < D.hybrid_cost_per_1k,
      f"{D.hybrid_cost_per_1k:.4f} -> {zero.hybrid_cost_per_1k:.4f}"
      "（部分最適と全体最適が逆を向く）")
check("本文が出る件数と回線断でも処理できる件数の和は 1000",
      all(abs(r["leaked_per_1k"] + r["offline_ok_per_1k"] - 1000) < 1e-9
          for r in rows),
      "送信率を上げるとプライバシーとオフライン耐性が同時に悪化する")

# --- 4. 逆転条件 ------------------------------------------------------------
print("\n=== 4. 逆転条件 ===")
limit = D.send_ratio_limit
check("送信率の上限は計算から出る",
      abs(limit - (D.capacity_rps - D.hq_peak_rps) / D.peak_per_send_ratio) < 1e-12,
      f"{limit:.1%} = ({D.instances} × {D.per_instance_rps:.3f} − "
      f"{D.hq_peak_rps:.1f}) ÷ {D.peak_per_send_ratio:.4f}")
below = replace(D, send_ratio=0.31)
above = replace(D, send_ratio=0.33)
check("上限の手前では台数が変わらない", below.instances == D.instances,
      f"送信率 {below.send_ratio:.1%} で {below.instances} 本")
check("上限を超えると台数が増える", above.instances == D.instances + 1,
      f"送信率 {above.send_ratio:.1%} で {above.instances} 本")
check("ピーク倍率を 5.0 にしても台数は変わらない",
      replace(D, peak_factor=5.0).instances == D.instances,
      "台数を決めているのは本社のピーク")
check("完結率は送信率の裏返し",
      abs(D.completion_ratio - (1.0 - D.send_ratio)) < 1e-12
      and abs(D.completion_floor - (1.0 - limit)) < 1e-12,
      f"{D.completion_ratio:.1%}（下限 {D.completion_floor:.1%}）")

# --- 5. メモリと停止の猶予 ---------------------------------------------------
print("\n=== 5. メモリと停止の猶予 ===")
plan = D.plan
check("メモリ要求は requests と limits に同じ値を書ける",
      plan.memory.quantity() == "768Mi",
      plan.memory.explain())
check("コンテキストはスロット数で等分される",
      plan.ctx_per_slot == D.total_ctx // D.slots,
      f"-c {D.total_ctx} -np {D.slots} -> 1スロット {plan.ctx_per_slot}")
check("停止の猶予は preStop + 生成の最長 + 余裕",
      plan.grace_required_s <= 60.0,
      f"{PRESTOP_S:.0f} + {plan.max_request_s:.1f} + 5 = "
      f"{plan.grace_required_s:.1f} 秒 <= 60 秒")
check("台数が1本増えるとメモリ合計も1本ぶん増える",
      above.total_memory_mib
      == D.total_memory_mib + plan.memory_per_instance_mib,
      f"{D.total_memory_mib:,} MiB -> {above.total_memory_mib:,} MiB")

# --- 6. エッジ側の予算 -------------------------------------------------------
print("\n=== 6. エッジ側の予算（③前提値の端末に載るか）===")
fp, llm = D.edge_footprint, D.llm_footprint
ok_small, margin_small = fits(DEVICES["端末D"], fp)
ok_llm, margin_llm = fits(DEVICES["端末D"], llm)
check("分類器は端末Dに収まる", ok_small,
      f"{fp.total_mb:.2f} MB <= {DEVICES['端末D'].limit_mb:,.1f} MB"
      f"（余白 {margin_small:.2f} MB・KVキャッシュは 0）")
check("0.5B は端末Dに載らない", not ok_llm,
      f"{llm.total_mb:.1f} MB > {DEVICES['端末D'].limit_mb:,.1f} MB"
      f"（{-margin_llm:.1f} MB 不足）")
check("0.5B は端末Aには載る", fits(DEVICES["端末A"], llm)[0],
      f"上限 {DEVICES['端末A'].limit_mb:,.1f} MB"
      "（**端末が変われば却下理由が消える**）")
check("KVキャッシュは分類器では 0、言語モデルでは 24.0 MB",
      fp.kv_mb == 0.0 and abs(llm.kv_mb - 24.0) < 1e-6,
      f"12.00 KB/トークン × 2,048 = {llm.kv_mb:.1f} MB")
check("往復の物理下限は SLO に収まる（だからレイテンシでは失格しない）",
      D.rtt_ms < D.edge_slo_ms,
      f"{D.rtt_ms:.2f} ms < {D.edge_slo_ms:.0f} ms（距離 {D.distance_km:.0f} km）")

# --- 7. OTA -----------------------------------------------------------------
print("\n=== 7. OTA（②物理計算）===")
check(f"全台への配布は {D.distribution_seconds:,.1f} 秒",
      abs(D.distribution_seconds - 1404.8) < 0.05,
      f"{INT8_MB:.2f} MB × {D.devices:,} 台 ÷ {D.line_mbps:.1f} Mbps"
      f"（{D.distribution_seconds / 60:.1f} 分）")
check(f"同時ダウンロードの上限は {D.max_parallel_downloads} 台",
      D.max_parallel_downloads == 213,
      f"タイムアウト {CLIENT_TIMEOUT_S:.0f} 秒")
stages = D.stages
check(f"段階展開は {len(stages)} 段"
      f"（{' / '.join(str(s.added) for s in stages)} 台）",
      len(stages) == 4 and sum(s.added for s in stages) == D.devices,
      f"所要 {D.rollout_hours:.1f} 時間")
check("fp32 は int8 の 4.0 倍の時間がかかる",
      abs(transfer_seconds(FP32_MB, D.devices, D.line_mbps)
          / D.distribution_seconds - FP32_MB / INT8_MB) < 1e-9,
      "サイズ比の逆数")

# --- 8. 振り分け ------------------------------------------------------------
print("\n=== 8. 振り分け（3分岐にする）===")
check("マージンがしきい値以上ならエッジで完結",
      handoff(0.20, D.threshold, True) == HANDOFF_EDGE, "0.20 >= 0.10")
check("境界（しきい値と同じ）は完結側",
      handoff(D.threshold, D.threshold, True) == HANDOFF_EDGE, "0.10 >= 0.10")
check("しきい値未満はクラウドへ引き継ぐ",
      handoff(0.05, D.threshold, True) == HANDOFF_CLOUD, "0.05 < 0.10")
check("回線断なら保留キューへ（**静かに落とさない**）",
      handoff(0.05, D.threshold, False) == HANDOFF_QUEUE,
      "既定の区分に寄せない")
check("送信率はマージンの分布から決まる",
      route(DEMO_MARGINS, D.threshold).send_ratio == D.send_ratio,
      f"{route(DEMO_MARGINS, D.threshold).to_cloud} / {len(DEMO_MARGINS)} 件")

# --- 9. SLO とアラート -------------------------------------------------------
print("\n=== 9. SLO とアラート（要素を強制する）===")
objs, alrt = objectives(D), alerts(D)
check("SLO は4本（3本は既習の導出、4本目が系としての SLO）", len(objs) == 4,
      " / ".join(o.key for o in objs))
check("すべての SLO に導き方がある", all(o.derivation for o in objs),
      "値だけの目標は作れない")
check("すべての SLO に超えたときの行動がある",
      all(o.on_breach for o in objs), "行動が無い目標はただの数字")
try:
    Objective(key="x", label="x", target="1 ms", derivation="d", how="h",
              window="w", ceiling="c", on_breach=())
    ok_obj = False
except ValueError:
    ok_obj = True
check("超えたときの行動が空だと SLO は作れない", ok_obj, "ValueError になる")
check("アラートは10件以上", len(alrt) >= 10, f"{len(alrt)} 件")
check("アラートの5要素に空欄が無い",
      all(a.metric and a.threshold and a.window and a.action and a.owner
          for a in alrt), "1つでも空なら作れない")
try:
    Alert("キュー長", "1.0 件", "5 分", "台数を増やす", "")
    ok_alert = False
except ValueError:
    ok_alert = True
check("担当が空だとアラートは作れない", ok_alert,
      "「鳴ったが誰も動かない」を構造で防ぐ")
check("誤検知を抑える条件が半分以上に書かれている",
      sum(1 for a in alrt if a.guard) >= len(alrt) // 2,
      f"{sum(1 for a in alrt if a.guard)} / {len(alrt)} 件")

# --- 10. runbook ------------------------------------------------------------
print("\n=== 10. runbook（必須項目・3値・禁止語）===")
book = runbook_markdown(D)
errors, warns = counts(lint_runbook_final(book))
check("必須項目がすべて埋まっている", errors == 0,
      f"エラー {errors} 件 / 警告 {warns} 件")
check("モデル更新とロールバックの節がある",
      "モデル更新" in book and "ロールバック" in book, "本章で足した2節")
check("判定は3値（続行／保留／中止）", all(v in book for v in VERDICTS),
      " / ".join(VERDICTS))
check("戻すのにかかる時間が書かれている",
      f"{D.distribution_seconds:,.1f} 秒" in book,
      "二面構成なら再ダウンロード不要、配り直すと 23.4 分以上")
broken = book.replace("## 8. モデル更新時の手順", "## 8. 手順")
check("モデル更新の節を消すと検出できる",
      counts(lint_runbook_final(broken))[0] >= 1, "必須項目の検査が働く")
two_valued = book.replace("「保留」", "「中断」")
check("判定を2値にすると検出できる",
      counts(lint_runbook_final(two_valued))[0] >= 1,
      "良い版を捨てるか悪い版を配ることになる")
banned = book + f"\n異常があれば{BANNED[0]}。\n"
check("当番が動けない表現を警告できる",
      counts(lint_runbook_final(banned))[1] >= 1,
      f"「{BANNED[0]}」は手順ではない")

# --- 11. 成果物7点と整合 -----------------------------------------------------
print("\n=== 11. 成果物7点と整合 ===")
names = [name for name, _ in DELIVERABLES]
docs = documents(D)
buffer = io.StringIO()
with tempfile.TemporaryDirectory() as tmp:
    with contextlib.redirect_stdout(buffer):
        code = write_all(tmp, D)
    written = sorted(p.name for p in Path(tmp).iterdir())
check("7点すべてを書き出せる", code == 0 and written == sorted(names),
      f"一時ディレクトリに {len(written)} ファイル")
missing = missing_sections(docs)
check("必須の節がすべてある", not missing,
      f"{len(docs)} 文書 / 欠落 {len(missing)} 件")
shared = shared_values(D)
check("生成した文書は整合している", not cross_check(docs, shared),
      f"共有値 {len(shared)} 件・食い違い 0 件")
stale = {**docs, CAPACITY: docs[CAPACITY].replace("768Mi", "512Mi")}
found = cross_check(stale, shared)
check("数字を1か所だけ古くすると検出できる", len(found) == 1,
      "768Mi -> 512Mi にすると 1 件の指摘")
check("正典が1つに決まっている",
      all(item.source in item.files for item in shared),
      " / ".join(f"{item.key}:{item.source[:2]}" for item in shared))

# --- 12. 端末群の門 ----------------------------------------------------------
print("\n=== 12. 端末群の門（配る前・配った後）===")
fleet = sample_fleet(D.devices)
stats = {s.version: s for s in version_mix(fleet)}
totals = fleet_totals(fleet)
check("配る前の門は等価性で判定する",
      release_gate(EQ_MAX_DIFF, True).ok
      and not release_gate(0.02, True).ok,
      f"最大差 {EQ_MAX_DIFF:.6f} なら配ってよい / 0.02 なら配ってはいけない")
new, base = stats["1.3.0"], stats["1.2.0"]
verdict = rollout_gate(new, base)
check("新版の失敗率が許容を超えたら中止", verdict.verdict == "中止",
      f"新版 {new.failure_rate:.1%} > 許容 {base.failure_rate * 1.5:.2%}")
few = replace(new, inferences=500, failures=20)
check("件数が足りなければ保留（中止にしない）",
      rollout_gate(few, base).verdict == "保留",
      "件数の検査を先に置く（良い版を捨てない）")
check("p95 はバケットで表す（分位は足せない）",
      quantile_bucket(base.buckets, 0.95) == "1.0 ms 未満"
      and quantile_bucket(new.buckets, 0.95) == "2.0 ms 未満",
      "現行版は目標内 / 新版は1段悪い")
check("オフライン端末を分母から外さない",
      abs(totals.offline_ratio - 0.10) < 1e-9,
      f"{totals.offline}/{totals.devices} 台（{totals.offline_ratio:.1%}）")

bail()

# --- 13. 推論サーバでの確認 --------------------------------------------------
print("\n=== 13. 推論サーバでの確認（SKIP_SERVER=1 で飛ばせる）===")
if os.environ.get("SKIP_SERVER") == "1":
    print("SKIP_SERVER=1 のため推論サーバを使う検証を飛ばします。")
else:
    from infrakit.client import LlamaClient  # noqa: E402

    client = LlamaClient()
    alive = client.health()
    check("推論サーバに接続できる", alive,
          "" if alive else "docker compose up -d llama を実行してください")
    bail()

    props = client.props()
    # llama.cpp の /props は n_ctx を default_generation_settings の下に入れる版と
    # トップレベルに置く版がある（requirements.md の「陳腐化に弱い箇所」②）。
    # 上流の項目名を断定せず、両方を見る（セッション10 のアダプタ層の考え方）。
    settings = props.get("default_generation_settings") or {}
    n_ctx = settings.get("n_ctx") or props.get("n_ctx")
    check("コンテキスト長を取得できる", n_ctx is not None,
          f"n_ctx = {n_ctx}（-c をスロット数で割った値）")
    res = client.generate("こんにちは。ヘルプデスクの受付です。", max_tokens=8)
    check("生成が成功する", res.error is None and res.tokens_out > 0,
          f"出力 {res.tokens_out} トークン")
    check("TTFT は総時間以下", res.ttft_ms <= res.total_ms + 1e-6,
          "レイテンシの絶対値はアサーションしていません")
    print(f"    記録: TTFT {res.ttft_ms:.0f} ms / 総時間 {res.total_ms:.0f} ms"
          "（この環境の値。期待値にはしていません）")

bail()
print(f"\n検証した項目: {checked} 件")
print("最終プロジェクトの検証はすべて成功しました。")
