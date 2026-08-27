#!/usr/bin/env python3
"""セッション8の自己検証：推論ワークロードの Kubernetes マニフェスト。

**クラスタも kubectl も要らない。** app コンテナからは Kubernetes の API に
触れないので、検証するのは次の3種類だけである。

  1. `k8s/*.yaml` を PyYAML で読み、推論固有の要件を満たしているか（静的検査）
  2. わざと壊したマニフェストが、期待した指摘に分解されるか
  3. マニフェストに書く数字（メモリ要求・Probe の猶予・停止の猶予）が
     満たすべき**関係**（絶対値は環境で変わるので検証しない）

推論サーバは不要（SKIP_SERVER の有無に関係なく動く）。
"""

from __future__ import annotations

import contextlib
import copy
import io
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from infrakit.kvcache import LLAMA_8B  # noqa: E402
from src.session07.imageplan import GGUF_MB  # noqa: E402
from src.session08.budget import (  # noqa: E402
    FETCH, MIB, TPOT_P50_MS, TTFT_P50_MS, Overhead, ProbeSpec, VOLUME,
    budget_for, budget_for_8b, grace_required_s, kv_mib, max_request_seconds,
    rollout_seconds, rollout_waves, startup_breakdown, startup_seconds,
    surge_memory_mib, weights_mib_for,
)
from src.session08.lint_manifest import main as lint_main  # noqa: E402
from src.session08.manifest import (  # noqa: E402
    ReviewInputs, inference_container, load_docs, load_docs_text, parse_memory,
    pod_spec, review_docs, rules_of, workloads,
)

SANDBOX = Path(__file__).resolve().parents[2]
K8S = SANDBOX / "k8s"
HERE = SANDBOX / "src" / "session08"

REF = K8S / "inference-deployment.yaml"
PVC = K8S / "inference-pvc.yaml"
GPU = K8S / "gpu-inference.yaml"
KIND = K8S / "kind-cluster.yaml"
BAD = HERE / "bad-probes.yaml"

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-6)


def only_review(path: Path, inputs: ReviewInputs | None = None):
    reviews = review_docs(load_docs(path), inputs)
    if len(reviews) != 1:
        raise SystemExit(f"{path} のワークロードが1つではありません: {len(reviews)}")
    return reviews[0]


def server_of(docs: list[dict]) -> dict:
    """1つ目のワークロードの推論コンテナ（書き換えて実験するために取り出す）。"""
    container = inference_container(pod_spec(workloads(docs)[0]))
    if container is None:
        raise SystemExit("推論コンテナが見つかりません")
    return container


def run_cli(argv: list[str]) -> tuple[int, str]:
    """CLI を関数として呼び、終了コードと出力を受け取る。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = lint_main(argv)
    return code, buf.getvalue()


# --- 1. 参照マニフェスト（初期化コンテナ方式）--------------------------------
print("=== 参照マニフェスト（初期化コンテナで重みを配置）===")

ref_docs = load_docs(REF)
ref = only_review(REF)

check("検査対象のワークロードは1つ", ref.where == "Deployment/llama-inference:llama",
      ref.where)
check("エラーは1件も無い", ref.errors == [],
      " / ".join(f.rule for f in ref.errors) or "なし")
check("残っている警告は理由を書いた2つだけ",
      rules_of(ref.findings, "warn") == {"image-digest", "probe-paths-shared"},
      " / ".join(sorted(rules_of(ref.findings, "warn"))))
check("重みの出所がマニフェストから追える", ref.placement.source == "initContainer",
      ref.placement.label)
check("推論コンテナは重みを読み取り専用でマウントしている",
      any(m.get("name") == "model-cache" and m.get("readOnly") is True
          for m in server_of(ref_docs).get("volumeMounts") or []))

print("\n=== メモリ要求（重み ＋ KVキャッシュ ＋ 上乗せ）===")
check("KVキャッシュは -c 2048 で 24.0 MiB", close(ref.budget.kv_mib, 24.0),
      f"12,288 バイト × 2048 = {ref.budget.kv_mib:.1f} MiB")
check("式の答えは 740.1 MiB", f"{ref.budget.required_mib:.1f}" == "740.1",
      ref.budget.explain())
check("マニフェストの値は式の答え以上",
      ref.requests_mem_bytes >= ref.budget.required_bytes,
      f"requests {ref.requests_mem_bytes / MIB:.1f}Mi ≧ "
      f"必要 {ref.budget.required_mib:.1f}Mi")
check("64 刻みで切り上げた 768Mi になる", ref.budget.quantity() == "768Mi",
      "切り下げて 704Mi にすると足りない")
check("requests と limits が同じ（Guaranteed）",
      close(ref.requests_mem_bytes, ref.limits_mem_bytes)
      and close(ref.requests_cpu, ref.limits_cpu),
      f"memory {ref.requests_mem_bytes / MIB:.0f}Mi / cpu {ref.requests_cpu:g}")
check("スレッド数は limits.cpu を超えない", ref.threads <= ref.limits_cpu,
      f"-t {ref.threads} ≦ limits.cpu {ref.limits_cpu:g}")

print("\n=== Probe 3種の役割分担 ===")
check("startupProbe の猶予は 305 秒", close(ref.startup.budget_s, 305.0),
      ref.startup.describe())
check("起動の見積りは 11.6 秒（セッション7の仮定）",
      f"{ref.startup_estimate_s:.1f}" == "11.6",
      f"{startup_breakdown(FETCH, 379.4)['重み取得']:.1f} 秒の重み取得を含む")
check("startupProbe の猶予は見積りの20倍以上ある",
      ref.startup.budget_s > ref.startup_estimate_s * 20,
      "モデルを載せ替えても足りるように取ってある")
check("startupProbe の猶予は readinessProbe の猶予より長い",
      ref.startup.budget_s > ref.readiness.budget_s,
      f"startup {ref.startup.budget_s:.0f} 秒 > readiness "
      f"{ref.readiness.budget_s:.0f} 秒")
check("readinessProbe は HTTP でロード完了を見ている",
      ref.readiness.kind == "httpGet" and ref.readiness.path == "/health",
      f"{ref.readiness.kind} {ref.readiness.path}")
check("livenessProbe の猶予はロードの見積りより長い",
      ref.liveness.budget_s > ref.startup_estimate_s,
      f"liveness {ref.liveness.budget_s:.0f} 秒 > 見積り "
      f"{ref.startup_estimate_s:.1f} 秒")
check("livenessProbe の猶予は 30 秒以上（生成中の遅れで誤爆しない）",
      ref.liveness.budget_s >= 30.0, ref.liveness.describe())

print("\n=== 停止とロールアウト ===")
check("停止の猶予は必要量を満たす", ref.grace_s >= ref.grace_required_s,
      f"必要 {ref.grace_required_s:.1f} 秒 / 設定 {ref.grace_s:.0f} 秒")
check("maxUnavailable は 0（受け皿を空にしない）",
      "max-unavailable" not in rules_of(ref.findings, "error"))
check("replicas は2本以上", ref.replicas >= 2, f"replicas {ref.replicas}")

long_gen = only_review(REF, ReviewInputs(max_tokens=2048))
check("生成上限 2048 でも 60 秒でぎりぎり足りる",
      "grace-too-short" not in rules_of(long_gen.findings, "error"),
      f"必要 {long_gen.grace_required_s:.1f} 秒 / 設定 {long_gen.grace_s:.0f} 秒")
too_long = only_review(REF, ReviewInputs(max_tokens=4096))
check("生成上限 4096 にすると足りなくなる（前提が変われば設定も変わる）",
      "grace-too-short" in rules_of(too_long.findings, "error")
      and f"{too_long.grace_required_s:.1f}" == "98.8",
      f"必要 {too_long.grace_required_s:.1f} 秒 / 設定 {too_long.grace_s:.0f} 秒")

# --- 2. PVC 方式 -------------------------------------------------------------
print("\n=== PVC 方式（重みは共有ボリュームにある）===")
pvc = only_review(PVC)
check("エラーは1件も無い", pvc.errors == [],
      " / ".join(f.rule for f in pvc.errors) or "なし")
check("警告は参照マニフェストと同じ2つ",
      rules_of(pvc.findings, "warn") == {"image-digest", "probe-paths-shared"},
      " / ".join(sorted(rules_of(pvc.findings, "warn"))))
check("重みの出所は PVC で、読み取り専用でマウントしている",
      pvc.placement.source == "pvc" and pvc.placement.read_only,
      pvc.placement.label)
check("起動の見積りは初期化コンテナ方式より短い（重みを運ばない）",
      pvc.startup_estimate_s < ref.startup_estimate_s,
      f"{pvc.startup_estimate_s:.1f} 秒 < {ref.startup_estimate_s:.1f} 秒")
check("だから startupProbe の猶予も短くできる",
      pvc.startup.budget_s < ref.startup.budget_s
      and pvc.startup.budget_s > pvc.startup_estimate_s,
      f"猶予 {pvc.startup.budget_s:.0f} 秒 > 見積り {pvc.startup_estimate_s:.1f} 秒")
check("同じモデル・同じ -c なのでメモリ要求は同じ値になる",
      pvc.budget.quantity() == ref.budget.quantity(), pvc.budget.quantity())

# --- 3. GPU（概念。実機は無い）------------------------------------------------
print("\n=== GPU をスケジュールするマニフェスト（概念）===")
gpu = only_review(GPU)
check("エラーは1件も無い", gpu.errors == [],
      " / ".join(f.rule for f in gpu.errors) or "なし")
check("警告は「ダイジェスト未固定」と「重みのサイズが分からない」の2つ",
      rules_of(gpu.findings, "warn") == {"image-digest", "weights-size-unknown"},
      " / ".join(sorted(rules_of(gpu.findings, "warn"))))
check("知らない重みのサイズを勝手に埋めない（実測が無いものは None）",
      gpu.budget is None and weights_mib_for("/models/llama3-8b-instruct-q4.gguf")
      is None, "本書は 8B を動かしていないので実測が無い")

gpu_container = server_of(load_docs(GPU))
gpu_res = gpu_container["resources"]
check("GPU は limits にだけ書く（requests は自動的に同じ値になる）",
      gpu_res["limits"]["nvidia.com/gpu"] == 1
      and "nvidia.com/gpu" not in gpu_res["requests"])
check("VRAM の検算は 8B・-c 8192 で 7168Mi（重み 4700 MiB は仮定）",
      budget_for_8b(4700.0, 8192).quantity() == "7168Mi"
      and close(kv_mib(8192, LLAMA_8B), 1024.0),
      budget_for_8b(4700.0, 8192).explain())
check("-c を 4 倍にすると KVキャッシュも 4 倍になる",
      close(kv_mib(32768, LLAMA_8B), 4096.0)
      and budget_for_8b(4700.0, 32768).quantity() == "10816Mi",
      f"7168Mi → {budget_for_8b(4700.0, 32768).quantity()}")

GPU_REQUESTS_ONLY = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gpu-requests-only
spec:
  template:
    spec:
      containers:
        - name: llama
          image: ghcr.io/ggml-org/llama.cpp:full-cuda
          resources:
            requests:
              nvidia.com/gpu: 1
"""
GPU_FRACTIONAL = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gpu-fractional
spec:
  template:
    spec:
      nodeSelector:
        nvidia.com/gpu.present: "true"
      containers:
        - name: llama
          image: ghcr.io/ggml-org/llama.cpp:full-cuda
          resources:
            limits:
              nvidia.com/gpu: 0.5
"""
GPU_MISMATCH = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gpu-mismatch
spec:
  template:
    spec:
      nodeSelector:
        nvidia.com/gpu.present: "true"
      containers:
        - name: llama
          image: ghcr.io/ggml-org/llama.cpp:full-cuda
          resources:
            requests:
              nvidia.com/gpu: 1
            limits:
              nvidia.com/gpu: 2
"""
only_req = review_docs(load_docs_text(GPU_REQUESTS_ONLY))[0]
check("GPU を requests にだけ書くと指摘される",
      "gpu-requests-limits" in rules_of(only_req.findings, "error"))
check("ノード選択もテイント許容も無いと Pending の危険として警告される",
      "gpu-scheduling" in rules_of(only_req.findings, "warn"))
frac = review_docs(load_docs_text(GPU_FRACTIONAL))[0]
check("0.5 枚のような要求は受け付けられない",
      "gpu-fractional" in rules_of(frac.findings, "error"),
      "分けたいなら MIG か time-slicing を device plugin 側で設定する")
mismatch = review_docs(load_docs_text(GPU_MISMATCH))[0]
check("requests と limits が違う GPU 要求も指摘される",
      "gpu-requests-limits" in rules_of(mismatch.findings, "error"))

# --- 4. アンチパターン集 -----------------------------------------------------
print("\n=== アンチパターン集（bad-probes.yaml）===")
bad = only_review(BAD)
expected_errors = {
    "grace-too-short", "image-tag", "liveness-during-load", "max-unavailable",
    "memory-limits", "memory-requests", "readiness-not-http",
    "startup-probe-missing",
}
expected_warns = {
    "cpu-requests-lt-limits", "image-digest", "liveness-too-tight",
    "pdb-missing", "prestop-missing", "replicas-single",
    "threads-over-cpu-limit",
}
check("エラー8件が期待どおりに分解される",
      rules_of(bad.findings, "error") == expected_errors,
      f"{len(bad.errors)} 件: " + " / ".join(sorted(rules_of(bad.findings, "error"))))
check("警告7件が期待どおりに分解される",
      rules_of(bad.findings, "warn") == expected_warns,
      f"{len(bad.warnings)} 件")
check("エラーが先に並ぶ（直す順番になっている）",
      [f.severity for f in bad.findings][:len(expected_errors)]
      == ["error"] * len(expected_errors))
check("ロード中に殺される猶予の短さが数字で出る",
      close(bad.liveness.budget_s, 15.0)
      and bad.liveness.budget_s < bad.startup_estimate_s,
      f"猶予 {bad.liveness.budget_s:.0f} 秒 < 見積り {bad.startup_estimate_s:.1f} 秒")
check("メモリ要求の不足も数字で出る",
      bad.requests_mem_bytes < bad.budget.required_bytes,
      f"requests {bad.requests_mem_bytes / MIB:.0f}Mi < "
      f"必要 {bad.budget.required_mib:.1f}Mi（{bad.budget.explain()}）")

# --- 5. startupProbe を消すと何が起きるか ------------------------------------
print("\n=== startupProbe の有無で何が変わるか ===")

no_startup_small = copy.deepcopy(ref_docs)
del server_of(no_startup_small)["startupProbe"]
small = review_docs(no_startup_small)[0]
check("0.5B のままなら startupProbe を消しても liveness は誤爆しない",
      rules_of(small.findings, "error") == {"startup-probe-missing"},
      f"見積り {small.startup_estimate_s:.1f} 秒 < liveness の猶予 "
      f"{small.liveness.budget_s:.0f} 秒。**罠がまだ見えない**")

# 8B 級の重みサイズは本書に実測が無いので、仮定として登録して使う
# （lint が「サイズが分かりません」と言ったときの正しい対処もこれである）
GGUF_MB.setdefault("llama8b-q4", 4700.0)

big_docs = copy.deepcopy(ref_docs)
big_args = server_of(big_docs)["args"]
big_args[big_args.index("-m") + 1] = "/models/llama8b-q4.gguf"
big = review_docs(big_docs)[0]
check("8B に載せ替えると起動の見積りは 70.1 秒になる",
      f"{big.startup_estimate_s:.1f}" == "70.1",
      "重み取得 47.0 秒 ＋ モデルロード 16.5 秒が増える")
check("startupProbe があれば猶予 305 秒で足りる",
      not {"startup-budget", "liveness-during-load"}
      & rules_of(big.findings, "error"))
check("同時にメモリ要求の不足も指摘される（式が先に教えてくれる）",
      "memory-requests" in rules_of(big.findings, "error"), big.budget.explain())

no_startup_big = copy.deepcopy(big_docs)
del server_of(no_startup_big)["startupProbe"]
trap = review_docs(no_startup_big)[0]
check("startupProbe が無いまま大きいモデルに替えた日に殺され始める",
      {"startup-probe-missing", "liveness-during-load"}
      <= rules_of(trap.findings, "error"),
      f"見積り {trap.startup_estimate_s:.1f} 秒 > liveness の猶予 "
      f"{trap.liveness.budget_s:.0f} 秒 → CrashLoopBackOff")

tcp_ready = copy.deepcopy(ref_docs)
server_of(tcp_ready)["readinessProbe"] = {"tcpSocket": {"port": "http"},
                                          "periodSeconds": 5}
check("readinessProbe を「ポートが開いた」にすると指摘される",
      "readiness-not-http" in rules_of(review_docs(tcp_ready)[0].findings, "error"))

default_strategy = copy.deepcopy(ref_docs)
del workloads(default_strategy)[0]["spec"]["strategy"]
check("strategy を書かないと maxUnavailable は 25% になる",
      "max-unavailable"
      in rules_of(review_docs(default_strategy)[0].findings, "error"))

# --- 6. 数字が満たすべき関係 --------------------------------------------------
print("\n=== 数字が満たすべき関係（絶対値は検証しない）===")
check("KVキャッシュはコンテキスト長に比例する",
      close(kv_mib(1024), 12.0) and close(kv_mib(2048), 24.0)
      and close(kv_mib(4096), 48.0),
      "1024 → 12.0 / 2048 → 24.0 / 4096 → 48.0 MiB")
ratio = kv_mib(2048, LLAMA_8B) / kv_mib(2048)
check("8B 級は同じ系列長で 10 倍以上の KVキャッシュを食う",
      close(kv_mib(2048, LLAMA_8B), 256.0) and 10.0 < ratio < 11.0,
      f"256.0 MiB / 24.0 MiB = {ratio:.2f} 倍（1トークン 128.00KB と 12.00KB）")
check("コンテキストを伸ばすと必要メモリも増える",
      budget_for("qwen05b-q4_k_m.gguf", 1024).required_mib
      < budget_for("qwen05b-q4_k_m.gguf", 4096).required_mib)
check("量子化を強めると必要メモリは減る",
      budget_for("qwen05b-f16.gguf", 2048).required_mib
      > budget_for("qwen05b-q8_0.gguf", 2048).required_mib
      > budget_for("qwen05b-q4_k_m.gguf", 2048).required_mib,
      "重みのサイズがそのまま効く（2026-08-15 実測のサイズ）")
check("上乗せを増やせば要求も増える（つまみの向きが正しい）",
      budget_for("qwen05b-q4_k_m.gguf", 2048, Overhead(0.4, 512.0)).required_mib
      > budget_for("qwen05b-q4_k_m.gguf", 2048).required_mib)
check("マニフェストに書く値は切り上げる（切り下げると足りない）",
      budget_for("qwen05b-q4_k_m.gguf", 2048).rounded_mib(64) == 768
      and budget_for("qwen05b-q4_k_m.gguf", 2048).required_mib > 704,
      "740.1 MiB → 768Mi")
check("Mi と M は違う単位（4.9% ずれる）",
      close(parse_memory("768Mi") / parse_memory("768M"), 1.048576),
      "マニフェストでは必ず Mi / Gi を使う")
check("1Gi は 1024Mi、1G は 1000M",
      close(parse_memory("1Gi"), parse_memory("1024Mi"))
      and close(parse_memory("1G"), parse_memory("1000M")))

print("\n=== Probe と停止の予算 ===")
check("Probe の猶予は initialDelay + period × (failureThreshold − 1)",
      close(ProbeSpec(10.0, 5.0, 60).budget_s, 305.0)
      and close(ProbeSpec(5.0, 5.0, 3).budget_s, 15.0)
      and close(ProbeSpec(0.0, 10.0, 3).budget_s, 20.0))
check("failureThreshold を増やすほうが period を伸ばすより刻みが細かい",
      close(ProbeSpec(0.0, 5.0, 61).budget_s, 300.0)
      and close(ProbeSpec(0.0, 150.0, 3).budget_s, 300.0),
      "同じ 300 秒でも、5 秒間隔なら 5 秒以内に準備完了を検出できる")
check("停止の猶予は preStop ＋ 生成の最長 ＋ 余裕",
      close(grace_required_s(15.0, max_request_seconds(512), 5.0),
            15.0 + (TTFT_P50_MS + TPOT_P50_MS * 512) / 1000.0 + 5.0),
      f"{grace_required_s(15.0, max_request_seconds(512), 5.0):.1f} 秒")
check("生成の最長は TPOT の実測から出す（概算で代用しない）",
      close(max_request_seconds(0), TTFT_P50_MS / 1000.0)
      and close(max_request_seconds(512),
                (TTFT_P50_MS + TPOT_P50_MS * 512) / 1000.0),
      f"TTFT {TTFT_P50_MS:.0f} ms ＋ TPOT {TPOT_P50_MS} ms × トークン数")
check("生成上限を増やすと必要な猶予も増える",
      max_request_seconds(2048) > max_request_seconds(512) > max_request_seconds(64))

print("\n=== ロールアウト ===")
check("maxUnavailable: 0 なら maxSurge の数だけ波に分かれる",
      rollout_waves(2, 1) == 2 and rollout_waves(10, 1) == 10
      and rollout_waves(10, 2) == 5)
check("波の数 × 起動時間がロールアウトの所要時間になる",
      close(rollout_seconds(2, 1, 11.6), 23.2),
      "2 レプリカ・maxSurge 1・起動 11.6 秒 → 23.2 秒")
check("maxSurge のぶん余分な容量が要る",
      close(surge_memory_mib(1, 768.0), 768.0),
      "空きが無いと新しい Pod は Pending のまま進まない")
check("重みがすでにある方式のほうが起動が短い（セッション7の関係）",
      startup_seconds(VOLUME, 379.4) < startup_seconds(FETCH, 379.4),
      f"{startup_seconds(VOLUME, 379.4):.1f} 秒 < "
      f"{startup_seconds(FETCH, 379.4):.1f} 秒")

# --- 7. CLI の契約（終了コードと出力）---------------------------------------
print("\n=== CLI（CI に置ける形）===")
code, out = run_cli([str(REF)])
check("参照マニフェストは終了コード 0",
      code == 0 and "検出: エラー 0 件 / 警告 2 件" in out, f"exit={code}")
code, out = run_cli(["--strict", str(REF)])
check("--strict は警告でも失敗させる", code == 1, f"exit={code}")
code, out = run_cli([str(PVC), str(GPU)])
check("複数ファイルをまとめて検査できる",
      code == 0 and "検出: エラー 0 件 / 警告 4 件" in out, f"exit={code}")
code, out = run_cli([str(BAD)])
check("アンチパターン集は終了コード 1",
      code == 1 and "検出: エラー 8 件 / 警告 7 件" in out, f"exit={code}")
check("本文に載せた指摘がそのまま出力される",
      "[ERROR] startup-probe-missing" in out
      and "[ERROR] liveness-during-load" in out
      and "CrashLoopBackOff から抜けられません" in out)
code, out = run_cli(["--explain", str(REF)])
check("--explain は数字の内訳を出す",
      "= 740.1 MiB → 768Mi" in out and "11.6 秒（起動時に取得" in out
      and "必要 30.0 秒 / 設定 60 秒" in out)
code, out = run_cli(["--max-tokens", "4096", str(REF)])
check("前提を変えると同じマニフェストが落ちる",
      code == 1 and "98.8 秒が必要です" in out,
      "生成上限 4096 トークンなら猶予 60 秒では足りない")

# --- 8. k8s/ 配下すべて ------------------------------------------------------
print("\n=== k8s/ 配下のすべてのマニフェスト ===")
for path in sorted(K8S.glob("*.yaml")):
    reviews = review_docs(load_docs(path))
    errors = [f for r in reviews for f in r.errors]
    check(f"{path.name} にエラーは無い", errors == [],
          f"ワークロード {len(reviews)} 件 / " +
          (" / ".join(f.rule for f in errors) or "エラーなし"))

kind_docs = load_docs(KIND)
check("kind の設定は読めるが、検査対象のワークロードは持たない",
      kind_docs and kind_docs[0].get("kind") == "Cluster"
      and review_docs(kind_docs) == [],
      "クラスタを立てる経路は任意（本書の検証はクラスタを使わない）")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション8の検証はすべて成功しました。")
