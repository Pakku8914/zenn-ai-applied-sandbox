#!/usr/bin/env python3
"""推論ワークロード向けの Kubernetes マニフェスト検査（セッション8）。

**クラスタも kubectl も要らない。** PyYAML でマニフェストを読み、
推論を載せたときだけ問題になる点に絞って検査する。

  1. ロード完了の表現（startupProbe があるか・猶予が足りているか）
  2. livenessProbe がロード中に殺さないか（推論固有で最も事故が多い）
  3. メモリ要求が「重み ＋ KVキャッシュ ＋ 上乗せ」を満たすか
  4. 重みの出所がマニフェストから追えるか
  5. 停止の猶予が生成中のリクエストを捨てない長さか
  6. ロールアウトで全 Pod が同時に落ちないか
  7. GPU の要求の書き方（分割できない・limits に書く）

Kubernetes 一般の妥当性（スキーマ・API バージョン・RBAC・ラベルの整合）は
**扱わない**。それは `kubectl apply --dry-run=client` と姉妹教材の担当である。

時間に関する数値はすべて仮定（セッション7の `Assumptions` を引き継ぐ）。
検証しているのは絶対値ではなく「設定した猶予 > 見積り」という大小関係である。
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.session08.budget import (  # noqa: E402
    BAKED, FETCH, MIB, VOLUME, Assumptions, MemoryBudget, Overhead, ProbeSpec,
    budget_for, grace_required_s, kv_mib, max_request_seconds, method_label,
    startup_seconds, weights_mib_for,
)

# ---------------------------------------------------------------------------
# 読み込みと小さなヘルパ
# ---------------------------------------------------------------------------

WORKLOAD_KINDS = ("Deployment", "StatefulSet")
INFERENCE_HINTS = ("llama", "inference", "vllm", "triton", "server")
GPU_RESOURCES = ("nvidia.com/gpu", "amd.com/gpu")

_MEM_SUFFIX: dict[str, int] = {
    "Ki": 1024, "Mi": 1024 ** 2, "Gi": 1024 ** 3, "Ti": 1024 ** 4,
    "K": 1000, "k": 1000, "M": 1000 ** 2, "G": 1000 ** 3, "T": 1000 ** 4,
}


def load_docs_text(text: str) -> list[dict]:
    """複数ドキュメント（`---` 区切り）の YAML を辞書の並びにする。"""
    return [doc for doc in yaml.safe_load_all(text) if isinstance(doc, dict)]


def load_docs(path: str | Path) -> list[dict]:
    return load_docs_text(Path(path).read_text(encoding="utf-8"))


def find_kind(docs: list[dict], kind: str) -> list[dict]:
    return [doc for doc in docs if doc.get("kind") == kind]


def workloads(docs: list[dict]) -> list[dict]:
    out: list[dict] = []
    for kind in WORKLOAD_KINDS:
        out += find_kind(docs, kind)
    return out


def parse_memory(value: object) -> float:
    """メモリの数量をバイトに直す。`Mi`（1024基準）と `M`（1000基準）は違う。"""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    for suffix in sorted(_MEM_SUFFIX, key=len, reverse=True):
        if text.endswith(suffix):
            return float(text[: -len(suffix)]) * _MEM_SUFFIX[suffix]
    return float(text)


def parse_cpu(value: object) -> float:
    """CPU の数量をコア数に直す。`500m` は 0.5 コア。"""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text.endswith("m"):
        return float(text[:-1]) / 1000.0
    return float(text)


def arg_value(args: object, flag: str) -> str | None:
    """コンテナの `args` から `-m /path` のような値を取り出す。"""
    items = [str(a) for a in (args or [])]
    for i, item in enumerate(items):
        if item == flag and i + 1 < len(items):
            return items[i + 1]
        if item.startswith(flag + "="):
            return item.split("=", 1)[1]
    return None


def image_tag(image: str) -> str:
    """イメージ参照からタグを取り出す。タグが無ければ空文字。"""
    ref = str(image).split("@", 1)[0]
    last = ref.rsplit("/", 1)[-1]
    return last.rsplit(":", 1)[1] if ":" in last else ""


def pod_spec(workload: dict) -> dict:
    return ((workload.get("spec") or {}).get("template") or {}).get("spec") or {}


def inference_container(pod: dict) -> dict | None:
    """推論サーバのコンテナを1つ選ぶ。名前で当たらなければ先頭を使う。"""
    containers = pod.get("containers") or []
    for container in containers:
        name = str(container.get("name", "")).lower()
        if any(hint in name for hint in INFERENCE_HINTS):
            return container
    return containers[0] if containers else None


def probe_spec(probe: object) -> ProbeSpec | None:
    """Probe の設定を読む。省略された項目には Kubernetes の既定値を入れる。"""
    if not isinstance(probe, dict):
        return None
    if "httpGet" in probe:
        kind = "httpGet"
    elif "tcpSocket" in probe:
        kind = "tcpSocket"
    elif "exec" in probe:
        kind = "exec"
    elif "grpc" in probe:
        kind = "grpc"
    else:
        kind = "unknown"
    return ProbeSpec(
        initial_delay_s=float(probe.get("initialDelaySeconds", 0)),
        period_s=float(probe.get("periodSeconds", 10)),
        failure_threshold=int(probe.get("failureThreshold", 3)),
        timeout_s=float(probe.get("timeoutSeconds", 1)),
        path=(probe.get("httpGet") or {}).get("path") if kind == "httpGet" else None,
        kind=kind,
    )


_SLEEP = re.compile(r"sleep\s+(\d+(?:\.\d+)?)")


def prestop_sleep(container: dict) -> tuple[bool, float]:
    """preStop があるか、あるなら何秒待つか。

    `sleep N` 以外（HTTP を叩く・自作のドレイン処理）の場合は待ち時間 0 として
    扱う。「あるかどうか」と「何秒か」は別の問題なのでタプルで返す。
    """
    hook = ((container.get("lifecycle") or {}).get("preStop")) or {}
    if not hook:
        return (False, 0.0)
    command = " ".join(str(c) for c in ((hook.get("exec") or {}).get("command") or []))
    found = _SLEEP.search(command)
    return (True, float(found.group(1)) if found else 0.0)


# ---------------------------------------------------------------------------
# 重みの出所
# ---------------------------------------------------------------------------

DELIVERY_BY_SOURCE = {
    "image": BAKED, "initContainer": FETCH, "pvc": VOLUME,
    "hostPath": VOLUME, "none": FETCH, "unknown": FETCH,
}
SOURCE_LABEL = {
    "image": "イメージに焼いてある（マウントが無い）",
    "initContainer": "初期化コンテナが emptyDir に置く",
    "pvc": "永続ボリューム（PVC）をマウントする",
    "hostPath": "ノード上のパスをマウントする",
    "none": "誰も置かない（emptyDir のまま）",
    "unknown": "判定できない",
}


@dataclass(frozen=True)
class WeightsPlacement:
    """重みがどこから来るか。"""

    source: str
    model_path: str | None
    volume: str | None = None
    read_only: bool = False

    @property
    def label(self) -> str:
        return SOURCE_LABEL.get(self.source, self.source)


def weights_placement(pod: dict, container: dict) -> WeightsPlacement:
    """`-m` のパスとボリュームの対応から、重みの出所を判定する。"""
    args = container.get("args") or container.get("command")
    model_path = arg_value(args, "-m") or arg_value(args, "--model")
    if not model_path:
        return WeightsPlacement("unknown", None)

    best: dict | None = None
    for mount in container.get("volumeMounts") or []:
        path = str(mount.get("mountPath", "")).rstrip("/")
        if not path:
            continue
        if model_path == path or model_path.startswith(path + "/"):
            if best is None or len(path) > len(str(best.get("mountPath", "")).rstrip("/")):
                best = mount
    if best is None:
        return WeightsPlacement("image", model_path)

    name = best.get("name")
    read_only = bool(best.get("readOnly", False))
    volumes = {v.get("name"): v for v in (pod.get("volumes") or [])}
    volume = volumes.get(name, {})
    if "persistentVolumeClaim" in volume:
        return WeightsPlacement("pvc", model_path, name, read_only)
    if "hostPath" in volume:
        return WeightsPlacement("hostPath", model_path, name, read_only)
    if "emptyDir" in volume:
        writers = [
            init for init in (pod.get("initContainers") or [])
            if any(m.get("name") == name for m in (init.get("volumeMounts") or []))
        ]
        source = "initContainer" if writers else "none"
        return WeightsPlacement(source, model_path, name, read_only)
    return WeightsPlacement("unknown", model_path, name, read_only)


# ---------------------------------------------------------------------------
# 検査
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """検査で見つかった問題。`error` は直さないと事故る、`warn` は理由が要る。"""

    rule: str
    severity: str
    where: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.rule} {self.where}: {self.message}"


@dataclass(frozen=True)
class ReviewInputs:
    """検査に使う前提。**時間はすべて仮定であり、実測ではない。**"""

    max_tokens: int = 512
    """1リクエストで許す最長の生成トークン数。停止の予算に効く。"""

    drain_margin_s: float = 5.0
    """停止時の余裕（endpoints が伝播するまでの取りこぼしを吸収する）。"""

    min_liveness_budget_s: float = 30.0
    """livenessProbe の猶予の下限。生成で CPU が埋まると応答が遅れるため。"""

    overprovision_ratio: float = 3.0
    """要求メモリが見積りの何倍を超えたら「積みすぎ」と見るか。"""

    overhead: Overhead = field(default_factory=Overhead)
    assumptions: Assumptions = field(default_factory=Assumptions)


@dataclass(frozen=True)
class WorkloadReview:
    """1ワークロードのレビュー結果（数字の内訳つき）。"""

    where: str
    placement: WeightsPlacement
    ctx_total: int
    slots: int
    threads: int | None
    budget: MemoryBudget | None
    requests_mem_bytes: float | None
    limits_mem_bytes: float | None
    requests_cpu: float | None
    limits_cpu: float | None
    startup: ProbeSpec | None
    readiness: ProbeSpec | None
    liveness: ProbeSpec | None
    startup_estimate_s: float | None
    grace_s: float
    grace_required_s: float
    replicas: int
    findings: list[Finding]

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warn"]


def review_workload(workload: dict, *, has_pdb: bool = True,
                    inputs: ReviewInputs | None = None) -> WorkloadReview:
    """1つの Deployment / StatefulSet を検査して、結果と内訳を返す。"""
    inputs = inputs or ReviewInputs()
    spec = workload.get("spec") or {}
    name = (workload.get("metadata") or {}).get("name", "?")
    pod = pod_spec(workload)
    container = inference_container(pod)
    findings: list[Finding] = []

    if container is None:
        where = f"{workload.get('kind')}/{name}"
        findings.append(Finding("no-container", "error", where,
                                "コンテナが1つもありません"))
        return WorkloadReview(
            where=where, placement=WeightsPlacement("unknown", None),
            ctx_total=0, slots=0, threads=None, budget=None,
            requests_mem_bytes=None, limits_mem_bytes=None,
            requests_cpu=None, limits_cpu=None,
            startup=None, readiness=None, liveness=None,
            startup_estimate_s=None, grace_s=0.0, grace_required_s=0.0,
            replicas=0, findings=findings)

    where = f"{workload.get('kind')}/{name}:{container.get('name', '?')}"

    def add(rule: str, severity: str, message: str) -> None:
        findings.append(Finding(rule, severity, where, message))

    # --- イメージ ---------------------------------------------------------
    image = str(container.get("image", ""))
    tag = image_tag(image)
    if not tag:
        add("image-tag", "error",
            f"{image} にタグがありません。いつ pull したかで中身が変わります")
    elif tag == "latest":
        add("image-tag", "error",
            f"{image} は latest です。ロールアウトのたびに別の中身が動きえます")
    if "@sha256:" not in image:
        add("image-digest", "warn",
            "ダイジェスト（@sha256:...）で固定していません。"
            "同じタグが差し替わると、動いていたものを再現できません")

    # --- 重みの出所 -------------------------------------------------------
    args = container.get("args") or container.get("command")
    placement = weights_placement(pod, container)
    if placement.source == "none":
        add("weights-not-provisioned", "error",
            f"{placement.model_path} は emptyDir の上にありますが、"
            "初期化コンテナも含めて誰も置きません。サーバは起動できません")
    elif placement.source == "pvc" and not placement.read_only:
        add("pvc-not-readonly", "warn",
            "重みのマウントに readOnly: true がありません。"
            "推論側は読むだけなので、書けてしまうと事故の余地が残ります")
    elif placement.source == "unknown":
        add("weights-source-unknown", "warn",
            "-m の指すパスとボリュームの対応が読めません。"
            "重みの出所がマニフェストから追えない状態です")

    # --- コンテキストとスレッド -------------------------------------------
    ctx_raw = arg_value(args, "-c") or arg_value(args, "--ctx-size")
    slots_raw = arg_value(args, "-np") or arg_value(args, "--parallel")
    threads_raw = arg_value(args, "-t") or arg_value(args, "--threads")
    ctx_total = int(ctx_raw) if ctx_raw else 0
    slots = int(slots_raw) if slots_raw else 1
    threads = int(threads_raw) if threads_raw else None
    if ctx_total <= 0:
        add("context-unspecified", "warn",
            "-c（コンテキスト長）が書かれていません。"
            "KVキャッシュの量が決まらないので、メモリ要求を見積もれません")

    # --- リソース ---------------------------------------------------------
    resources = container.get("resources") or {}
    requests = resources.get("requests") or {}
    limits = resources.get("limits") or {}
    missing = [key for key in ("memory", "cpu") if key not in requests]
    if missing:
        add("requests-missing", "error",
            f"requests に {' と '.join(missing)} がありません。"
            "省略すると limits と同じ値が要求として使われ、"
            "limits も無ければ要求ゼロでどこにでも置かれます")

    def effective(key: str) -> object | None:
        if key in requests:
            return requests[key]
        return limits.get(key)

    req_mem_raw, lim_mem_raw = effective("memory"), limits.get("memory")
    req_cpu_raw, lim_cpu_raw = effective("cpu"), limits.get("cpu")
    req_mem = parse_memory(req_mem_raw) if req_mem_raw is not None else None
    lim_mem = parse_memory(lim_mem_raw) if lim_mem_raw is not None else None
    req_cpu = parse_cpu(req_cpu_raw) if req_cpu_raw is not None else None
    lim_cpu = parse_cpu(lim_cpu_raw) if lim_cpu_raw is not None else None

    budget = (budget_for(placement.model_path or "", ctx_total, inputs.overhead)
              if ctx_total > 0 else None)
    if placement.model_path and weights_mib_for(placement.model_path) is None:
        add("weights-size-unknown", "warn",
            f"{placement.model_path} のサイズが分かりません。"
            "メモリ要求の検査を飛ばしました（本書の実測表にあるモデル名を使うか、"
            "自分で測った値を budget.py に足してください）")

    if budget is not None:
        required = budget.required_bytes
        if req_mem is not None and req_mem < required:
            add("memory-requests", "error",
                f"requests.memory が {req_mem / MIB:.1f}Mi ですが、"
                f"{budget.explain()} が必要です。"
                "足りないノードに置かれ、動き出してから落ちます")
        if lim_mem is None:
            add("memory-limit-missing", "warn",
                "limits.memory がありません。暴走したときにノードごと巻き込みます")
        elif lim_mem < required:
            add("memory-limits", "error",
                f"limits.memory が {lim_mem / MIB:.1f}Mi ですが、"
                f"必要なのは {budget.required_mib:.1f}Mi です。"
                "KVキャッシュが埋まった時点で OOMKilled（終了コード 137）になります")
        if (req_mem is not None
                and req_mem > required * inputs.overprovision_ratio):
            add("memory-overprovisioned", "warn",
                f"requests.memory が見積りの "
                f"{req_mem / required:.1f} 倍あります。"
                "積みすぎるとノードに詰められる Pod が減り、単価が上がります")

    if req_cpu is not None and lim_cpu is not None and req_cpu < lim_cpu:
        add("cpu-requests-lt-limits", "warn",
            f"requests.cpu {req_cpu:g} < limits.cpu {lim_cpu:g} です。"
            "混雑時に CPU を譲るので TPOT が伸びます。"
            "レイテンシを守るなら requests と limits を揃えます")
    if threads is not None and lim_cpu is not None and threads > lim_cpu:
        add("threads-over-cpu-limit", "warn",
            f"-t {threads} が limits.cpu {lim_cpu:g} を超えています。"
            "使えないコアにスレッドを立てると、切り替えの分だけ遅くなります")

    # --- GPU ---------------------------------------------------------------
    gpu_keys = [key for key in GPU_RESOURCES if key in requests or key in limits]
    for key in gpu_keys:
        if key not in limits:
            add("gpu-requests-limits", "error",
                f"{key} が requests にしかありません。"
                "GPU は limits に書きます（requests は limits と同じ値になります）")
        elif key in requests and parse_cpu(requests[key]) != parse_cpu(limits[key]):
            add("gpu-requests-limits", "error",
                f"{key} の requests と limits が違います"
                f"（{requests[key]} と {limits[key]}）。GPU は分け合えないので"
                "同じ値でなければ受け付けられません")
        for value in (requests.get(key), limits.get(key)):
            if value is None:
                continue
            count = parse_cpu(value)
            if count <= 0 or not float(count).is_integer():
                add("gpu-fractional", "error",
                    f"{key} に {value} を指定しています。"
                    "GPU は 1 個単位でしか要求できません"
                    "（分割したいなら MIG か time-slicing を device plugin 側で設定します）")
    if gpu_keys and not (pod.get("nodeSelector") or pod.get("affinity")
                         or pod.get("tolerations")):
        add("gpu-scheduling", "warn",
            "GPU を要求していますが nodeSelector も tolerations もありません。"
            "GPU ノードに taint が付いていると Pending のまま止まります")

    # --- Probe -------------------------------------------------------------
    startup = probe_spec(container.get("startupProbe"))
    readiness = probe_spec(container.get("readinessProbe"))
    liveness = probe_spec(container.get("livenessProbe"))
    weights_mib = weights_mib_for(placement.model_path or "")
    estimate: float | None = None
    if weights_mib is not None:
        estimate = startup_seconds(DELIVERY_BY_SOURCE.get(placement.source, FETCH),
                                   weights_mib, inputs.assumptions)

    if startup is None:
        add("startup-probe-missing", "error",
            "startupProbe がありません。ロード完了を待つ役はこの Probe だけです")
        if liveness is not None and estimate is not None \
                and liveness.budget_s < estimate:
            add("liveness-during-load", "error",
                f"livenessProbe の猶予が {liveness.budget_s:.1f} 秒しかなく、"
                f"起動の見積り {estimate:.1f} 秒に届きません。"
                "ロード中に再起動され、CrashLoopBackOff から抜けられません")
    elif estimate is not None and startup.budget_s < estimate:
        add("startup-budget", "error",
            f"startupProbe の猶予が {startup.budget_s:.1f} 秒"
            f"（{startup.describe()}）で、起動の見積り {estimate:.1f} 秒に"
            "届きません。ロードが終わる前に再起動されます")

    if readiness is None:
        add("readiness-not-http", "error",
            "readinessProbe がありません。ロード中の Pod にも振り分けられます")
    elif readiness.kind != "httpGet":
        add("readiness-not-http", "error",
            f"readinessProbe が {readiness.kind} です。"
            "ポートが開いているかは「プロセスが生きているか」でしかなく、"
            "モデルのロードが終わったかを表せません")

    if liveness is not None and liveness.budget_s < inputs.min_liveness_budget_s:
        add("liveness-too-tight", "warn",
            f"livenessProbe の猶予が {liveness.budget_s:.1f} 秒です。"
            "生成で CPU が埋まると応答が遅れるので、"
            f"{inputs.min_liveness_budget_s:.0f} 秒以上を目安にします")
    if (readiness is not None and liveness is not None
            and readiness.kind == "httpGet" and liveness.kind == "httpGet"
            and readiness.path == liveness.path):
        add("probe-paths-shared", "warn",
            f"readinessProbe と livenessProbe が同じ {readiness.path} を見ています。"
            "llama.cpp が /health しか持たないための妥協なら構いませんが、"
            "「準備完了」と「生存」は別の問いです")

    # --- ロールアウトと停止 -------------------------------------------------
    strategy = spec.get("strategy") or {}
    if str(strategy.get("type", "RollingUpdate")) == "RollingUpdate":
        rolling = strategy.get("rollingUpdate") or {}
        max_unavailable = rolling.get("maxUnavailable", "25%")
        if str(max_unavailable) not in ("0", "0%"):
            add("max-unavailable", "error",
                f"maxUnavailable が {max_unavailable} です。"
                "起動に時間がかかる推論では、新しい Pod が受け付ける前に"
                "古い Pod が抜けて受け皿が消えます。0 にします")

    has_prestop, prestop_s = prestop_sleep(container)
    if not has_prestop:
        add("prestop-missing", "warn",
            "preStop がありません。SIGTERM と endpoints の削除は同時ではないので、"
            "抜ける直前に届いたリクエストを取りこぼします")
    grace = float(pod.get("terminationGracePeriodSeconds", 30))
    request_s = max_request_seconds(inputs.max_tokens)
    needed = grace_required_s(prestop_s, request_s, inputs.drain_margin_s)
    if grace < needed:
        add("grace-too-short", "error",
            f"terminationGracePeriodSeconds が {grace:.0f} 秒ですが、"
            f"preStop {prestop_s:.0f} 秒 ＋ 生成 {request_s:.1f} 秒 ＋ 余裕 "
            f"{inputs.drain_margin_s:.0f} 秒 = {needed:.1f} 秒が必要です。"
            "生成中のリクエストが SIGKILL で切られます")

    replicas = int(spec.get("replicas", 1))
    if replicas < 2:
        add("replicas-single", "warn",
            f"replicas が {replicas} です。1本だと更新中もノードの入れ替え中も"
            "受け皿が無くなります")
    if not has_pdb:
        add("pdb-missing", "warn",
            "PodDisruptionBudget がありません。ノードのメンテナンスで"
            "全 Pod が同時に退去させられます")

    findings.sort(key=lambda f: (0 if f.severity == "error" else 1, f.rule))
    return WorkloadReview(where, placement, ctx_total, slots, threads, budget,
                          req_mem, lim_mem, req_cpu, lim_cpu, startup, readiness,
                          liveness, estimate, grace, needed, replicas, findings)


def review_docs(docs: list[dict],
                inputs: ReviewInputs | None = None) -> list[WorkloadReview]:
    """マニフェスト全体（`---` で連結された複数ドキュメント）を検査する。"""
    has_pdb = bool(find_kind(docs, "PodDisruptionBudget"))
    return [review_workload(w, has_pdb=has_pdb, inputs=inputs)
            for w in workloads(docs)]


def lint_manifest(docs: list[dict],
                  inputs: ReviewInputs | None = None) -> list[Finding]:
    """検査結果を平らな並びで返す（エラーが先、次にルール名順）。"""
    out: list[Finding] = []
    for review in review_docs(docs, inputs):
        out += review.findings
    out.sort(key=lambda f: (0 if f.severity == "error" else 1, f.rule, f.where))
    return out


def rules_of(findings: list[Finding], severity: str) -> set[str]:
    """指定した重大度のルール名の集合（テストで期待値と比べるため）。"""
    return {f.rule for f in findings if f.severity == severity}


# ---------------------------------------------------------------------------
# 説明（レビューのときに人が読む形）
# ---------------------------------------------------------------------------


def explain(review: WorkloadReview) -> str:
    """数字の内訳を並べる。マニフェストの値の根拠を口で言えるようにする。"""
    lines = [review.where]
    p = review.placement
    lines.append(f"  重みの出所      : {p.label}")
    if p.model_path:
        size = weights_mib_for(p.model_path)
        size_text = f"{size:.1f} MiB" if size is not None else "サイズ不明"
        lines.append(f"  モデル          : {p.model_path}（{size_text}）")
    if review.ctx_total:
        per_slot = review.ctx_total // max(review.slots, 1)
        lines.append(f"  コンテキスト    : -c {review.ctx_total} / -np {review.slots}"
                     f"（1スロット {per_slot}）")
        lines.append(f"  KVキャッシュ    : {kv_mib(review.ctx_total):.1f} MiB")
    if review.budget is not None:
        lines.append(f"  要求メモリの内訳: {review.budget.explain()}")
    req = (f"{review.requests_mem_bytes / MIB:.1f}Mi"
           if review.requests_mem_bytes is not None else "未指定")
    lim = (f"{review.limits_mem_bytes / MIB:.1f}Mi"
           if review.limits_mem_bytes is not None else "未指定")
    lines.append(f"  マニフェストの値: requests {req} / limits {lim}")
    if review.startup_estimate_s is not None:
        method = DELIVERY_BY_SOURCE.get(review.placement.source, FETCH)
        lines.append(f"  起動の見積り    : {review.startup_estimate_s:.1f} 秒"
                     f"（{method_label(method)}・セッション7の仮定）")
    if review.startup is not None:
        lines.append(f"  startupProbe    : 猶予 {review.startup.describe()}")
    if review.liveness is not None:
        lines.append(f"  livenessProbe   : 猶予 {review.liveness.describe()}")
    lines.append(f"  停止の予算      : 必要 {review.grace_required_s:.1f} 秒 / "
                 f"設定 {review.grace_s:.0f} 秒")
    return "\n".join(lines)


__all__ = [
    "Finding", "ReviewInputs", "WeightsPlacement", "WorkloadReview",
    "arg_value", "explain", "find_kind", "image_tag", "inference_container",
    "lint_manifest", "load_docs", "load_docs_text", "parse_cpu", "parse_memory",
    "pod_spec", "prestop_sleep", "probe_spec", "review_docs", "review_workload",
    "rules_of", "weights_placement", "workloads",
]
