#!/usr/bin/env python3
"""セッション10の自己検証：見えるようにして、単価で語る。

**Prometheus も推論サーバも起動しない。ネットワークにも出ない。** 検証するのは
決定的に決まる4種類だけである。

  1. `/metrics`（同梱の固定サンプル）を本書の名前に翻訳する経路
  2. ヒストグラムの数え方（累積・分位点・SLO 違反率・+Inf の扱い）
  3. 単価・停止スケジュール・損益分岐・感度分析の計算
  4. Prometheus の設定とルール、compose の上書きファイルの静的検査（PyYAML）

**絶対値ではなく関係を検証する。** 例：単価は利用率に反比例する／台数では動かない／
損益分岐は rps でも利用率でも動かない／飽和させると単価は少し下がるが TTFT は
桁で悪化する。本文に載せた「期待される出力」の文字列もここで突き合わせている。
"""

from __future__ import annotations

import contextlib
import io
import math
import sys
from dataclasses import replace
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.session09.scaling import (  # noqa: E402
    SLOTS_PER_INSTANCE, Slo, target_queue_len,
)
from src.session10.cost_report import (  # noqa: E402
    HOURS_PER_WEEK, MAX_UTILIZATION, Assumptions, breakeven,
    capacity_requests_per_hour, cost_per_1k, explain, headroom_price, levers,
    report_markdown, requests_per_hour, saturation_tradeoff, schedules,
    sensitivity_rows, utilization_rows,
)
from src.session10.cost_report import main as cost_main  # noqa: E402
from src.session10.inference_metrics import (  # noqa: E402
    GATEWAY_METRICS, OUR_METRICS, SAMPLE_RENAMED, SAMPLES, SOURCES,
    TPOT_BOUNDS, TPOT_EXAMPLE, TTFT_BOUNDS, TTFT_EXAMPLE, LatencyHistogram,
    SourceMetric, adapt, parse_exposition, render_gateway,
)
from src.session10.inference_metrics import main as metrics_main  # noqa: E402

HERE = Path(__file__).resolve().parent

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def close(a: float, b: float, rel: float = 1e-9) -> bool:
    return math.isclose(a, b, rel_tol=rel, abs_tol=1e-12)


def run(fn, argv: list[str]) -> tuple[int, str]:
    buf, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
        code = fn(argv)
    return code, buf.getvalue() + err.getvalue()


def load_yaml(name: str) -> dict:
    return yaml.safe_load((HERE / name).read_text(encoding="utf-8"))


# --- 1. メトリクスの翻訳 --------------------------------------------------------
print("=== /metrics を本書の名前に直す ===")

sat = adapt(SAMPLES["saturated"], slots=SLOTS_PER_INSTANCE)
healthy = adapt(SAMPLES["healthy"], slots=SLOTS_PER_INSTANCE)

check("飽和したサンプルは欠測なしで翻訳できる", sat.ok, f"used={sat.used}")
check("キュー長は 2 件（並列4 でスロット2 を超えた分）",
      close(sat.values["inference_queue_length"], 2.0))
check("スロット使用率は派生値として自分で作る",
      "inference_slot_utilization" in sat.derived
      and close(sat.values["inference_slot_utilization"], 1.0))
check("健全なサンプルはキュー長 0 件", healthy.ok
      and close(healthy.values["inference_queue_length"], 0.0))
check("スロット使用率は健全でも飽和でも同じ 1.0（頭打ち）",
      close(healthy.values["inference_slot_utilization"],
            sat.values["inference_slot_utilization"]),
      "セッション9 の結論：区別できるのはキュー長だけ")
check("処理中の件数も両者で同じ 2 件",
      close(healthy.values["inference_active_requests"],
            sat.values["inference_active_requests"]))
check("KVキャッシュ使用率は必須ではない",
      [s.required for s in SOURCES if s.ours == "inference_kv_cache_ratio"] == [False])

expected_saturated = "\n".join([
    "# HELP inference_queue_length スロットに載れず待っている件数（セッション9 の第一の指標）",
    "# TYPE inference_queue_length gauge",
    "inference_queue_length 2",
    "# HELP inference_slot_utilization 使用中スロット ÷ 総スロット（1.0 で頭打ち）",
    "# TYPE inference_slot_utilization gauge",
    "inference_slot_utilization 1",
    "# HELP inference_active_requests スロットに載って処理中の件数",
    "# TYPE inference_active_requests gauge",
    "inference_active_requests 2",
    "# HELP inference_kv_cache_ratio KVキャッシュの埋まり具合（0.0〜1.0）",
    "# TYPE inference_kv_cache_ratio gauge",
    "inference_kv_cache_ratio 0.35",
])
check("本文に載せた出力と1文字も違わない（saturated）",
      sat.render() == expected_saturated)
check("公開した形を読み戻すと本書の名前だけが並ぶ",
      {s.name for s in parse_exposition(sat.render())}
      == {name for name, _, _ in OUR_METRICS},
      "上流の名前は1つも残らない")

print("\n=== 上流の名前が変わったとき ===")
renamed = adapt(SAMPLE_RENAMED, slots=SLOTS_PER_INSTANCE)
check("欠測は 0 で埋めず、欠測として報告する", not renamed.ok
      and renamed.missing == ("inference_active_requests", "inference_queue_length"),
      f"missing={renamed.missing}")
check("欠測した項目の行は出力しない（0 の行を作らない）", renamed.render() == "")
advice = "\n".join(renamed.advice())
check("直し方（候補を1行足す）が出力に含まれる",
      "SOURCES の candidates に足す" in advice and "0 で埋めてはいけません" in advice)

no_def = adapt(SAMPLES["no-deferred"], slots=SLOTS_PER_INSTANCE)
check("待ちを表す項目が無ければ欠測になる",
      no_def.missing == ("inference_queue_length",))
derived = adapt(SAMPLES["no-deferred"], slots=SLOTS_PER_INSTANCE,
                gateway_stats={"inflight": 4})
check("ゲートウェイの inflight からキュー長を作れる（4 − 2 = 2）",
      derived.ok and close(derived.values["inference_queue_length"], 2.0)
      and "inference_queue_length" in derived.derived)
negative = adapt(SAMPLES["no-deferred"], slots=SLOTS_PER_INSTANCE,
                 gateway_stats={"inflight": 1})
check("inflight が処理中より少なくても負にならない",
      close(negative.values["inference_queue_length"], 0.0))

# 問題5（読者が書く解答）と同じ対応表。候補は「足す」だけで既存を消さない
ANSWER_SOURCES = (
    SourceMetric("inference_active_requests",
                 ("llamacpp:requests_processing", "server_requests_in_flight"),
                 True, "grep -i -e process -e slot -e flight", "処理中の件数"),
    SourceMetric("inference_queue_length", ("llamacpp:requests_deferred",),
                 True, "grep -i -e defer -e queue -e wait", "待っている件数"),
    SourceMetric("inference_kv_cache_ratio",
                 ("llamacpp:kv_cache_usage_ratio", "server_kv_cache_ratio"),
                 False, "grep -i kv", "KVキャッシュの埋まり具合"),
)
fixed = adapt(SAMPLE_RENAMED, slots=SLOTS_PER_INSTANCE,
              gateway_stats={"inflight": 3}, sources=ANSWER_SOURCES)
check("候補名を足すと新しい版でも翻訳できる（問題5の解答）", fixed.ok,
      f"used={fixed.used}")
check("問題5の期待出力どおりキュー長 1・KV 0.18",
      close(fixed.values["inference_queue_length"], 1.0)
      and close(fixed.values["inference_kv_cache_ratio"], 0.18)
      and fixed.derived == ("inference_slot_utilization", "inference_queue_length"))
check("既存の候補を消していない（旧版でも動く）",
      adapt(SAMPLES["saturated"], slots=SLOTS_PER_INSTANCE,
            sources=ANSWER_SOURCES).ok)

try:
    adapt(SAMPLES["saturated"], slots=0)
    check("スロット 0 は例外にする", False)
except ValueError:
    check("スロット 0 は例外にする", True, "0 除算で黙って壊れない")

print("\n=== ゲートウェイの /stats を Prometheus の形にする ===")
gw = render_gateway({"requests": 120, "rate_limited": 8, "rejected": 2,
                     "cache_hits": 30, "errors": 1, "inflight": 3,
                     "cache": {"hits": 30, "misses": 90, "hit_rate": 0.25}})
check("ゲートウェイ側の6項目とキャッシュヒット率が出る",
      all(name in gw for name, _, _, _ in GATEWAY_METRICS)
      and "inference_cache_hit_ratio 0.25" in gw)
check("429 と 503 を別のカウンタで持つ（断り方を混ぜない）",
      "inference_gateway_rate_limited_total 8" in gw
      and "inference_gateway_rejected_total 2" in gw)

print("\n=== CLI の終了コード（CI に置ける形）===")
code, out = run(metrics_main, ["--sample", "saturated"])
check("翻訳できたら終了コード 0", code == 0 and "inference_queue_length 2" in out)
code, out = run(metrics_main, ["--sample", "renamed"])
check("欠測があれば終了コード 1", code == 1 and "[欠測]" in out,
      "上流の名前が変わった瞬間に CI が赤くなる")
code, out = run(metrics_main, ["--sample", "no-deferred", "--gateway-inflight", "4"])
check("代替経路が使えれば終了コード 0", code == 0 and "inference_queue_length 2" in out)

# --- 2. 分布（ヒストグラム）-----------------------------------------------------
print("\n=== 分布で見る（平均は分布を隠す）===")

check("TTFT の例は 20 件・平均 300ms", TTFT_EXAMPLE.total == 20
      and close(TTFT_EXAMPLE.average_seconds, 0.3))
check("累積件数は 0,10,15,17,18,19,20,20",
      TTFT_EXAMPLE.cumulative() == [0, 10, 15, 17, 18, 19, 20, 20])
check("p50 は 100ms、p95 は 2000ms",
      close(TTFT_EXAMPLE.quantile(0.5), 0.1)
      and close(TTFT_EXAMPLE.quantile(0.95), 2.0))
check("平均は SLO の中なのに p95 は SLO の 2 倍",
      TTFT_EXAMPLE.average_seconds < 1.0 and TTFT_EXAMPLE.quantile(0.95) == 2.0,
      "平均 300ms / p95 2000ms / SLO 1000ms")
check("SLO 1.0 秒の違反率は 10%（20 件中 2 件）",
      close(TTFT_EXAMPLE.violation_ratio(1.0), 0.1))
check("本文の要約行と一致する",
      TTFT_EXAMPLE.summary()
      == "inference_ttft_seconds: n=20 平均=300ms p50=100ms p95=2000ms",
      TTFT_EXAMPLE.summary())
check("SLO の値が境界に入っている（引き算だけで違反率が出る）",
      1.0 in TTFT_BOUNDS)

check("TPOT の例も同じ形（平均は上限の内側・10% が違反）",
      TPOT_EXAMPLE.summary()
      == "inference_tpot_seconds: n=20 平均=30ms p50=17ms p95=80ms"
      and close(TPOT_EXAMPLE.violation_ratio(0.0426), 0.1),
      TPOT_EXAMPLE.summary())
check("TPOT の境界には SLO から逆算した上限が入っている",
      0.0426 in TPOT_BOUNDS
      and abs(0.0426 - (3000.0 - 1000.0) / 47 / 1000.0) < 1e-4,
      "総時間 3000ms − TTFT 1000ms を 47 トークンで割ると 42.6ms")

try:
    TTFT_EXAMPLE.at_most(0.8)
    check("境界に無い値の違反率は例外にする", False)
except ValueError:
    check("境界に無い値の違反率は例外にする", True, "推測値を黙って返さない")

roundtrip = LatencyHistogram.from_exposition(TTFT_EXAMPLE.render(),
                                             "inference_ttft_seconds")
check("公開した形（累積）から読み戻せる",
      roundtrip.counts == TTFT_EXAMPLE.counts
      and close(roundtrip.sum_seconds, TTFT_EXAMPLE.sum_seconds),
      "ダッシュボードが見ている形で検算できる")

overflow = LatencyHistogram.from_values("x", [6.0], TTFT_BOUNDS)
check("最上位のバケットに落ちた分位点は +Inf を返す",
      math.isinf(overflow.quantile(0.95)),
      "「とても遅い」ではなく「境界の設計が足りない」と読む")
for bad, why in (((0, 1), "counts が bounds より1つ多くない"),
                 ((0, 1, 2, 3, 4, 5, 6, -1), "counts に負の数")):
    try:
        LatencyHistogram("x", TTFT_BOUNDS, bad, 1.0)
        check(f"{why} は例外にする", False)
    except ValueError:
        check(f"{why} は例外にする", True)

# --- 3. 単価と損益分岐 ---------------------------------------------------------
print("\n=== 1000リクエスト単価（分母は SLO を満たす動作点）===")

BASE = Assumptions()
check("動作点は実測の 1.13 rps（SLO を満たす中で最大）",
      close(BASE.rps_per_instance, 1.13))
check("既定の利用率はヘッドルーム 30% の裏返し（70%）",
      close(BASE.utilization, MAX_UTILIZATION) and close(BASE.utilization, 0.7))
check("1時間の処理数は 8542.8 リクエスト",
      f"{requests_per_hour(BASE):.1f}" == "8542.8",
      "1.13 × 3600 × 3 本 × 70%")
check("1000リクエスト単価は 0.3512（相対単位）",
      f"{cost_per_1k(BASE):.4f}" == "0.3512")
check("台数を変えても単価は変わらない（式で約分される）",
      close(cost_per_1k(replace(BASE, instances=7)), cost_per_1k(BASE)),
      "3 本 → 7 本。請求総額は増えるが単価は同じ")
check("単価は利用率に反比例する（10% と 90% で 9.00 倍）",
      close(cost_per_1k(BASE, 0.1) / cost_per_1k(BASE, 0.9), 9.0),
      "9 という数字は 0.9 ÷ 0.1 そのもの")

rows = {row["utilization"]: row for row in utilization_rows(BASE)}
for util, rph, cost in ((0.1, 1220, 2.4582), (0.2, 2441, 1.2291),
                        (0.5, 6102, 0.4916), (0.7, 8543, 0.3512),
                        (0.9, 10984, 0.2731)):
    row = rows[util]
    check(f"利用率 {util * 100:.0f}% → {rph:,} リクエスト/時・単価 {cost}",
          row["requests_per_hour"] == rph
          and close(row["cost_per_1k_requests"], cost))

sat_rows = {row["utilization"]: row["cost_per_1k_requests"]
            for row in utilization_rows(replace(BASE, rps_per_instance=1.15))}
check("飽和した点（1.15 rps）で数えても 9 倍の関係は同じ",
      close(sat_rows[0.1], 2.4155) and close(sat_rows[0.9], 0.2684)
      and close(sat_rows[0.1] / sat_rows[0.9], 9.0, rel=1e-4),
      "2.4155 → 0.2684。関係は動かない（値だけ 1.7% ずれる）")

hp = headroom_price(BASE)
check("ヘッドルーム 30% は単価 1.43 倍として現れる",
      f"{hp['ratio']:.2f}" == "1.43",
      f"利用率100% {hp['full']:.4f} → 70% {hp['capped']:.4f}。安全のための値段")

print("\n=== 停止スケジュール ===")
plans = schedules(BASE)
baseline = plans[0].instance_hours
check("常時稼働は週 504.0 インスタンス時間", close(baseline, 504.0),
      f"3 本 × {HOURS_PER_WEEK:.0f} 時間")
check("夜間・週末 1 本なら 288.0 時間・削減 42.9%",
      close(plans[1].instance_hours, 288.0)
      and f"{plans[1].saving_ratio(baseline) * 100:.1f}" == "42.9")
check("夜間・週末 0 本なら 180.0 時間・削減 64.3%",
      close(plans[2].instance_hours, 180.0)
      and f"{plans[2].saving_ratio(baseline) * 100:.1f}" == "64.3")
check("0 本にすると最初の利用者はセッション9 の遅れを丸ごと待つ",
      "56.6 秒" in plans[2].note and "56.6 倍" in plans[2].note,
      plans[2].note)
check("削減率の差は 21.4 ポイントしかないのに、片方だけ SLO の合意が要る",
      close((plans[2].saving_ratio(baseline) - plans[1].saving_ratio(baseline)) * 100,
            21.4285714285, rel=1e-6))

print("\n=== クラウドAPIとの損益分岐 ===")
be = breakeven(BASE)
check("API の1リクエスト単価は 0.0003936（300 入力 / 48 出力）",
      f"{be.api_per_request:.7g}" == "0.0003936"
      and f"{be.api_per_1k:.4f}" == "0.3936")
check("損益分岐は毎時 7621.95 リクエスト（2.12 rps）",
      f"{be.requests_per_hour:.2f}" == "7621.95" and f"{be.rps:.2f}" == "2.12",
      "固定費 3 ÷ 1リクエスト単価")
check("分岐点は 3 本の能力（毎時 8542.8）の内側 → 達成できる",
      be.achievable and f"{capacity_requests_per_hour(BASE):.1f}" == "8542.8")
check("分岐点は利用率 62.5% に当たる（上限 70% まで余地は 7.5 ポイント）",
      f"{be.utilization * 100:.1f}" == "62.5")
check("いまの利用率では自前のほうが安い",
      be.self_hosting_cheaper_now and be.self_cost_per_1k < be.api_per_1k,
      f"自前 {be.self_cost_per_1k:.4f} < API {be.api_per_1k:.4f}")
check("損益分岐は rps でも利用率でも動かない（固定費と API 単価だけで決まる）",
      close(breakeven(replace(BASE, rps_per_instance=2.0)).requests_per_hour,
            be.requests_per_hour)
      and close(breakeven(replace(BASE, utilization=0.2)).requests_per_hour,
                be.requests_per_hour))
cheap_api = breakeven(replace(BASE, api_input_price_per_1m=0.5,
                              api_output_price_per_1m=1.5))
check("API が安い前提では分岐点が能力を超える（自前は選べない）",
      not cheap_api.achievable
      and f"{cheap_api.requests_per_hour:.2f}" == "13513.51",
      "どれだけ詰めても自前は安くならない、という結論もある")

print("\n=== 感度分析 ===")
sens = {row["label"]: row for row in sensitivity_rows(BASE)}
expected_sens = {
    "インスタンス時間単価": ("+10.0%", "+10.0%"),
    "動作点の rps": ("-9.1%", "0.0%"),
    "利用率": ("-9.1%", "0.0%"),
    "API の出力トークン単価": ("0.0%", "-3.8%"),
    "1リクエストの出力トークン数": ("0.0%", "-3.8%"),
}
for label, (want_cost, want_break) in expected_sens.items():
    row = sens[label]
    got_cost = ("0.0%" if abs(row["cost_delta"]) < 1e-12
                else f"{row['cost_delta'] * 100:+.1f}%")
    got_break = ("0.0%" if abs(row["breakeven_delta"]) < 1e-12
                 else f"{row['breakeven_delta'] * 100:+.1f}%")
    check(f"{label} +10% → 単価 {want_cost} / 分岐点 {want_break}",
          got_cost == want_cost and got_break == want_break,
          f"実際は 単価 {got_cost} / 分岐点 {got_break}")

print("\n=== 単価だけを最適化してはいけない ===")
trade = saturation_tradeoff(BASE)
check("飽和させると rps は 1.02 倍しか増えない",
      f"{trade['rps_ratio']:.2f}" == "1.02")
check("単価は 1.7% しか下がらない",
      f"{trade['cost_ratio']:.2f}" == "0.98"
      and f"{trade['saving_pct']:.1f}" == "1.7",
      f"{trade['cost_slo']:.4f} → {trade['cost_sat']:.4f}")
check("その代償に TTFT p95 は 20.6 倍になる",
      f"{trade['ttft_ratio']:.1f}" == "20.6",
      f"{trade['ttft_slo_ms']:.0f} ms → {trade['ttft_sat_ms']:.0f} ms（SLO 違反）")

lever_ratio = {lever["action"]: f"{lever['ratio']:.2f}" for lever in levers(BASE)}
for action, want in (("利用率を 20% から 70% へ", "0.29"),
                     ("量子化を Q4_K_M から Q8_0 へ", "0.69"),
                     ("応答キャッシュのヒット率 30%", "0.70"),
                     ("台数を 3 本から 7 本へ", "1.00"),
                     ("飽和させる（並列2 → 並列4）", "0.98")):
    check(f"{action} → 単価 {want} 倍", lever_ratio.get(action) == want,
          f"実際は {lever_ratio.get(action)}")

print("\n=== 前提の検証（おかしな入力は通さない）===")
for kwargs, why in (({"utilization": 0.0}, "利用率 0"),
                    ({"utilization": 1.5}, "利用率 150%"),
                    ({"instances": 0}, "台数 0"),
                    ({"rps_per_instance": 0.0}, "rps 0"),
                    ({"hourly_cost": -1.0}, "時間単価が負"),
                    ({"output_tokens": -1.0}, "トークン数が負")):
    try:
        replace(BASE, **kwargs)
        check(f"{why} は例外にする", False)
    except ValueError:
        check(f"{why} は例外にする", True)

print("\n=== 本文・解答に載せた出力と突き合わせる ===")
text = explain(BASE)
for line in (
    "  1時間の固定費  : 1 × 3 本 = 3",
    "  1時間の処理数  : 1.13 rps × 3600 × 3 本 × 70% = 8542.8 リクエスト",
    "  1000リクエスト : 3 ÷ 8542.8 × 1000 = 0.3512",
    "| 10% | 1,220 | 2.4582 | 7.00 倍 |",
    "| 90% | 10,984 | 0.2731 | 0.78 倍 |",
    "| 常時 3 本 | 504.0 | 0.0% | 0 秒 |",
    "| 夜間・週末は 1 本 | 288.0 | 42.9% | 0 秒（1本は残る） |",
    "| 夜間・週末は 0 本 | 180.0 | 64.3% | 56.6 秒（TTFT SLO の 56.6 倍） |",
    "  API の1リクエスト単価 : 300 ÷ 1e6 × 0.8 + 48 ÷ 1e6 × 3.2 = 0.0003936",
    "  損益分岐               : 3 ÷ 0.0003936 = 7621.95 リクエスト/時（= 2.12 rps）",
    "  損益分岐の利用率       : 62.5%（上限 70% の内側 → 達成できる）",
    "  いまの利用率 70% の単価: 自前 0.3512 < API 0.3936 → 自前が安い",
    "| 動作点の rps | -9.1% | 0.0% |",
    "  単価は 0.3512 → 0.3451（0.98 倍・1.7% 安い）",
    "  しかし TTFT p95 は 100 ms → 2064 ms（20.6 倍）で SLO 違反",
):
    check(f"出力に「{line.strip()[:34]}」がある", line in text)
check("測定条件が必ず併記される", "2026-08-15 実測" in text)

md = report_markdown(BASE)
for heading in ("# コスト試算：みなと商事 ヘルプデスク回答 API",
                "## 1. 前提（変わったら数え直す入力）",
                "## 2. 1000リクエスト単価",
                "## 3. 利用率の感度",
                "## 4. 停止スケジュール",
                "## 5. クラウドAPI との損益分岐",
                "## 6. 前提が変わったときの再計算手順"):
    check(f"引き継げる成果物に「{heading.lstrip('# ')}」がある", heading in md)
check("成果物に SLO が制約として書かれている",
      "TTFT p95 ≦ 1000 ms" in md and "制約条件" in md)
check("成果物で実測と入力欄・仮定が区別されている",
      "実測（SLO を満たす動作点" in md and "入力欄（読者が入れる）" in md
      and "仮定（ヘッドルーム" in md)

code, out = run(cost_main, [])
check("CLI は終了コード 0 で単価を出す", code == 0 and "=== 1000リクエスト単価 ===" in out)
code, out = run(cost_main, ["--utilization", "0.2"])
check("利用率を変えると単価も変わる（1.2291）",
      code == 0 and "× 20% = 2440.8 リクエスト" in out and "= 1.2291" in out)
code, out = run(cost_main, ["--utilization", "0"])
check("おかしな前提は終了コード 2 で断る", code == 2 and "前提が不正です" in out)
code, out = run(cost_main, ["--markdown"])
check("--markdown は引き継げる成果物を出す",
      code == 0 and "## 6. 前提が変わったときの再計算手順" in out)

# --- 4. Prometheus の設定とルールの静的検査 -------------------------------------
print("\n=== prometheus-inference.yml（項目名の翻訳）===")

prom = load_yaml("prometheus-inference.yml")
jobs = {job["job_name"]: job for job in prom["scrape_configs"]}
check("llama を収集対象にしている", jobs["llama"]["static_configs"][0]["targets"]
      == ["llama:8080"])
check("ルールファイルを読み込んでいる",
      prom["rule_files"] == ["/etc/prometheus/inference-rules.yml"])

renames = {}
for rule in jobs["llama"]["metric_relabel_configs"]:
    check(f"翻訳先は本書の名前（{rule['replacement']}）",
          rule["replacement"] in {name for name, _, _ in OUR_METRICS}
          and rule["target_label"] == "__name__"
          and rule["source_labels"] == ["__name__"])
    renames[rule["replacement"]] = rule["regex"]

by_ours = {s.ours: s for s in SOURCES}
for ours, regex in renames.items():
    check(f"{ours} の元になる名前が候補リストにある",
          regex in by_ours[ours].candidates,
          f"regex={regex}")
required = {s.ours for s in SOURCES if s.required}
check("必須の指標はすべて翻訳されている", required <= set(renames),
      f"必須 {sorted(required)} / 翻訳 {sorted(renames)}")

print("\n=== inference-rules.yml（派生値とアラート）===")
rules = load_yaml("inference-rules.yml")
groups = {group["name"]: group for group in rules["groups"]}
records = [r for r in groups["inference-recording"]["rules"] if "record" in r]
alerts = [r for r in groups["inference-alerts"]["rules"] if "alert" in r]

check("スロット使用率は recording rule で作る",
      [r["record"] for r in records] == ["inference_slot_utilization"])
divisor = float(records[0]["expr"].split("/")[-1].strip())
check("その分母は並列スロット数（台数ではない）",
      close(divisor, float(SLOTS_PER_INSTANCE)), f"expr={records[0]['expr']}")

check("アラートは4本", len(alerts) == 4,
      " / ".join(a["alert"] for a in alerts))
check("すべてのアラートに for が付いている",
      all(a.get("for") for a in alerts),
      " / ".join(f"{a['alert']}={a.get('for')}" for a in alerts))
check("すべてのアラートに severity と summary が付いている",
      all(a["labels"]["severity"] in ("warning", "critical")
          and a["annotations"]["summary"] for a in alerts))
exprs = {a["alert"]: a["expr"] for a in alerts}
check("キュー長のしきい値は容量計画と同じ 1 件",
      exprs["InferenceQueueBacklog"].endswith(f"> {target_queue_len():g}"),
      exprs["InferenceQueueBacklog"])
check("SLO 違反は分位点で判定する（TTFT 1 秒）",
      "histogram_quantile(0.95" in exprs["InferenceTtftSloBurn"]
      and exprs["InferenceTtftSloBurn"].endswith(
          f"> {Slo().ttft_p95_ms / 1000:g}"))
check("欠測そのものにアラートを付けている",
      exprs["InferenceMetricsMissing"] == "absent(inference_queue_length)")
check("平均（_sum / _count）でアラートを鳴らしていない",
      not any("_sum" in expr or "_count" in expr for expr in exprs.values()))
check("CPU 使用率でアラートを鳴らしていない",
      not any("cpu" in expr.lower() for expr in exprs.values()),
      "推論の飽和と相関しない（セッション9）")

print("\n=== compose.metrics.yml（任意起動の上書き）===")
override = load_yaml("compose.metrics.yml")
mounts = override["services"]["prometheus"]["volumes"]
targets = [m.split(":")[1] for m in mounts]
check("設定とルールを Prometheus の読む場所に重ねている",
      targets == ["/etc/prometheus/prometheus.yml",
                  "/etc/prometheus/inference-rules.yml"], str(targets))
check("読み取り専用でマウントしている", all(m.endswith(":ro") for m in mounts))
check("既定の docker-compose.yml を書き換えずに済ませている",
      "services" in override and set(override["services"]) == {"prometheus"})

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション10の検証はすべて成功しました。")
