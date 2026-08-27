#!/usr/bin/env python3
"""復習4（セッション2〜16）の自己検証。

    python src/review04/verify.py

検証するのは**絶対値ではなく関係**である。推論サーバも ONNX Runtime も要らない
（すべて式・文字列・定数の計算で完結するので、環境によってぶれない）。
レイテンシの絶対値を期待値に書いてはいけない（実行ごとに 2 倍程度ぶれるため）。

- セッション2 : p95 / p99 に必要な件数／条件が違うレポートは並べられない
- セッション3 : 小さいほど速いとは限らない／KVキャッシュは系列長で決まる
- セッション12: サイズ比は決定的、速度比は範囲でしか語れない
- セッション13: コア数付近が最速。超えても速くならず、ばらつきが増える
- セッション14: Flash と RAM は別の池／量子化は必要条件だが十分条件ではない
- セッション15: 段階展開は帯域を減らさない／件数の検査を失敗率より先に置く
- セッション16: 台数は整数なので、動作点が 2.5% 動くと結論が反転する
- 復習4      : 運用と判断の鎖（載るか -> 諦めるもの -> 配れるか -> 自前で持つか）
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.review04.ops_chain import (  # noqa: E402
    DEVICES, FLASH, FOOTPRINTS, OPTIONS_BY_POOL, RAM, SINGLE, chain,
    distribution, economics, fit_of, memo, options_when_unfit, table,
)
from src.session02.metrics import comparable, min_samples, rebuild_total  # noqa: E402
from src.session11.edge_budget import Footprint, fits  # noqa: E402
from src.session14.mcu_budget import (  # noqa: E402
    C12_PARAMS, DEVICE_E, MODEL_C12, MODEL_V, MODEL_W, bytes_per_param_needed,
    fits as fits_mcu, kv_tokens, max_params,
)
from src.session15.fleet import (  # noqa: E402
    CLIENT_TIMEOUT_S, DEVICE_COUNT, EQ_MAX_DIFF, FP32_MB, INT8_BYTES, INT8_MB,
    DeviceReport, VersionStat, check_payload, device_payload, fleet_totals,
    max_parallel_for_timeout, merge_buckets, per_device_seconds,
    plan_elapsed_hours, quantile_bucket, release_gate, rollout_gate,
    sample_fleet, stage_plan, telemetry_bytes, total_gb, transfer_seconds,
    version_mix,
)
from src.session15.ota import (  # noqa: E402
    DeviceSpec, Release, check_compatibility, version_lt,
)
from src.session16.decision import (  # noqa: E402
    API, EDGE, HYBRID, MODE_AUTO, MODE_FIXED, POINT, SCENARIOS, SELF, STAGES,
    WEIGHTS, Trigger, api_cost_per_1k, cost_ratio, gate_reasons,
    observe_days_total, ranking, ratios_monotonic, self_cost_per_1k,
    self_is_cheaper, survivors,
)

failures: list[str] = []
checked = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global checked
    checked += 1
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def near(a: float, b: float, tol: float = 1e-6) -> bool:
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
GGUF_MB = {"q8_0": 506.5, "q4_k_m": 379.4}
TTFT_P50 = {"q8_0": 61.0, "q4_k_m": 144.0}
TPOT_P50 = {"q8_0": 14.63, "q4_k_m": 19.58}

ONNX_FP32_MB, ONNX_INT8_MB = 70.13, 17.56
INT8_SPEEDUPS = (3.86, 3.77, 3.59, 3.84)   # 4回計測した定常 p50 の比
NOISE_P50, FLOOR_MS = 0.15, 1.0

# ① intra_op ごとの定常 p50 の範囲（2026-08-26 に5回計測）
THREAD_RANGE_MS = {1: (0.31, 0.33), 2: (0.17, 0.22), 4: (0.18, 0.34)}

S1, S2, S3 = SCENARIOS["s1"], SCENARIOS["s2"], SCENARIOS["s3"]

# ---------------------------------------------------------------------------
# 1. セッション2・3・12・13：測り方の規約と「範囲で語る」
# ---------------------------------------------------------------------------
print("=== セッション2・3・12・13：断定してよい数字とそうでない数字 ===")

check("p95 を名乗るには 20 件、p99 には 100 件が必要",
      min_samples(0.95) == 20 and min_samples(0.99) == 100)
check("条件が違うレポートは並べられない（違う項目名が返る）",
      comparable({"max_tokens": 48}, {"max_tokens": 24}) == ["max_tokens"]
      and comparable({"max_tokens": 48}, {"max_tokens": 48}) == [],
      "空リストなら並べてよい")

total_q8 = rebuild_total(TTFT_P50["q8_0"], TPOT_P50["q8_0"], 48)
total_q4 = rebuild_total(TTFT_P50["q4_k_m"], TPOT_P50["q4_k_m"], 48)
check("サイズの大きい Q8_0 のほうが総時間が短い（小さいほど速いとは限らない）",
      GGUF_MB["q8_0"] > GGUF_MB["q4_k_m"] and total_q8 < total_q4,
      f"Q8_0 {GGUF_MB['q8_0']:.1f}MB / {total_q8:.0f}ms vs "
      f"Q4_K_M {GGUF_MB['q4_k_m']:.1f}MB / {total_q4:.0f}ms")

size_ratio = ONNX_INT8_MB / ONNX_FP32_MB
check("int8 のサイズ比 25.0% は決定的（断定してよい）",
      abs(size_ratio - 0.25) < 0.005,
      f"{size_ratio:.1%}（{ONNX_FP32_MB} MB -> {ONNX_INT8_MB} MB）")
check("速度比は範囲でしか語れない（4回で 3.6〜3.9 倍の幅がある）",
      3.5 < min(INT8_SPEEDUPS) and max(INT8_SPEEDUPS) < 4.0
      and max(INT8_SPEEDUPS) - min(INT8_SPEEDUPS) > 0.2,
      f"{min(INT8_SPEEDUPS)}〜{max(INT8_SPEEDUPS)} 倍。1つの値で断定しない")

lo1, hi1 = THREAD_RANGE_MS[1]
lo2, hi2 = THREAD_RANGE_MS[2]
lo4, hi4 = THREAD_RANGE_MS[4]
check("コア数（2）が最速の記録を持つ", lo2 < lo4 and lo2 < lo1,
      f"最良: intra_op=1 {lo1} / 2 {lo2} / 4 {lo4} ms")
check("コア数を超えるとばらつきが増える", (hi4 - lo4) > (hi2 - lo2),
      f"幅: 2 は {hi2 - lo2:.2f} ms / 4 は {hi4 - lo4:.2f} ms")
check("「4 は遅い」と断定できない（範囲が重なっている）", lo4 < hi2,
      f"4 の最良 {lo4} ms < 2 の最悪 {hi2} ms。1回の測定で順位を語ると間違える")
check("ノイズの床に埋もれる規模では倍率を語れない", NOISE_P50 < FLOOR_MS,
      f"{NOISE_P50} ms < {FLOOR_MS} ms（隠れ層 1536 の規模）")

# ---------------------------------------------------------------------------
# 2. セッション14・11・3：池が2つある端末
# ---------------------------------------------------------------------------
print("\n=== セッション14・11・3：Flash と RAM は別の池 ===")

check("端末E の枠は Flash 563.20 KB / RAM 166.40 KB（③前提値からの②計算）",
      near(DEVICE_E.weights_limit_kb, 563.2) and near(DEVICE_E.arena_limit_kb, 166.4),
      f"{DEVICE_E.weights_limit_kb:.2f} KB / {DEVICE_E.arena_limit_kb:.2f} KB")
check("int8 にすると同じ枠に載るパラメータ数が fp32 の 4 倍になる",
      near(max_params(DEVICE_E.weights_limit_kb, 1.0)
           / max_params(DEVICE_E.weights_limit_kb, 4.0), 4.0),
      f"{max_params(DEVICE_E.weights_limit_kb, 1.0):,} 個 vs "
      f"{max_params(DEVICE_E.weights_limit_kb, 4.0):,} 個")
over_c12 = C12_PARAMS / max_params(DEVICE_E.weights_limit_kb, 1.0)
check("それでもセッション12の分類器は枠の 31.9 倍（量子化は十分条件ではない）",
      C12_PARAMS == 18_374_656 and round(over_c12, 1) == 31.9,
      f"{C12_PARAMS:,} パラメータ / {over_c12:.2f} 倍")
bpp = bytes_per_param_needed(DEVICE_E.weights_limit_kb, 500_000_000)
check("0.5B は 1bit 量子化でも 100 倍以上足りない", 0.125 / bpp > 100.0,
      f"1パラメータ {bpp:.6f} バイト（{bpp * 8:.4f} ビット）／"
      f"{0.125 / bpp:.1f} 倍足りない")
check("端末E のアリーナに置ける KVキャッシュは 0.5B で 13 トークン・8B級で 1 トークン",
      kv_tokens(DEVICE_E.arena_limit_kb, 12.00) == 13
      and kv_tokens(DEVICE_E.arena_limit_kb, 128.00) == 1)

v_int8 = fits_mcu(DEVICE_E, MODEL_V)
v_fp32 = fits_mcu(DEVICE_E, MODEL_V, bytes_per_param=4.0, act_bytes=4)
check("モデルV は int8 なら載る", v_int8.ok,
      f"重み {v_int8.weights_kb:.2f} KB / アリーナ {v_int8.arena_kb:.2f} KB")
check("fp32 では重みが Flash に入るのに RAM で落ちる（落ちる池が違う）",
      v_fp32.flash_ok and not v_fp32.ram_ok,
      f"重み {v_fp32.weights_kb:.2f} KB（Flash {v_fp32.flash_use:.1%}）／"
      f"アリーナ {v_fp32.arena_kb:.2f} KB（RAM {v_fp32.ram_use:.1%}）")
w_peak = fits_mcu(DEVICE_E, MODEL_W)
w_naive = fits_mcu(DEVICE_E, MODEL_W, naive=True)
check("同じモデルでも数え方で判定が変わる（ピークなら載る・素朴に足すと載らない）",
      w_peak.ok and not w_naive.ok,
      f"ピーク {w_peak.arena_kb:.2f} KB / 素朴 {w_naive.arena_kb:.2f} KB "
      f"（上限 {DEVICE_E.arena_limit_kb:.2f} KB）")
c12 = fits_mcu(DEVICE_E, MODEL_C12)
check("先に溢れる池はモデルの形で変わる（C12 は RAM に余裕があるのに Flash で落ちる）",
      c12.ram_ok and not c12.flash_ok,
      f"Flash {c12.flash_use:.1%} / RAM {c12.ram_use:.1%}")

ok_cls, slack_cls = fits(DEVICES["D"], FOOTPRINTS["classifier"])
ok_gen, slack_gen = fits(DEVICES["D"], FOOTPRINTS["0.5b"])
check("分類器 int8（67.56 MB）は端末D に載る",
      ok_cls and near(round(FOOTPRINTS["classifier"].total_mb, 2), 67.56)
      and near(round(slack_cls, 2), 444.44), f"余白 {slack_cls:+.2f} MB")
check("0.5B（553.4 MB）は端末D に 41.4 MB 足りない",
      not ok_gen and near(round(abs(slack_gen), 1), 41.4),
      f"{FOOTPRINTS['0.5b'].total_mb:.1f} MB / 上限 "
      f"{DEVICES['D'].limit_mb:.1f} MB")
no_kv = Footprint(weights_mb=FOOTPRINTS["0.5b"].weights_mb, kv_mb=0.0,
                  runtime_mb=FOOTPRINTS["0.5b"].runtime_mb)
check("KVキャッシュを 0 にしても端末D には載らない（重みが支配的）",
      not fits(DEVICES["D"], no_kv)[0], f"{no_kv.total_mb:.1f} MB")
ok_b, slack_b = fits(DEVICES["B"], FOOTPRINTS["0.5b"])
check("端末B には載るが余白が 61.0 MB しかない（載ると報告してはいけない行）",
      ok_b and near(round(slack_b, 1), 61.0),
      f"上限 {DEVICES['B'].limit_mb:.1f} MB − 553.4 MB = {slack_b:+.1f} MB")

# ---------------------------------------------------------------------------
# 3. セッション15：配ったあと
# ---------------------------------------------------------------------------
print("\n=== セッション15：段階展開は帯域を減らさない ===")

seconds_int8 = transfer_seconds(INT8_MB, DEVICE_COUNT)
seconds_fp32 = transfer_seconds(FP32_MB, DEVICE_COUNT)
check("int8 を 1,000 台に配ると 1,404.8 秒（②物理計算）",
      near(seconds_int8, 1404.8) and round(total_gb(INT8_MB, DEVICE_COUNT), 2) == 17.15,
      f"{seconds_int8:,.1f} 秒 / {total_gb(INT8_MB, DEVICE_COUNT):.2f} GB")
check("配布時間の比はサイズの比とぴったり一致する",
      near(seconds_fp32 / seconds_int8, FP32_MB / INT8_MB)
      and 3.9 < seconds_fp32 / seconds_int8 < 4.0,
      f"{seconds_fp32 / seconds_int8:.4f} 倍")
limit = max_parallel_for_timeout(INT8_MB)
check("タイムアウト 300 秒を守れる同時台数は 213 台（切り捨て）",
      limit == 213
      and per_device_seconds(INT8_MB, limit) <= CLIENT_TIMEOUT_S
      < per_device_seconds(INT8_MB, limit + 1),
      f"{limit} 台で 1台 {per_device_seconds(INT8_MB, limit):.1f} 秒、"
      f"{limit + 1} 台で {per_device_seconds(INT8_MB, limit + 1):.1f} 秒")
check("一斉に 1,000 台で落とすとタイムアウトを超える（リトライストームの入口）",
      per_device_seconds(INT8_MB, DEVICE_COUNT) > CLIENT_TIMEOUT_S,
      f"1台 {per_device_seconds(INT8_MB, DEVICE_COUNT):,.1f} 秒 > "
      f"{CLIENT_TIMEOUT_S:.0f} 秒")

stages = stage_plan()
check("段階展開の台数は 1 / 9 / 90 / 900（累積で数える）",
      [s.added for s in stages] == [1, 9, 90, 900]
      and [s.target for s in stages] == [1, 10, 100, 1000],
      "1% の段は 10 台ではなく 9 台")
check("段に分けても配布時間の合計は変わらない",
      near(sum(s.seconds for s in stages), seconds_int8),
      f"{sum(s.seconds for s in stages):,.1f} 秒。減るのは間違った版が届く台数")
check("観察を含めた所要は 72.4 時間（配布 0.4 時間・観察 72 時間）",
      round(plan_elapsed_hours(stages), 1) == 72.4
      and sum(s.observe_hours for s in stages[:-1]) == 72.0,
      f"{plan_elapsed_hours(stages):.2f} 時間")

fleet = sample_fleet()
stats = version_mix(fleet)
new, base, old = stats[0], stats[1], stats[2]
check("版別に集計すると新版だけが壊れている",
      (new.version, base.version, old.version) == ("1.3.0", "1.2.0", "1.1.0")
      and round(new.failure_rate * 100, 1) == 2.5
      and round(base.failure_rate * 100, 1) == 0.5
      and round(old.failure_rate * 100, 1) == 1.0,
      f"新版 {new.failure_rate:.1%} / 現行 {base.failure_rate:.1%} / "
      f"未更新 {old.failure_rate:.1%}")
totals = fleet_totals(fleet)
check("全体の失敗率だけを見ると新版の異常が見えない",
      totals.devices == 1000 and totals.inferences == 200_000
      and totals.failures == 1450 and near(totals.offline_ratio, 0.10),
      f"全体 {totals.failure_rate:.2%}（新版は {new.failure_rate:.1%}）／"
      f"オフライン {totals.offline_ratio:.0%}")
check("新版は失敗率の門で中止になる（許容は現行の 1.5 倍）",
      rollout_gate(new, base).verdict == "中止",
      f"許容 {base.failure_rate * 1.5:.3%} < 新版 {new.failure_rate:.3%}")
tiny = VersionStat(version="1.4.0", devices=1, ratio=0.001, inferences=100,
                   failures=5, offline=0, buckets=(0, 0, 0, 0, 0))
check("件数の検査を先に置くので、1台・100 件では保留になる",
      rollout_gate(tiny, base).verdict == "保留",
      "逆順にすると 5% という揺れた値で良い版を捨てる")
check("パーセンタイルは足せないが件数は足せる（新版の p90 の区間が1つ重い）",
      quantile_bucket(new.buckets, 0.90) == "2.0 ms 未満"
      and quantile_bucket(base.buckets, 0.90) == "1.0 ms 未満",
      f"新版 {quantile_bucket(new.buckets, 0.90)} / "
      f"現行 {quantile_bucket(base.buckets, 0.90)}")
check("区間しか答えられない（値そのものは合成できない）",
      quantile_bucket((0, 0, 0, 0, 0), 0.90) == "データなし",
      "端末から p95 の値を受け取って平均しても全体の p95 にはならない")
bad = DeviceReport(device_id="dev-9999", model_version="1.3.0", app_version="2.1.0",
                   last_seen_h=0.5, inferences=200, failures=1, buckets=(1, 2, 3))
check("境界を変えたバケットは混ぜられない", raises(lambda: merge_buckets([bad])),
      "境界は SLO から決めて、あとから変えない")
payload = device_payload(fleet[0])
check("送ってよい項目は許可リストで持つ（生の入力は1バイトも送らない）",
      check_payload(payload) is None
      and raises(lambda: check_payload({**payload, "raw_input": [1, 2, 3]})),
      f"許可された項目: {sorted(payload)}")
check("集約指標にすると転送量が 1,536 分の1になる",
      telemetry_bytes(raw=True) // telemetry_bytes() == 1536,
      f"生 {telemetry_bytes(raw=True):,} バイト -> 集約 "
      f"{telemetry_bytes():,} バイト")
check("配る前の門はセッション12の等価性の判定をそのまま使う",
      release_gate(EQ_MAX_DIFF, True).ok
      and not release_gate(0.02, True).ok
      and not release_gate(EQ_MAX_DIFF, False).ok,
      f"確率の最大差 {EQ_MAX_DIFF} は上限 0.01 の内側")

release = Release(model_id="classifier", version="1.3.0", sha256="0" * 64,
                  size_bytes=INT8_BYTES, min_app="2.0.0", max_app=None,
                  input_dim=384, n_classes=6)
spec = DeviceSpec(app_version="1.9.0", input_dim=256, n_classes=6, free_bytes=1000)
reasons = check_compatibility(release, spec)
check("互換性の理由は打ち切らずに全部返る（手元にない端末への往復を増やさない）",
      len(reasons) == 3, "／".join(reasons))
check("版は文字列のまま比べてはいけない",
      not version_lt("1.10.0", "1.9.0") and ("1.10.0" < "1.9.0"),
      "文字列比較では 1.10.0 < 1.9.0 と読まれる")

# ---------------------------------------------------------------------------
# 4. セッション16・9・10：整数の段差
# ---------------------------------------------------------------------------
print("\n=== セッション16・9・10：台数が整数だから結論が反転する ===")

check("動作点は実測値をそのまま使う（並列2・1.13 rps）",
      POINT.concurrency == 2 and POINT.throughput_rps == 1.13,
      f"1本の安全な能力 {S2.inputs.per_instance_rps:.4f} rps")
n_auto, n_fixed = S2.inputs.instances(MODE_AUTO), S2.inputs.instances(MODE_FIXED)
c_auto = self_cost_per_1k(S2.inputs, MODE_AUTO)
c_fixed = self_cost_per_1k(S2.inputs, MODE_FIXED)
api_1k = api_cost_per_1k(S2.inputs)
check("同じ件数でも運転の仕方で結論が反転する",
      n_auto == 5 and n_fixed == 15 and c_auto < api_1k < c_fixed,
      f"オート{n_auto}本 {c_auto:.4f} < API {api_1k:.4f} < 固定{n_fixed}本 "
      f"{c_fixed:.4f}")
check("単価は 0.3600 / 1.0800 / API 0.3936（式で決まる値）",
      round(c_auto, 4) == 0.36 and round(c_fixed, 4) == 1.08
      and round(api_1k, 4) == 0.3936)
check("件数が2桁少ないと自前は 36.59 倍高い（桁で開いた差）",
      not self_is_cheaper(S1.inputs) and round(cost_ratio(S1, SELF), 2) == 36.59,
      f"自前 {self_cost_per_1k(S1.inputs):.4f} / API "
      f"{api_cost_per_1k(S1.inputs):.4f}")

down = replace(S2.inputs, point_rps=1.13 * 0.975)
up = replace(S2.inputs, point_rps=1.13 * 1.10)
check("動作点が 2.5% 落ちるだけで台数が1本増え、結論が反転する",
      down.instances(MODE_AUTO) == 6 and not self_is_cheaper(down),
      f"{down.instances(MODE_AUTO)} 本 / 単価 "
      f"{self_cost_per_1k(down):.4f} > API {api_1k:.4f}")
check("感度は非対称（動作点が 10% 良くなっても結論は変わらない）",
      up.instances(MODE_AUTO) == 5 and self_is_cheaper(up),
      "台数が減らないので単価も変わらない")

check("ゲートで生き残る案はシナリオごとに変わる",
      survivors(S1) == [API, SELF] and survivors(S3) == [EDGE, HYBRID],
      f"S1 {survivors(S1)} / S3 {survivors(S3)}")
check("S1 のハイブリッドは人員のゲートで落ちる",
      any("運用人員" in x for x in gate_reasons(S1, HYBRID)),
      "／".join(gate_reasons(S1, HYBRID)))
check("重みを変えると1位が入れ替わる（スコアは根拠にならない）",
      ranking(S1, WEIGHTS[0])[0][0] == API
      and ranking(S1, WEIGHTS[1])[0][0] == SELF,
      f"{WEIGHTS[0].key}: {ranking(S1, WEIGHTS[0])[0][0]} / "
      f"{WEIGHTS[1].key}: {ranking(S1, WEIGHTS[1])[0][0]}")
check("移行計画は影運転から始まり、割合は単調に増え、全段に撤退条件がある",
      STAGES[0].ratio == 0.0 and ratios_monotonic()
      and all(s.retreat for s in STAGES) and observe_days_total() == 29,
      f"観察の合計 {observe_days_total()} 日")
check("しきい値の無いトリガーは作れない",
      raises(lambda: Trigger("状況が変わったら見直す", "", "", "見直す", "")),
      "5要素すべてが埋まっていないと発火しない")

# ---------------------------------------------------------------------------
# 5. 復習4：運用と判断の鎖
# ---------------------------------------------------------------------------
print("\n=== 復習4：載るか -> 諦めるもの -> 配れるか -> 自前で持つか ===")

fit_d = fit_of("D", "classifier")
fit_e = fit_of("E", "classifier")
fit_e_llm = fit_of("E", "0.5b")
check("池の数が違っても同じ形の結果が返る",
      fit_d.pools == 1 and fit_e.pools == 2
      and fit_d.tight_pool == SINGLE and fit_e.tight_pool == FLASH,
      f"{fit_d.device}: {fit_d.tight_pool} / {fit_e.device}: {fit_e.tight_pool}")
check("分類器 int8 は端末D に載り、端末E には Flash 枠の 31.9 倍で載らない",
      fit_d.ok and not fit_e.ok and round(fit_e.over, 1) == 31.9,
      f"端末D {fit_d.over:.2f} 倍 / 端末E {fit_e.over:.2f} 倍")
check("0.5B は端末E では両方の池で溢れる（Flash が先に効く）",
      not fit_e_llm.ok and fit_e_llm.over > 600.0
      and fit_e_llm.tight_pool == FLASH,
      f"上限比 {fit_e_llm.over:.2f} 倍")
check("選択肢は詰まっている池で順序が変わる",
      "量子化" in options_when_unfit(fit_e_llm)[0]
      and "入力を小さくする" in OPTIONS_BY_POOL[RAM][0]
      and "量子化" in OPTIONS_BY_POOL[SINGLE][0],
      f"Flash 側の先頭: {options_when_unfit(fit_e_llm)[0]}")
check("載る場合は余白の警告を返す（載るで終わらせない）",
      "載るので選択肢は不要" in options_when_unfit(fit_d)[0]
      and len(options_when_unfit(fit_d)) == 1)
check("未知の端末名・モデル名は入口で弾く",
      raises(lambda: fit_of("Z", "classifier"))
      and raises(lambda: fit_of("A", "8b")))

dist_int8 = distribution(INT8_MB)
dist_llm = distribution(379.4)
check("配布の見積りはセッション15の関数をそのまま使う",
      near(dist_int8.seconds, 1404.8) and dist_int8.max_parallel == 213
      and dist_int8.waves_at_max == 5
      and dist_int8.stage_added == (1, 9, 90, 900),
      f"{dist_int8.seconds:,.1f} 秒 / 同時 {dist_int8.max_parallel} 台 / "
      f"{dist_int8.waves_at_max} 波")
check("配るものが大きくなると同時台数の上限が下がる",
      dist_llm.max_parallel == 9 and near(dist_llm.seconds, 30352.0),
      f"0.5B の重み 379.4 MB: {dist_llm.seconds:,.1f} 秒 / 同時 "
      f"{dist_llm.max_parallel} 台")
check("0 台への配布は入口で弾く",
      raises(lambda: distribution(INT8_MB, devices=0))
      and raises(lambda: distribution(INT8_MB, timeout_s=0.0)))

econ_big, econ_small = economics(10_000_000.0), economics(100_000.0)
check("台数が1本増える月間件数は 1,025.1 万件（閉じた式で出る）",
      abs(econ_big.step_up_monthly - 10_251_360.0) < 1.0
      and econ_big.instances_auto == 5,
      f"{econ_big.step_up_monthly / 10000:,.1f} 万件")
check("台数が1本増える動作点は 0.7716 rps（1本）＝ −2.5%",
      near(econ_big.step_down_rps, 0.7716049382716049, 1e-9)
      and round(econ_big.step_down_pct, 1) == -2.5,
      f"{econ_big.step_down_rps:.4f} rps（{econ_big.step_down_pct:+.2f}%）")
check("走査で求めた反転点と、平均 rps ÷ 台数 が一致する",
      near(econ_big.step_down_rps,
           econ_big.avg_rps / econ_big.instances_auto, 1e-12),
      "反転は切り上げの段差を越えた瞬間だけ起きる")
check("件数が2桁少ないと結論が反転し、台数は下限で決まる",
      not econ_small.cheaper and econ_big.cheaper
      and econ_small.floor_binding and not econ_big.floor_binding,
      f"月 10 万件: 単価 {econ_small.cost_auto:.4f} > API "
      f"{econ_small.api_cost:.4f}（{econ_small.instances_auto} 本・下限が効く）")
check("件数が 0 以下の前提は受け取らない", raises(lambda: economics(0.0)))

built = chain()
text, note = table(built), memo(built)
check("表には根拠の列があり、どのセッションの計算かが追える",
      "根拠" in text and "S14" in text and "S15" in text,
      text.splitlines()[0])
check("引き継げるメモに測定条件・種別・再計算手順が入る",
      "2026-08-15" in note and "③ 前提値" in note and "再計算手順" in note
      and "未実測" in note,
      note.splitlines()[0])
check("メモは絶対値を約束しない（扱うのはぶれない算術だけ）",
      "絶対値は再現しません" in note and "リトライストーム" in note,
      "レイテンシの期待値はこの鎖に1つも入っていない")

print(f"\n検証 {checked} 件")
if failures:
    print(f"NG {len(failures)} 件: " + " / ".join(failures))
    sys.exit(1)
print("復習4の検証はすべて成功しました（失敗 0 件）。")
