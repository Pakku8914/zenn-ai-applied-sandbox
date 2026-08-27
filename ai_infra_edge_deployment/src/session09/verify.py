#!/usr/bin/env python3
"""セッション9の自己検証：何を見て増やすか・何本必要か。

**クラスタも kubectl も推論サーバも要らない。** 検証するのは3種類だけである。

  1. `k8s/hpa.yaml` を PyYAML で読み、推論固有の要件を満たしているか（静的検査）
  2. わざと壊した HPA が、期待した指摘に分解されるか
  3. 容量計画の計算（飽和点・動作点・遅れ・必要レプリカ数）が満たすべき**関係**

絶対値そのものではなく、次の関係を検証している。

  - 飽和した点と健全な点は、スループットも TPOT もほとんど同じで、
    TTFT の p95 だけが20倍以上違う（＝CPU 使用率では区別できない）
  - スケールの遅れは「発火」と「供給」に分かれ、支配する側が
    モデルの大きさで入れ替わる
  - 前提（ピークの rps・重みのサイズ）を変えると、同じマニフェストが落ちる
"""

from __future__ import annotations

import contextlib
import copy
import io
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.session08.budget import FETCH, VOLUME  # noqa: E402
from src.session08.manifest import (  # noqa: E402
    inference_container, pod_spec, probe_spec, workloads,
)
from src.session09.hpa_review import (  # noqa: E402
    DEFAULT_SCALE_DOWN, DEFAULT_SCALE_UP, explain, load_docs, review_docs,
    rules_of, workload_names,
)
from src.session09.lint_hpa import main as lint_main  # noqa: E402
from src.session09.plan import main as plan_main  # noqa: E402
from src.session09.scaling import (  # noqa: E402
    FIRST, LAST_RESORT, METRICS, POINTS, Slo, best_point, cpu_blind_spot,
    lag_for, little_check_rps, metric_table, plan_capacity, recommend_metric,
    saturation_concurrency, scale_up_vs_out, target_queue_len,
)

SANDBOX = Path(__file__).resolve().parents[2]
K8S = SANDBOX / "k8s"
HERE = SANDBOX / "src" / "session09"

HPA = K8S / "hpa.yaml"
REF = K8S / "inference-deployment.yaml"
BAD = HERE / "bad-hpa.yaml"

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def close(a: float, b: float, rel: float = 1e-6) -> bool:
    return math.isclose(a, b, rel_tol=rel, abs_tol=1e-9)


def run_cli(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = lint_main(argv)
    return code, buf.getvalue()


def run_plan(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = plan_main(argv)
    return code, buf.getvalue()


REF_DOCS = load_docs(REF)
HPA_DOCS = load_docs(HPA)
BAD_DOCS = load_docs(BAD)
KNOWN = workload_names(REF_DOCS)
PLAN = plan_capacity()


def reviewed(docs: list[dict], *, known=KNOWN, plan=PLAN):
    reviews = review_docs(docs, known=known, plan=plan)
    if len(reviews) != 1:
        raise SystemExit(f"HPA が1つではありません: {len(reviews)}")
    return reviews[0]


def broken(mutate) -> object:
    """`k8s/hpa.yaml` を1か所だけ壊してレビューする。"""
    docs = copy.deepcopy(HPA_DOCS)
    mutate(docs[0])
    return reviewed(docs)


# --- 1. 指標の選択 ------------------------------------------------------------
print("=== 指標の選択（何を見て増やすか）===")

table = metric_table()
check("指標の比較表は6行ある", len(table.splitlines()) == 8,
      f"ヘッダ2行 + {len(table.splitlines()) - 2} 行")
check("第一候補はキュー長だけ",
      [m.key for m in METRICS if m.role == FIRST] == ["queue_length"],
      " / ".join(m.name for m in METRICS if m.role == FIRST))
check("CPU 使用率と GPU 使用率は「最後の手段」",
      {m.key for m in METRICS if m.role == LAST_RESORT}
      == {"cpu_utilization", "gpu_utilization"})
check("発火に使ってよい指標は2つだけ",
      {m.key for m in METRICS if m.for_firing} == {"queue_length", "slot_utilization"})

choice, note = recommend_metric({"cpu_utilization", "queue_length"})
check("キュー長が取れるならキュー長を選ぶ",
      choice.key == "queue_length" and note == "", choice.name)
choice, note = recommend_metric({"cpu_utilization"})
check("CPU しか無いときは CPU を返すが、必ず注意書きが付く",
      choice.key == "cpu_utilization" and "キュー長を取り出せるように" in note,
      note[:40] + "…")
for bad_input, why in ((set(), "空"), ({"unknown_metric"}, "知らない指標")):
    try:
        recommend_metric(bad_input)
        check(f"{why}の入力は例外にする", False)
    except ValueError:
        check(f"{why}の入力は例外にする", True, "黙って CPU に倒れない")

# --- 2. 動作点と飽和点 --------------------------------------------------------
print("\n=== 動作点（測った点から選ぶ）===")

slo = Slo()
best = best_point()
check("飽和点は並列4（スロット2の2倍）", saturation_concurrency() == 4,
      "セッション4の定義：伸びが止まり TTFT が悪化する最初の点")
check("採用する動作点は並列2", best.concurrency == 2,
      f"TTFT p95 {best.ttft_p95_ms:.0f} ms / {best.throughput_rps} rps")
check("SLO を満たすのは並列1と並列2だけ",
      [p.concurrency for p in POINTS if slo.satisfied_by(p)] == [1, 2],
      slo.describe())
check("rps が最大の点（並列4）は SLO を満たさない",
      max(POINTS, key=lambda p: p.throughput_rps).concurrency == 4
      and not slo.satisfied_by(POINTS[2]),
      "「rps が最大」で選ぶと体感の壊れた点を選ぶ")
check("待ち行列の理屈で検算できる（スロット数 ÷ 総時間）",
      abs(little_check_rps(best) - best.throughput_rps) / best.throughput_rps < 0.10,
      f"2 ÷ {best.total_p50_ms / 1000:.3f} 秒 = {little_check_rps(best):.2f} rps ≒ "
      f"実測 {best.throughput_rps} rps")
check("キュー長は飽和点で2件、健全な点で0件",
      POINTS[1].queue_len() == 0 and POINTS[2].queue_len() == 2)
check("スロット使用率はどちらも100%（頭打ちになる）",
      close(POINTS[1].slot_utilization(), 1.0)
      and close(POINTS[2].slot_utilization(), 1.0),
      "だからスロット使用率だけでは超過が見えない")
check("キュー長のしきい値は飽和時の半分（1.0 件）",
      close(target_queue_len(), 1.0), "飽和してから発火しては遅い")

# --- 3. CPU 使用率の死角 ------------------------------------------------------
print("\n=== CPU 使用率で推論をスケールしてはいけない理由 ===")

bs = cpu_blind_spot()
check("健全な点と飽和した点でスループットはほぼ同じ", bs.throughput_ratio < 1.02,
      f"53.9 ÷ 53.0 = {bs.throughput_ratio:.2f} 倍")
check("TPOT もほぼ同じ", 0.95 < bs.tpot_ratio < 1.05,
      f"36.15 ÷ 36.74 = {bs.tpot_ratio:.2f} 倍")
check("それでも TTFT p95 は20倍以上悪化している", bs.ttft_p95_ratio > 20.0,
      f"2064 ÷ 100 = {bs.ttft_p95_ratio:.1f} 倍")
check("スロット使用率も同じ値になる", bs.same_slot_utilization,
      "計算量が同じなら CPU 使用率も同じ。区別できるのはキュー長だけ")
check("説明文に比が出る", "20.6 倍" in bs.explain() and "1.02 倍" in bs.explain())

print("\n=== 縦（スロット）と横（レプリカ）は別物 ===")
up, out = scale_up_vs_out()
check("横に並べたほうが rps は伸びる", out.rps > up.rps,
      f"{out.label} {out.rps:.2f} rps > {up.label} {up.rps} rps"
      "（別ノードに置く前提の掛け算）")
check("横に並べたほうが TPOT は速い", out.tpot_ms < up.tpot_ms,
      f"{out.tpot_ms} ms < {up.tpot_ms} ms")
check("ただし TTFT p95 は縦のほうが良い（連続バッチが効く）",
      up.ttft_p95_ms < out.ttft_p95_ms,
      f"{up.ttft_p95_ms:.0f} ms < {out.ttft_p95_ms:.0f} ms。どちらも SLO は満たす")
check("1インスタンスに2本流すと TPOT は約1.9倍になる",
      f"{POINTS[1].tpot_p50_ms / POINTS[0].tpot_p50_ms:.2f}" == "1.91",
      f"36.74 ÷ 19.19 = "
      f"{POINTS[1].tpot_p50_ms / POINTS[0].tpot_p50_ms:.2f} 倍。"
      f"rps の伸びは {POINTS[1].throughput_rps / POINTS[0].throughput_rps:.2f} 倍だけ")

# --- 4. スケールの遅れ --------------------------------------------------------
print("\n=== スケールの遅れ（発火 ＋ コールドスタート）===")

ref_container = inference_container(pod_spec(workloads(REF_DOCS)[0]))
readiness = probe_spec(ref_container.get("readinessProbe"))
lag = lag_for(FETCH, ready_detect_s=readiness.period_s)
check("readiness の検出遅れはマニフェストの periodSeconds と同じ",
      close(readiness.period_s, 10.0), f"readinessProbe periodSeconds "
      f"{readiness.period_s:.0f} 秒")
check("起動の見積りは 11.6 秒（セッション7・8と同じ値）",
      f"{lag.startup_s:.1f}" == "11.6")
check("遅れの合計は 56.6 秒", f"{lag.total_s:.1f}" == "56.6", lag.explain())
check("発火 30.0 秒 ＋ 供給 26.6 秒に分かれる",
      f"{lag.fire_s:.1f}" == "30.0" and f"{lag.provision_s:.1f}" == "26.6")
check("0.5B では発火側のほうが起動より長い", lag.fire_s > lag.startup_s,
      f"発火 {lag.fire_s:.1f} 秒 > 起動 {lag.startup_s:.1f} 秒。"
      f"支配している項目は「{lag.dominant}」")

lag_volume = lag_for(VOLUME)
saved = (lag.total_s - lag_volume.total_s) / lag.total_s * 100
check("PVC 方式で起動を縮めても合計は 6.7% しか減らない",
      f"{saved:.1f}" == "6.7" and lag_volume.total_s < lag.total_s,
      f"{lag.total_s:.1f} 秒 → {lag_volume.total_s:.1f} 秒。"
      "起動だけ速くしても効かない場合がある")

lag_8b = lag_for(FETCH, 4700.0)
check("8B 級に載せ替えると遅れは 115.1 秒になる",
      f"{lag_8b.total_s:.1f}" == "115.1" and f"{lag_8b.startup_s:.1f}" == "70.1",
      f"支配している項目は「{lag_8b.dominant}」に入れ替わる")
check("大きいモデルでは起動が支配する（縮める場所が変わる）",
      lag_8b.startup_s > lag_8b.fire_s
      and lag_8b.dominant == "起動（重み取得込み）")

lag_stab = lag_for(FETCH, stabilization_s=15.0)
check("スケールアウトの安定化はまるごと遅れに足される",
      f"{lag_stab.total_s:.1f}" == "71.6",
      "「増えすぎないように」待たせた秒数は、利用者が待つ秒数である")

# --- 5. 容量計画 --------------------------------------------------------------
print("\n=== 容量計画（何本必要か）===")

check("1インスタンスに任せる rps は 0.79", f"{PLAN.per_instance_rps:.2f}" == "0.79",
      f"1.13 rps × (1 − 0.30) = {PLAN.per_instance_rps:.4f}")
check("ピーク 5.00 rps には 7 本", PLAN.peak_replicas == 7,
      f"5.0 ÷ 0.79 = {PLAN.peak_rps / PLAN.per_instance_rps:.2f} → 切り上げ")
check("平常 0.50 rps には 1 本", PLAN.baseline_replicas == 1)
check("立ち上がりの吸収に 2 本", PLAN.headroom_replicas == 2,
      f"0.02 rps/s × {PLAN.lag.total_s:.1f} 秒 = {PLAN.burst_rps:.2f} rps")
check("minReplicas は 3（平常1 ＋ 吸収2、下限2）", PLAN.min_replicas == 3)
check("maxReplicas は 12（ピーク7 × 1.7）", PLAN.max_replicas == 12)
check("しきい値は 1.0 件/本", close(PLAN.target_queue_len, 1.0)
      and PLAN.saturation_queue_len == 2)
check("minReplicas を 0 にすると SLO の 56.6 倍待たせる",
      f"{PLAN.slo_multiple:.1f}" == "56.6",
      f"{PLAN.cold_start_wait_s:.1f} 秒 ÷ 1000 ms")

sat_point = POINTS[2]
sat_replicas = math.ceil(PLAN.peak_rps / (sat_point.throughput_rps * 0.70))
check("飽和した点の rps で数えても本数はほぼ同じ",
      sat_replicas == PLAN.peak_replicas,
      f"1.15 rps で数えても {sat_replicas} 本。"
      f"それでも TTFT p95 は {sat_point.ttft_p95_ms:.0f} ms（SLO 違反）になる。"
      "だから rps ではなく SLO で動作点を選ぶ")

steep = plan_capacity(ramp_rps_per_s=0.05)
check("立ち上がりが急なほど常時空けておく本数が増える",
      steep.headroom_replicas == 4 and steep.min_replicas == 5,
      f"0.05 rps/s → {steep.burst_rps:.2f} rps → {steep.headroom_replicas} 本")
plan_8b = plan_capacity(lag=lag_8b)
check("8B 級では遅れが伸びるぶん minReplicas も増える",
      plan_8b.headroom_replicas == 3 and plan_8b.min_replicas == 4,
      f"遅れ {lag_8b.total_s:.1f} 秒 → {plan_8b.burst_rps:.2f} rps")
plan_peak10 = plan_capacity(peak_rps=10.0)
check("ピークが倍になれば本数も倍近くになる（数え直せる）",
      plan_peak10.peak_replicas == 13 and plan_peak10.max_replicas == 23)
plan_no_room = plan_capacity(headroom=0.0)
check("ヘッドルームを 0 にすると本数は減るが逃げ場が無くなる",
      plan_no_room.peak_replicas == 5
      and plan_no_room.peak_replicas < PLAN.peak_replicas,
      "1本落ちた瞬間に飽和する")

for kwargs, why in (({"headroom": 1.0}, "ヘッドルーム 100%"),
                    ({"floor": 0}, "下限 0 本"),
                    ({"peak_rps": 0.0}, "ピーク 0 rps"),
                    ({"slo": Slo(10.0, 10.0)}, "誰も満たせない SLO")):
    try:
        plan_capacity(**kwargs)
        check(f"{why} は例外にする", False)
    except ValueError:
        check(f"{why} は例外にする", True)

report = PLAN.markdown()
for heading in ("## 1. 前提（変わったら数え直す入力）", "## 2. 動作点（実測から選ぶ）",
                "## 4. HPA に書く値", "## 5. 前提が変わったときの再計算手順"):
    check(f"引き継げるレポートに「{heading[3:]}」がある", heading in report)
check("レポートに測定条件が入っている", "2026-08-15 実測" in report)
check("レポートに飽和点と採用した点の印が付く",
      "満たさない（飽和点）" in report and "満たす（採用）" in report)

# --- 6. HPA の静的検査 --------------------------------------------------------
print("\n=== k8s/hpa.yaml の静的検査 ===")

hpa = reviewed(HPA_DOCS)
check("エラーは1件も無い", hpa.errors == [],
      " / ".join(f.rule for f in hpa.errors) or "なし")
check("警告も無い（Deployment と一緒に検査した場合）", hpa.warnings == [],
      " / ".join(f.rule for f in hpa.warnings) or "なし")
check("対象は Deployment/llama-inference", hpa.target == "Deployment/llama-inference")
check("minReplicas は計画どおり 3", hpa.min_replicas == PLAN.min_replicas)
check("maxReplicas はピークを満たす",
      hpa.max_replicas is not None and hpa.max_replicas >= PLAN.peak_replicas,
      f"max {hpa.max_replicas} ≧ ピーク {PLAN.peak_replicas} 本")
check("指標は待ちを表すものが1つだけ",
      len(hpa.metrics) == 1 and hpa.metrics[0].is_queue_like
      and not hpa.metrics[0].is_cpu, hpa.metrics[0].label())
check("しきい値は計画と同じ 1 件",
      close(hpa.metrics[0].value, PLAN.target_queue_len))
check("スケールアウトは待たない（安定化 0 秒・最大 4.0 本/分）",
      close(hpa.up.stabilization_s, 0.0)
      and close(hpa.up.rate_per_min(hpa.min_replicas), 4.0))
check("スケールインは保守的（安定化 600 秒・最大 0.5 本/分）",
      close(hpa.down.stabilization_s, 600.0)
      and close(hpa.down.rate_per_min(hpa.min_replicas), 0.5))
check("非対称になっている（出るのは遅く・入るのは早く）",
      hpa.down.stabilization_s > hpa.up.stabilization_s
      and hpa.down.rate_per_min(hpa.min_replicas)
      < hpa.up.rate_per_min(hpa.min_replicas))
check("内訳の表示に計画と遅れが出る",
      "計画の minReplicas 3" in explain(hpa)
      and "スケールの遅れ  : 56.6 秒" in explain(hpa))

alone = review_docs(HPA_DOCS, known=None, plan=PLAN)[0]
check("HPA 単独で検査すると「対象が確かめられない」と言われる",
      rules_of(alone.findings, "warn") == {"target-unverified"}
      and alone.errors == [],
      "HPA だけ見ても、名前が合っているかは分からない")

print("\n=== Kubernetes の既定値（behavior を書かないとどうなるか）===")
check("既定はスケールイン 300 秒・スケールアウト 0 秒",
      close(DEFAULT_SCALE_DOWN.stabilization_s, 300.0)
      and close(DEFAULT_SCALE_UP.stabilization_s, 0.0))
check("既定の削減幅は 15 秒あたり 100%（一気に minReplicas まで落ちる）",
      close(DEFAULT_SCALE_DOWN.rate_per_min(10), 40.0),
      "10 本なら1分で 40 本ぶん減らせる勢い")

# --- 7. アンチパターン集 ------------------------------------------------------
print("\n=== アンチパターン集（bad-hpa.yaml）===")

bad = reviewed(BAD_DOCS)
expected_errors = {"cpu-only-metric", "max-replicas-below-peak", "min-replicas-zero",
                   "scale-down-window", "target-missing"}
expected_warns = {"api-version", "cpu-target-high", "queue-metric-missing",
                  "scale-down-rate", "scale-up-slow"}
check("エラー5件が期待どおりに分解される",
      rules_of(bad.findings, "error") == expected_errors,
      f"{len(bad.errors)} 件: " + " / ".join(sorted(rules_of(bad.findings, "error"))))
check("警告5件が期待どおりに分解される",
      rules_of(bad.findings, "warn") == expected_warns,
      f"{len(bad.warnings)} 件: " + " / ".join(sorted(rules_of(bad.findings, "warn"))))
check("エラーが先に並ぶ（直す順番になっている）",
      [f.severity for f in bad.findings][:len(expected_errors)]
      == ["error"] * len(expected_errors))
check("スケールインのほうが速いことが数字で出る",
      bad.down.rate_per_min(1) > bad.up.rate_per_min(1),
      f"スケールイン {bad.down.rate_per_min(1):.1f} 本/分 > "
      f"スケールアウト {bad.up.rate_per_min(1):.1f} 本/分")

# --- 8. 1か所ずつ壊して確かめる ------------------------------------------------
print("\n=== 1か所ずつ壊すと何が出るか ===")


def set_min(h: dict, value: int) -> None:
    h["spec"]["minReplicas"] = value


def cpu_only(h: dict) -> None:
    h["spec"]["metrics"] = [{"type": "Resource",
                             "resource": {"name": "cpu",
                                          "target": {"type": "Utilization",
                                                     "averageUtilization": 60}}}]


cases = [
    ("minReplicas を 0 にする", lambda h: set_min(h, 0), "error", "min-replicas-zero"),
    ("minReplicas を 1 にする", lambda h: set_min(h, 1), "warn", "min-replicas-single"),
    ("minReplicas を 2 にする（計画は3）", lambda h: set_min(h, 2), "error",
     "min-replicas-below-plan"),
    ("maxReplicas を 3 にする", lambda h: h["spec"].__setitem__("maxReplicas", 3),
     "error", "max-replicas-below-peak"),
    ("指標を CPU 使用率だけにする", cpu_only, "error", "cpu-only-metric"),
    ("CPU 使用率を併用する",
     lambda h: h["spec"]["metrics"].append(
         {"type": "Resource", "resource": {"name": "cpu",
                                           "target": {"type": "Utilization",
                                                      "averageUtilization": 60}}}),
     "warn", "cpu-metric-present"),
    ("メモリ使用量を指標にする",
     lambda h: h["spec"]["metrics"].append(
         {"type": "Resource", "resource": {"name": "memory",
                                           "target": {"type": "Utilization",
                                                      "averageUtilization": 70}}}),
     "warn", "memory-metric"),
    ("指標をスロット使用率だけにする",
     lambda h: h["spec"]["metrics"][0]["pods"]["metric"].__setitem__(
         "name", "inference_slot_utilization"), "warn", "slot-metric-only"),
    ("しきい値を 3 件に緩める",
     lambda h: h["spec"]["metrics"][0]["pods"]["target"].__setitem__(
         "averageValue", "3"), "warn", "queue-threshold-above-plan"),
    ("Pods 指標を Value で書く",
     lambda h: h["spec"]["metrics"][0]["pods"]["target"].__setitem__(
         "type", "Value"), "error", "pods-target-type"),
    ("スケールインの安定化を 0 秒にする",
     lambda h: h["spec"]["behavior"]["scaleDown"].__setitem__(
         "stabilizationWindowSeconds", 0), "error", "scale-down-window"),
    ("behavior を消す", lambda h: h["spec"].pop("behavior"), "warn",
     "behavior-missing"),
    ("対象の名前を間違える",
     lambda h: h["spec"]["scaleTargetRef"].__setitem__("name", "llama-inferrence"),
     "error", "target-missing"),
]
for label, mutate, severity, rule in cases:
    review = broken(mutate)
    check(f"{label} → {rule}", rule in rules_of(review.findings, severity),
          " / ".join(sorted(rules_of(review.findings, severity))) or "指摘なし")

no_behavior = broken(lambda h: h["spec"].pop("behavior"))
check("behavior を消すと既定値（300 秒 / 0 秒）で評価される",
      close(no_behavior.down.stabilization_s, 300.0)
      and not no_behavior.down.explicit,
      "既定でも非対称ではあるが、削減幅が 100%/15秒なので一気に落ちる")

# --- 9. CLI の契約（終了コードと出力）------------------------------------------
print("\n=== CLI（CI に置ける形）===")

code, out = run_cli([str(HPA)])
check("HPA 単独は終了コード 0（警告1件）",
      code == 0 and "検出: エラー 0 件 / 警告 1 件" in out
      and "[WARN] target-unverified" in out, f"exit={code}")
code, out = run_cli(["--strict", str(HPA)])
check("--strict は警告でも失敗させる", code == 1, f"exit={code}")
code, out = run_cli(["--plan", "--explain", str(HPA), str(REF)])
check("Deployment と一緒に検査すると警告も 0 件",
      code == 0 and "検出: エラー 0 件 / 警告 0 件" in out, f"exit={code}")
check("--plan は計画の要約を1行で出す",
      "容量計画: ピーク 5.00 rps → 7 本 / minReplicas 3 / maxReplicas 12 / "
      "キュー長 1.0 件/本 / スケールの遅れ 56.6 秒" in out)
check("--explain は指標と behavior の内訳を出す",
      "指標            : Pods inference_queue_length AverageValue 1（待ちを表す指標）"
      in out and "スケールイン    : 安定化 600 秒 / 最大 0.5 本/分" in out)
check("HPA を持たないファイルはそう表示される",
      "検査対象の HorizontalPodAutoscaler がありません" in out)

code, out = run_cli(["--plan", str(BAD), str(REF)])
check("アンチパターン集は終了コード 1",
      code == 1 and "検出: エラー 5 件 / 警告 5 件" in out, f"exit={code}")
check("本文に載せた指摘がそのまま出力される",
      "[ERROR] cpu-only-metric" in out
      and "デコードはメモリ帯域律速なので" in out
      and "[ERROR] min-replicas-zero" in out
      and "[ERROR] target-missing" in out)

code, out = run_cli(["--plan", "--peak-rps", "20", str(HPA), str(REF)])
check("前提（ピーク）を変えると同じマニフェストが落ちる",
      code == 1 and "26 本必要です" in out,
      "20 rps ÷ 0.79 rps = 25.28 → 26 本。maxReplicas 12 では足りない")
code, out = run_cli(["--plan", "--weights-mib", "4700", str(HPA), str(REF)])
check("前提（重みのサイズ）を変えても落ちる",
      code == 1 and "計画では 4 本必要です" in out,
      "遅れが 115.1 秒に伸びるので、常時空けておく本数が増える")

code, out = run_plan(["--lag"])
check("plan.py --lag は遅れの内訳を出す",
      code == 0 and "スケールの遅れ 56.6 秒（発火 30.0 ＋ 供給 26.6）" in out
      and "支配している項目: メトリクスの周期" in out)
code, out = run_plan([])
check("plan.py は引き継げる容量計画を出す",
      code == 0 and "# 容量計画：みなと商事 ヘルプデスク回答 API" in out
      and "| `minReplicas` | 3 |" in out and "| `maxReplicas` | 12 |" in out)

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション9の検証はすべて成功しました。")
