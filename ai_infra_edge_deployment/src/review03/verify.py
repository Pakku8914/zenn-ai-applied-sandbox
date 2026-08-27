#!/usr/bin/env python3
"""復習3（セッション2〜12）の自己検証。

    python src/review03/verify.py

検証するのは**絶対値ではなく関係**である。推論サーバは要らない（すべて式・文字列・
定数の計算で完結するので、環境によってぶれない）。レイテンシの絶対値を期待値に
書いてはいけない（実行ごとに2倍程度ぶれるため）。

- セッション2 : 総時間の組み立て／p95 に必要な件数
- セッション3 : KVキャッシュは系列長で決まる／サイズ順と速さ順は一致しない
- セッション4 : 飽和点は「伸びが止まり TTFT が悪化する点」
- セッション9 : CPU 使用率は健全な点と飽和した点を区別できない／しきい値は飽和点の手前
- セッション10: アダプタ層は欠測を 0 で埋めない／単価は利用率に反比例／損益分岐は
                rps と利用率で動かない
- セッション11: 端末の予算は重みが支配する／往復の物理的下限
- セッション12: サイズ比のとおりに速くはならない／ノイズに埋もれる規模で語らない
- 復習3      : 受け渡しの鎖（エッジに逃がすと rps は減るが単価は下がらない）
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from infrakit.cost import (  # noqa: E402
    HostedAPI, SelfHosted, breakeven_requests_per_hour,
)
from src.review03.handoff_sweep import (  # noqa: E402
    DEVICES, classifier_footprint, cost_per_1k, generation_footprint, insight,
    memo, per_instance_rps, replicas_for, sweep, table, upstream_rps,
)
from src.session02.metrics import min_samples, rebuild_total  # noqa: E402
from src.session09.scaling import (  # noqa: E402
    POINTS, Slo, best_point, cpu_blind_spot, plan_capacity,
    saturation_concurrency, target_queue_len,
)
from src.session10.inference_metrics import SAMPLES, adapt  # noqa: E402
from src.session11.edge_budget import (  # noqa: E402
    Footprint, fits, kv_mb, rtt_floor_ms,
)

failures: list[str] = []
checked = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global checked
    checked += 1
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def near(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def raises(fn) -> bool:
    """不正な入力を入口で弾いているかを確かめる（黙って通さないこと）。"""
    try:
        fn()
    except ValueError:
        return True
    return False


# --- ① 実測値（2026-08-15 実測 / aarch64 / CPU 2コア / メモリ 5.8GB /
#     Python 3.12.13 / llama.cpp -t 2）。関係の検証にだけ使う ---------------
GGUF_MB = {"f16": 948.1, "q8_0": 506.5, "q4_k_m": 379.4}
TTFT_P50 = {"f16": 124.0, "q8_0": 61.0, "q4_k_m": 144.0}
TPOT_P50 = {"f16": 26.54, "q8_0": 14.63, "q4_k_m": 19.58}

ONNX_FP32_MB, ONNX_INT8_MB = 70.13, 17.56
ONNX_FP32_P50, ONNX_INT8_P50 = 1.12, 0.29
MAX_PROB_DIFF = 0.001344
NOISE_P50 = 0.15        # 隠れ層 1536（11.3 MB）で測った定常 p50
FLOOR_MS = 1.0          # src/session12/scale_check.py の FLOOR_MS と同じ値

# --- ③ 前提値 ---------------------------------------------------------------
SLO_MS = 100.0          # 一次応答の SLO（サービスレベル目標）
API = HostedAPI(input_price_per_1m=0.8, output_price_per_1m=3.2,
                input_tokens=300.0, output_tokens=48.0)
BASE = SelfHosted(hourly_cost=1.0, instances=3, rps_per_instance=1.13,
                  utilization=0.7)

# ---------------------------------------------------------------------------
# 1. セッション2・3・4：測ってから動作点を選ぶ
# ---------------------------------------------------------------------------
print("=== セッション2・3・4：動作点は「rps が最大の点」ではない ===")

point = best_point(slo=Slo())
sat = saturation_concurrency()
saturated = next(p for p in POINTS if p.concurrency == sat)

check("飽和点は並列4（伸びが止まり TTFT が悪化する最初の点）", sat == 4,
      f"スループット {POINTS[1].throughput_tps} → {POINTS[2].throughput_tps} tok/s "
      f"／TTFT p50 {POINTS[1].ttft_p50_ms:.0f} → {POINTS[2].ttft_p50_ms:.0f} ms")
check("動作点は並列2（SLO を満たす中で rps が最大）", point.concurrency == 2,
      f"TTFT p95 {point.ttft_p95_ms:.0f} ms ≦ 1000 ms")
check("rps が最大の点（飽和点）は動作点にならない",
      saturated.throughput_rps > point.throughput_rps
      and not Slo().satisfied_by(saturated),
      f"飽和点 {saturated.throughput_rps} rps は動作点 {point.throughput_rps} rps "
      f"より高いが TTFT p95 {saturated.ttft_p95_ms:.0f} ms で SLO 違反")
check("並列2 の TPOT は並列1 の約1.9倍（スロットを分け合うと遅くなる）",
      1.8 < POINTS[1].tpot_p50_ms / POINTS[0].tpot_p50_ms < 2.0,
      f"{POINTS[1].tpot_p50_ms / POINTS[0].tpot_p50_ms:.2f} 倍")

total_q8 = rebuild_total(TTFT_P50["q8_0"], TPOT_P50["q8_0"], 48)
total_q4 = rebuild_total(TTFT_P50["q4_k_m"], TPOT_P50["q4_k_m"], 48)
check("サイズの大きい Q8_0 のほうが総時間が短い（小さいほど速いとは限らない）",
      GGUF_MB["q8_0"] > GGUF_MB["q4_k_m"] and total_q8 < total_q4,
      f"Q8_0 {GGUF_MB['q8_0']:.1f}MB / {total_q8:.0f}ms vs "
      f"Q4_K_M {GGUF_MB['q4_k_m']:.1f}MB / {total_q4:.0f}ms")
check("p95 を名乗るには 20 件、p99 には 100 件が必要",
      min_samples(0.95) == 20 and min_samples(0.99) == 100)

# ---------------------------------------------------------------------------
# 2. セッション9：CPU 使用率の死角と、しきい値の置き場所
# ---------------------------------------------------------------------------
print("\n=== セッション9：計算量が同じ2点を CPU では区別できない ===")

blind = cpu_blind_spot()
check("スループットはほぼ同じ（1.02 倍）", near(round(blind.throughput_ratio, 2), 1.02),
      f"{blind.throughput_ratio:.4f} 倍")
check("TPOT もほぼ同じ（0.98 倍）", near(round(blind.tpot_ratio, 2), 0.98),
      f"{blind.tpot_ratio:.4f} 倍")
check("TTFT p95 だけが 20.6 倍に壊れる", near(round(blind.ttft_p95_ratio, 1), 20.6),
      f"{blind.ttft_p95_ratio:.2f} 倍")
check("スロット使用率は2点で同じ（1.0 で頭打ち）", blind.same_slot_utilization,
      "どちらも 100%。区別できるのはキュー長だけ")
check("キュー長なら区別できる（0 件 と 2 件）",
      blind.healthy.queue_len() == 0 and blind.saturated.queue_len() == 2)

check("キュー長のしきい値は飽和点の手前（1.0 件/本）",
      near(target_queue_len(), 1.0)
      and target_queue_len() < max(sat - 2, 0),
      f"飽和時 {max(sat - 2, 0)} 件の半分 = {target_queue_len():.1f} 件")
check("1本に安全に任せられるのは 0.79 rps（ヘッドルーム 30%）",
      near(round(plan_capacity().per_instance_rps, 2), 0.79),
      f"{plan_capacity().per_instance_rps:.4f} rps")

# ---------------------------------------------------------------------------
# 3. セッション10：アダプタ層は欠測を 0 で埋めない
# ---------------------------------------------------------------------------
print("\n=== セッション10：欠測は欠測として持ち歩く ===")

sat_m = adapt(SAMPLES["saturated"])
healthy_m = adapt(SAMPLES["healthy"])
check("飽和した状態はキュー長 2 件、健全な状態は 0 件",
      near(sat_m.values["inference_queue_length"], 2.0)
      and near(healthy_m.values["inference_queue_length"], 0.0))
check("スロット使用率は両方 1.0 で区別できない",
      near(sat_m.values["inference_slot_utilization"], 1.0)
      and near(healthy_m.values["inference_slot_utilization"], 1.0),
      "スロット使用率は 1.0 で頭打ちになる")
check("どちらも欠測なし（そのまま HPA に渡せる）", sat_m.ok and healthy_m.ok)

nod = adapt(SAMPLES["no-deferred"])
check("待ちの項目が無いサンプルはキュー長が欠測になる",
      "inference_queue_length" in nod.missing and not nod.ok,
      f"欠測: {nod.missing}")
nod5 = adapt(SAMPLES["no-deferred"], gateway_stats={"inflight": 5})
check("ゲートウェイの inflight 5 件からキュー長 3 件を作れる",
      near(nod5.values["inference_queue_length"], 3.0)
      and "inference_queue_length" in nod5.derived and nod5.ok,
      "max(5 − 2, 0) = 3")

ren = adapt(SAMPLES["renamed"])
check("上流の名前が変わると2件が欠測になる（0 を入れない）",
      set(ren.missing) == {"inference_active_requests", "inference_queue_length"}
      and not ren.ok and "inference_slot_utilization" not in ren.values,
      f"欠測: {sorted(ren.missing)}")
check("欠測のときは「0 で埋めるな」と助言が出る",
      any("0 で埋めて" in line for line in ren.advice()),
      "0 は「待ちが無い」を意味してしまう")

# ---------------------------------------------------------------------------
# 4. セッション10：単価は利用率に反比例し、損益分岐は rps で動かない
# ---------------------------------------------------------------------------
print("\n=== セッション10：単価の式に何が現れるか ===")

cost_70 = BASE.cost_per_1k_requests
cost_10 = SelfHosted(1.0, 3, 1.13, 0.1).cost_per_1k_requests
cost_90 = SelfHosted(1.0, 3, 1.13, 0.9).cost_per_1k_requests
cost_100 = SelfHosted(1.0, 3, 1.13, 1.0).cost_per_1k_requests
cost_6inst = SelfHosted(1.0, 6, 1.13, 0.7).cost_per_1k_requests

check("利用率 70% の 1000リクエスト単価は 0.3512", near(round(cost_70, 4), 0.3512),
      f"{cost_70:.6f}")
check("利用率 10% と 90% では 9.00 倍の差（= 0.9 ÷ 0.1）",
      near(round(cost_10 / cost_90, 4), 9.0, 1e-6), f"{cost_10 / cost_90:.4f} 倍")
check("台数を倍にしても単価は変わらない（式で約分される）",
      near(cost_6inst, cost_70), f"3 本 {cost_70:.6f} / 6 本 {cost_6inst:.6f}")
check("ヘッドルーム 30% は単価 1.43 倍として現れる",
      near(round(cost_70 / cost_100, 2), 1.43), f"{cost_70 / cost_100:.4f} 倍")

check("API の 1000リクエスト単価は 0.3936",
      near(round(API.cost_per_1k_requests, 4), 0.3936),
      f"{API.cost_per_1k_requests:.7f}")
be = breakeven_requests_per_hour(BASE, API)
check("損益分岐は 7621.95 リクエスト/時（= 固定費 ÷ API の1リクエスト単価）",
      near(round(be, 2), 7621.95), f"{be:.2f} リクエスト/時（{be / 3600:.2f} rps）")
check("損益分岐は rps も利用率も変えても動かない（式に現れない）",
      near(breakeven_requests_per_hour(SelfHosted(1.0, 3, 1.15, 0.2), API), be),
      "動くのは単価と「その件数を捌けるか」だけ")
check("損益分岐はヘッドルームを残した能力の内側にある（達成できる）",
      be <= BASE.requests_per_hour,
      f"{be:.1f} ≦ {BASE.requests_per_hour:.1f} リクエスト/時")
check("いまの利用率では自前が API より安い",
      cost_70 < API.cost_per_1k_requests,
      f"自前 {cost_70:.4f} < API {API.cost_per_1k_requests:.4f}")
check("利用率 10% まで落ちると自前のほうが高くなる",
      cost_10 > API.cost_per_1k_requests,
      f"自前 {cost_10:.4f} > API {API.cost_per_1k_requests:.4f}")

cost_sat = SelfHosted(1.0, 3, saturated.throughput_rps, 0.7).cost_per_1k_requests
saving_pct = (1.0 - cost_sat / cost_70) * 100.0
check("飽和させても単価は 2% 未満しか下がらないのに体感は 20 倍以上悪くなる",
      1.0 < saving_pct < 2.5 and blind.ttft_p95_ratio > 20.0,
      f"単価 {saving_pct:.1f}% 安い／TTFT p95 {blind.ttft_p95_ratio:.1f} 倍")

# ---------------------------------------------------------------------------
# 5. 復習3：受け渡しの鎖（エッジに逃がしても単価は下がらない）
# ---------------------------------------------------------------------------
print("\n=== 復習3：エッジに逃がすと rps は減るが単価は上がる ===")

cases = sweep()
check("上流に届く rps は 5.00 → 2.50 → 1.00 → 0.25 と減る",
      all(a.served_rps > b.served_rps for a, b in zip(cases, cases[1:])),
      " → ".join(f"{c.served_rps:.2f}" for c in cases))
check("必要レプリカ数は 7 → 4 → 2 → 2（切り上げと下限で比例して減らない）",
      [c.replicas for c in cases] == [7, 4, 2, 2],
      f"{[c.replicas for c in cases]}")
check("1000リクエスト単価は単調に悪化する",
      all(a.cost_per_1k < b.cost_per_1k for a, b in zip(cases, cases[1:])),
      " → ".join(f"{c.cost_per_1k:.4f}" for c in cases))
check("単価は 0.3889 → 2.2222（5.7 倍）",
      [round(c.cost_per_1k, 4) for c in cases]
      == [0.3889, 0.4444, 0.5556, 2.2222]
      and near(round(cases[-1].cost_per_1k / cases[0].cost_per_1k, 1), 5.7),
      f"{cases[-1].cost_per_1k / cases[0].cost_per_1k:.2f} 倍")
check("利用率は 63.2% → 11.1% に落ちる（固定費を薄める相手が減る）",
      [round(c.utilization, 4) for c in cases]
      == [0.6321, 0.5531, 0.4425, 0.1106],
      " → ".join(f"{c.utilization:.1%}" for c in cases))
check("割合 0% では端末に何も置かない",
      not cases[0].on_edge and near(cases[0].edge_total_mb, 0.0))
check("割合が 0 より大きいケースは端末D に載る（85.12 MB）",
      all(c.edge_fits and near(round(c.edge_total_mb, 2), 85.12)
          for c in cases[1:]),
      f"余白 {cases[1].slack_mb:+.2f} MB")

all_edge = sweep(ratios=(1.0,))
check("割合 100% では単価が定義できない（0 で割らず inf を返す）",
      math.isinf(all_edge[0].cost_per_1k)
      and all_edge[0].replicas == 2 and near(all_edge[0].served_rps, 0.0),
      "表では「—（上流に届かない）」と表示する")
check("レプリカ数の下限が効く（0.25 rps でも 2 本）",
      replicas_for(0.25, per_instance_rps(1.13)) == 2
      and replicas_for(0.0, per_instance_rps(1.13)) == 2)
check("端末A に替えると余白が 1143.7 MB になる",
      near(round(sweep(device="A")[1].slack_mb, 1), 1143.7),
      f"上限 {DEVICES['A'].limit_mb:.1f} MB − 85.12 MB")
check("upstream_rps と cost_per_1k は単独でも同じ答えを返す",
      near(upstream_rps(5.0, 0.5), 2.5)
      and near(round(cost_per_1k(4, 2.5), 4), 0.4444))
check("入力の妥当性は入口で弾く（floor に 0 は許さない）",
      raises(lambda: replicas_for(1.0, 0.79, floor=0))
      and raises(lambda: upstream_rps(5.0, 1.5))
      and raises(lambda: sweep(device="Z")),
      "0 本を許すと最初の利用者がスケールの遅れぶん待つ設計が黙って通る")

text = table(cases)
check("表には単価と余白の列がある", "1000リクエスト単価" in text and "余白" in text)
lines = insight(cases)
check("気づきの文に「悪化」と下限の話が入る",
      any("悪化" in line for line in lines)
      and any("下限" in line for line in lines))
note = memo(cases, peak_rps=5.0, hourly=1.0, headroom=0.30, classifiers=2)
check("引き継げるメモに測定条件・前提の種別・再計算手順が入る",
      "2026-08-15" in note and "③ 前提値" in note and "再計算手順" in note,
      note.splitlines()[0])

# ---------------------------------------------------------------------------
# 6. セッション11・3：端末の予算は重みが支配する
# ---------------------------------------------------------------------------
print("\n=== セッション11・3：載るかどうかは重みで決まる ===")

gen = generation_footprint()
check("0.5B級 Q4_K_M のフットプリントは 553.4 MB（重み＋KVキャッシュ＋実行時）",
      near(round(gen.total_mb, 1), 553.4),
      f"{gen.weights_mb:.1f} + {gen.kv_mb:.1f} + {gen.runtime_mb:.1f}")
check("KVキャッシュは系列長 2048・1本で 24.0 MB", near(kv_mb("qwen05b", 2048), 24.0))
ok_gen, slack_gen = fits(DEVICES["D"], gen)
check("端末D には載らない（41.4 MB 超過）",
      not ok_gen and near(round(abs(slack_gen), 1), 41.4),
      f"上限 {DEVICES['D'].limit_mb:.1f} MB")
no_kv = Footprint(weights_mb=gen.weights_mb, kv_mb=0.0,
                  runtime_mb=gen.runtime_mb)
check("KVキャッシュを 0 にしても端末D には載らない（重みが支配的）",
      not fits(DEVICES["D"], no_kv)[0],
      f"{no_kv.total_mb:.1f} MB / 上限 {DEVICES['D'].limit_mb:.1f} MB")

cls = classifier_footprint(2)
ok_cls, slack_cls = fits(DEVICES["D"], cls)
check("int8 の分類器 2 本（85.12 MB）なら端末D に載る",
      ok_cls and near(round(cls.total_mb, 2), 85.12)
      and near(round(slack_cls, 2), 426.88), f"余白 {slack_cls:.2f} MB")
check("分類器は KVキャッシュを持たない（系列を持たないため）", near(cls.kv_mb, 0.0))
check("分類器のフットプリントは生成の 6 分の1未満",
      cls.total_mb / gen.total_mb < 1 / 6,
      f"{cls.total_mb / gen.total_mb:.1%}")

check("エッジ（0 km）では往復の物理的下限が 0 になる", near(rtt_floor_ms(0), 0.0))
check("8,000 km の往復の下限 80.0 ms は SLO 100.0 ms の 80% を食う",
      near(rtt_floor_ms(8000), 80.0)
      and near(rtt_floor_ms(8000) / SLO_MS, 0.8),
      "設定でもコードでも縮められない部分")
check("16,000 km は下限だけで SLO を超える", rtt_floor_ms(16000) > SLO_MS,
      f"{rtt_floor_ms(16000):.1f} ms")

# ---------------------------------------------------------------------------
# 7. セッション12：サイズ・速度・精度は別の量
# ---------------------------------------------------------------------------
print("\n=== セッション12：サイズ比のとおりには速くならない ===")

size_ratio = ONNX_INT8_MB / ONNX_FP32_MB
check("int8 のサイズは fp32 の 25.0%", abs(size_ratio - 0.25) < 0.005,
      f"{size_ratio:.1%}（{ONNX_FP32_MB} MB → {ONNX_INT8_MB} MB）")
check("int8 の定常 p50 は fp32 より短い", ONNX_INT8_P50 < ONNX_FP32_P50,
      f"{ONNX_FP32_P50} ms → {ONNX_INT8_P50} ms")
check("しかしサイズ比のとおりには短くならない（ノードが増えるため）",
      ONNX_INT8_P50 > ONNX_FP32_P50 * size_ratio,
      f"サイズ比どおりなら {ONNX_FP32_P50 * size_ratio:.4f} ms、"
      f"実測は {ONNX_INT8_P50} ms")
check("確率の最大差は合否条件（0.01）の内側で 0 ではない",
      0.0 < MAX_PROB_DIFF < 0.01, f"{MAX_PROB_DIFF}")
check("隠れ層 1536 の規模はノイズに埋もれる（定常 p50 が 1 ms 未満）",
      NOISE_P50 < FLOOR_MS,
      f"{NOISE_P50} ms < {FLOOR_MS} ms。この規模で倍率を語ってはいけない")
check("小さいほど速いとは限らない（GGUF は逆・ONNX は順で、両方向が起こる）",
      TPOT_P50["q8_0"] < TPOT_P50["q4_k_m"]
      and GGUF_MB["q8_0"] > GGUF_MB["q4_k_m"]
      and ONNX_INT8_P50 < ONNX_FP32_P50 and ONNX_INT8_MB < ONNX_FP32_MB,
      "サイズは速度の代理指標にならない。測って選ぶ")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print(f"\n復習3の検証はすべて成功しました（{checked} 件）。")
