#!/usr/bin/env python3
"""HorizontalPodAutoscaler の静的検査（セッション9）。

**クラスタも kubectl も要らない。** PyYAML でマニフェストを読み、推論を
オートスケールしたときだけ問題になる点に絞って検査する。セッション8の
`src/session08/manifest.py` と同じ作りで、`Finding` もそのまま使い回す。

見るのは6つ。

1. 指標（CPU 使用率だけでスケールしていないか・待ちを表す指標があるか）
2. 最小レプリカ（0 にしていないか・可用性の下限を割っていないか）
3. `behavior` の非対称（スケールインがスケールアウトより保守的か）
4. 対象（`scaleTargetRef`）が実在するワークロードを指しているか
5. API バージョンと書式（`Pods` 指標の target は `AverageValue` である）
6. 容量計画との整合（`--plan` を渡したときだけ。計画より小さい上限・下限を弾く）

Kubernetes 一般の妥当性（スキーマ・RBAC・メトリクス配線の存在）は**扱わない**。
それは `kubectl apply --dry-run` と、メトリクスを公開する側（次章）の担当である。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.session08.manifest import (  # noqa: E402
    Finding, find_kind, load_docs, load_docs_text, parse_cpu, workloads,
)
from src.session09.scaling import CapacityPlan  # noqa: E402

HPA_KIND = "HorizontalPodAutoscaler"
SUPPORTED_API = "autoscaling/v2"
SCALABLE_KINDS = ("Deployment", "StatefulSet")

QUEUE_HINTS = ("queue", "pending", "deferred", "waiting", "inflight", "backlog")
SLOT_HINTS = ("slot",)
GPU_HINTS = ("gpu", "sm_", "dcgm")

CPU_TARGET_WARN = 80.0
"""CPU の目標使用率がこれ以上なら、届く前に飽和していると考える。"""

SCALE_UP_STABILIZATION_WARN_S = 60.0
"""スケールアウトの安定化ウィンドウがこれを超えたら、遅れに上乗せされる。"""

MIN_REPLICAS_FLOOR = 2
"""可用性の下限（更新中とノード入れ替え中に受け皿を空にしない）。"""


# ---------------------------------------------------------------------------
# 読み取り
# ---------------------------------------------------------------------------


def hpas(docs: list[dict]) -> list[dict]:
    return find_kind(docs, HPA_KIND)


def workload_names(docs: list[dict]) -> set[tuple[str, str]]:
    """同じ入力に含まれる Deployment / StatefulSet の（kind, name）の集合。"""
    out: set[tuple[str, str]] = set()
    for w in workloads(docs):
        name = (w.get("metadata") or {}).get("name")
        if name:
            out.add((str(w.get("kind")), str(name)))
    return out


@dataclass(frozen=True)
class MetricRef:
    """`spec.metrics[]` の1つ。型ごとに置き場所が違うので平らにして持つ。"""

    type: str
    name: str
    target_type: str
    value: float | None
    utilization: float | None

    @property
    def is_cpu(self) -> bool:
        return self.type in ("Resource", "ContainerResource") and self.name == "cpu"

    @property
    def is_memory(self) -> bool:
        return self.type in ("Resource", "ContainerResource") and self.name == "memory"

    @property
    def is_queue_like(self) -> bool:
        lowered = self.name.lower()
        return any(hint in lowered for hint in QUEUE_HINTS)

    @property
    def is_slot_like(self) -> bool:
        lowered = self.name.lower()
        return any(hint in lowered for hint in SLOT_HINTS)

    @property
    def is_gpu_like(self) -> bool:
        lowered = self.name.lower()
        return any(hint in lowered for hint in GPU_HINTS)

    def label(self) -> str:
        if self.utilization is not None:
            target = f"{self.target_type} {self.utilization:.0f}%"
        elif self.value is not None:
            target = f"{self.target_type} {self.value:g}"
        else:
            target = f"{self.target_type} 未指定"
        return f"{self.type} {self.name} {target}"


_TARGET_KEYS = {"Resource": "resource", "ContainerResource": "containerResource",
                "Pods": "pods", "Object": "object", "External": "external"}


def metric_refs(hpa: dict) -> list[MetricRef]:
    """`spec.metrics[]` を MetricRef の並びにする。"""
    out: list[MetricRef] = []
    for item in ((hpa.get("spec") or {}).get("metrics") or []):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type", "unknown"))
        body = item.get(_TARGET_KEYS.get(kind, ""), {}) or {}
        if kind in ("Resource", "ContainerResource"):
            name = str(body.get("name", "?"))
        else:
            name = str((body.get("metric") or {}).get("name", "?"))
        target = body.get("target") or {}
        raw = target.get("averageValue", target.get("value"))
        util = target.get("averageUtilization")
        out.append(MetricRef(
            type=kind, name=name,
            target_type=str(target.get("type", "未指定")),
            value=parse_cpu(raw) if raw is not None else None,
            utilization=float(util) if util is not None else None))
    return out


@dataclass(frozen=True)
class BehaviorSide:
    """`behavior.scaleUp` / `behavior.scaleDown` の片側。"""

    direction: str
    stabilization_s: float
    select: str
    policies: tuple[tuple[str, float, float], ...]
    explicit: bool

    def rate_per_min(self, replicas: int) -> float:
        """1分あたり何本まで動かせるか。

        `Percent` のポリシーは現在のレプリカ数に比例するので、**最小レプリカ数を
        基準**に換算する（一番小さい状態でどれだけ動くかを見る）。
        """
        if self.select == "Disabled":
            return 0.0
        rates: list[float] = []
        for kind, value, period in self.policies:
            if period <= 0:
                continue
            pods = value if kind == "Pods" else max(replicas, 1) * value / 100.0
            rates.append(pods / period * 60.0)
        if not rates:
            return 0.0
        return min(rates) if self.select == "Min" else max(rates)

    def describe(self, replicas: int) -> str:
        source = "" if self.explicit else "（既定）"
        return (f"安定化 {self.stabilization_s:.0f} 秒 / "
                f"最大 {self.rate_per_min(replicas):.1f} 本/分{source}")


# Kubernetes の既定値（autoscaling/v2）。出典は本文に記載。
DEFAULT_SCALE_UP = BehaviorSide("scaleUp", 0.0, "Max",
                                (("Percent", 100.0, 15.0), ("Pods", 4.0, 15.0)), False)
DEFAULT_SCALE_DOWN = BehaviorSide("scaleDown", 300.0, "Max",
                                  (("Percent", 100.0, 15.0),), False)


def behavior_side(hpa: dict, direction: str) -> BehaviorSide:
    """片側の `behavior` を読む。省略された項目には既定値を入れる。"""
    default = DEFAULT_SCALE_UP if direction == "scaleUp" else DEFAULT_SCALE_DOWN
    side = ((hpa.get("spec") or {}).get("behavior") or {}).get(direction)
    if not isinstance(side, dict):
        return default
    policies = tuple(
        (str(p.get("type", "?")), float(p.get("value", 0)), float(p.get("periodSeconds", 0)))
        for p in (side.get("policies") or []) if isinstance(p, dict))
    return BehaviorSide(
        direction=direction,
        stabilization_s=float(side.get("stabilizationWindowSeconds",
                                       default.stabilization_s)),
        select=str(side.get("selectPolicy", "Max")),
        policies=policies or default.policies,
        explicit=True)


# ---------------------------------------------------------------------------
# 検査
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HpaReview:
    """HPA 1つぶんのレビュー結果（数字の内訳つき）。"""

    where: str
    target: str
    min_replicas: int
    max_replicas: int | None
    min_specified: bool
    metrics: tuple[MetricRef, ...]
    up: BehaviorSide
    down: BehaviorSide
    plan: CapacityPlan | None
    findings: list[Finding]

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warn"]


def review_hpa(hpa: dict, *, known: set[tuple[str, str]] | None = None,
               plan: CapacityPlan | None = None) -> HpaReview:
    """HPA 1つを検査して、結果と内訳を返す。"""
    spec = hpa.get("spec") or {}
    name = (hpa.get("metadata") or {}).get("name", "?")
    where = f"{HPA_KIND}/{name}"
    findings: list[Finding] = []

    def add(rule: str, severity: str, message: str) -> None:
        findings.append(Finding(rule, severity, where, message))

    # --- API バージョン -----------------------------------------------------
    api = str(hpa.get("apiVersion", ""))
    if api != SUPPORTED_API:
        add("api-version", "warn",
            f"apiVersion が {api or '未指定'} です。{SUPPORTED_API} を使います"
            "（v1 は behavior もカスタム指標も持てず、v2beta2 は削除済みです）")

    # --- 対象 ---------------------------------------------------------------
    ref = spec.get("scaleTargetRef") or {}
    target_kind = str(ref.get("kind", "?"))
    target_name = str(ref.get("name", "?"))
    target = f"{target_kind}/{target_name}"
    if target_kind not in SCALABLE_KINDS:
        add("target-kind", "warn",
            f"scaleTargetRef の kind が {target_kind} です。"
            "推論サーバは Deployment か StatefulSet で動かします")
    if known is None:
        add("target-unverified", "warn",
            "対象のワークロードが同じ入力に含まれていないので、"
            f"{target} が実在するか確かめられません。"
            "Deployment のマニフェストも一緒に検査してください")
    elif (target_kind, target_name) not in known:
        add("target-missing", "error",
            f"{target} が見つかりません。名前が違う HPA は"
            "「作られているのに1本も増えない」状態になります"
            f"（同じ入力にあるのは {'、'.join(sorted(n for _, n in known)) or 'なし'}）")

    # --- レプリカの範囲 -----------------------------------------------------
    min_specified = "minReplicas" in spec
    min_replicas = int(spec.get("minReplicas", 1))
    max_raw = spec.get("maxReplicas")
    max_replicas = int(max_raw) if max_raw is not None else None

    if max_replicas is None:
        add("max-replicas-missing", "error",
            "maxReplicas がありません（必須フィールドです）。"
            "上限が無いとノードの空きとレジストリ帯域を食い尽くします")
    if min_replicas == 0:
        add("min-replicas-zero", "error",
            "minReplicas が 0 です。推論はモデルのロードとウォームアップがあるため、"
            "0 から立ち上げると最初の利用者がその全部を待ちます"
            "（既定では API も受け付けません。HPAScaleToZero が必要です）")
    elif min_replicas < MIN_REPLICAS_FLOOR:
        note = "" if min_specified else "（未指定なので既定の 1 です）"
        add("min-replicas-single", "warn",
            f"minReplicas が {min_replicas} です{note}。"
            "1本だと更新中もノードの入れ替え中も受け皿が無くなります")
    if max_replicas is not None and min_replicas > max_replicas:
        add("min-over-max", "error",
            f"minReplicas {min_replicas} が maxReplicas {max_replicas} を"
            "超えています")

    # --- 指標 ---------------------------------------------------------------
    metrics = tuple(metric_refs(hpa))
    if not metrics:
        add("metrics-missing", "error",
            "metrics がありません。何を見て増やすかが決まっていません")
    else:
        cpu = [m for m in metrics if m.is_cpu]
        if cpu and len(cpu) == len(metrics):
            add("cpu-only-metric", "error",
                "CPU 使用率だけでスケールしています。デコードはメモリ帯域律速なので、"
                "待ち行列が伸びていても使用率は上がりきらないことがあります"
                "（逆にプリフィル中は張り付きます）。"
                "キュー長を指標にしてください")
        elif cpu:
            add("cpu-metric-present", "warn",
                "CPU 使用率を併用しています。HPA は指標ごとの推奨値の最大を採るので、"
                "CPU が張り付くと待ち行列が空でも増え続けます。"
                "残すなら理由をコメントに書いてください")
        for m in cpu:
            if m.utilization is not None and m.utilization >= CPU_TARGET_WARN:
                add("cpu-target-high", "warn",
                    f"CPU の目標使用率が {m.utilization:.0f}% です。"
                    "requests と limits を揃えた推論 Pod では、"
                    "ここに届く前に待ち行列が伸び始めます")
        for m in metrics:
            if m.is_memory:
                add("memory-metric", "warn",
                    "メモリ使用量を指標にしています。推論のメモリは"
                    "「重み ＋ KVキャッシュ」で起動時にほぼ確定するので、"
                    "負荷が増えても動きません")
            if m.is_gpu_like:
                add("gpu-metric", "warn",
                    f"{m.name} は GPU の使用率に見えます。"
                    "GPU 使用率は並列度も飽和度も表しません"
                    "（帯域待ちでも 100% に見えます）")
            if m.type == "Pods" and m.target_type != "AverageValue":
                add("pods-target-type", "error",
                    f"Pods 指標 {m.name} の target.type が {m.target_type} です。"
                    "Pods 指標は AverageValue（1本あたりの平均）でしか書けません")

        queue_like = [m for m in metrics if m.is_queue_like]
        slot_like = [m for m in metrics if m.is_slot_like]
        if not queue_like and slot_like:
            add("slot-metric-only", "warn",
                "スロット使用率だけを見ています。100% に張り付いた先"
                "（どれだけ超過しているか）が見えないので、"
                "キュー長と併用してください")
        elif not queue_like:
            add("queue-metric-missing", "warn",
                "待ちを表す指標（キュー長・キュー待ち時間）が1つもありません。"
                "推論の飽和は「待たされているか」で判断します")
        if plan is not None:
            for m in queue_like:
                if m.value is not None and m.value > plan.target_queue_len:
                    add("queue-threshold-above-plan", "warn",
                        f"{m.name} のしきい値 {m.value:g} が、飽和点から出した "
                        f"{plan.target_queue_len:.1f} 件より大きいです。"
                        "飽和してから発火することになります")

    # --- behavior -----------------------------------------------------------
    up = behavior_side(hpa, "scaleUp")
    down = behavior_side(hpa, "scaleDown")
    if not (up.explicit or down.explicit):
        add("behavior-missing", "warn",
            "behavior がありません。既定はスケールインの安定化 300 秒・"
            "スケールアウト 0 秒ですが、削減幅が 15 秒あたり 100% なので"
            "一気に minReplicas まで落ちます。明示してください")
    # 「<」ではなく「<=」で見る。スケールアウトの安定化は 0 秒が推奨なので、
    # 「<」だとスケールインも 0 秒にした設定（安定化なし＝最もフラッピングする）を
    # 1件も検出できない（0 < 0 が偽になるため）。等しい場合も非対称になっていない。
    if down.stabilization_s <= up.stabilization_s:
        add("scale-down-window", "error",
            f"スケールインの安定化 {down.stabilization_s:.0f} 秒が、"
            f"スケールアウトの {up.stabilization_s:.0f} 秒より長くありません。"
            "起動が遅いワークロードでは「出るのを遅く・入るのを早く」が原則です。"
            "同じ秒数でも非対称になっていないので、減らした直後に足りなくなると"
            "コールドスタートをもう一度払います")
    up_rate = up.rate_per_min(max(min_replicas, 1))
    down_rate = down.rate_per_min(max(min_replicas, 1))
    if down_rate > up_rate:
        add("scale-down-rate", "warn",
            f"1分あたりの本数がスケールイン {down_rate:.1f} 本 > "
            f"スケールアウト {up_rate:.1f} 本です。"
            "減らすほうが速いと、減らした直後に足りなくなって"
            "コールドスタートをもう一度払います")
    if up.stabilization_s > SCALE_UP_STABILIZATION_WARN_S:
        add("scale-up-slow", "warn",
            f"スケールアウトの安定化が {up.stabilization_s:.0f} 秒あります。"
            "この時間はまるごと「発火の遅れ」に足されます")

    # --- 容量計画との照合 ---------------------------------------------------
    if plan is not None:
        if min_replicas > 0 and min_replicas < plan.min_replicas:
            add("min-replicas-below-plan", "error",
                f"minReplicas が {min_replicas} ですが、計画では "
                f"{plan.min_replicas} 本必要です"
                f"（平常 {plan.baseline_replicas} 本 ＋ 立ち上がりの吸収 "
                f"{plan.headroom_replicas} 本）")
        if max_replicas is not None and max_replicas < plan.peak_replicas:
            add("max-replicas-below-peak", "error",
                f"maxReplicas が {max_replicas} ですが、ピーク "
                f"{plan.peak_rps:.2f} rps を捌くには {plan.peak_replicas} 本"
                f"必要です（1本 {plan.per_instance_rps:.2f} rps）")

    findings.sort(key=lambda f: (0 if f.severity == "error" else 1, f.rule))
    return HpaReview(where, target, min_replicas, max_replicas, min_specified,
                     metrics, up, down, plan, findings)


def review_docs(docs: list[dict], *, known: set[tuple[str, str]] | None = None,
                plan: CapacityPlan | None = None) -> list[HpaReview]:
    """マニフェスト全体を検査する。`known` が None なら対象の実在を検証しない。"""
    return [review_hpa(h, known=known, plan=plan) for h in hpas(docs)]


def lint_hpa(docs: list[dict], *, known: set[tuple[str, str]] | None = None,
             plan: CapacityPlan | None = None) -> list[Finding]:
    """検査結果を平らな並びで返す（エラーが先、次にルール名順）。"""
    out: list[Finding] = []
    for review in review_docs(docs, known=known, plan=plan):
        out += review.findings
    out.sort(key=lambda f: (0 if f.severity == "error" else 1, f.rule, f.where))
    return out


def rules_of(findings: list[Finding], severity: str) -> set[str]:
    return {f.rule for f in findings if f.severity == severity}


def explain(review: HpaReview) -> str:
    """数字の内訳を並べる。マニフェストの値の根拠を口で言えるようにする。"""
    replicas = max(review.min_replicas, 1)
    lines = [f"{review.where} -> {review.target}"]
    lines.append(f"  レプリカの範囲  : min {review.min_replicas} / "
                 f"max {review.max_replicas if review.max_replicas is not None else '未指定'}")
    for m in review.metrics:
        role = ("待ちを表す指標" if m.is_queue_like else
                "スロット使用率" if m.is_slot_like else
                "CPU 使用率（推論の飽和とは相関しない）" if m.is_cpu else "その他")
        lines.append(f"  指標            : {m.label()}（{role}）")
    if not review.metrics:
        lines.append("  指標            : なし")
    lines.append(f"  スケールアウト  : {review.up.describe(replicas)}")
    lines.append(f"  スケールイン    : {review.down.describe(replicas)}")
    plan = review.plan
    if plan is not None:
        lines.append(f"  容量計画        : ピーク {plan.peak_rps:.2f} rps → "
                     f"{plan.peak_replicas} 本 / 計画の minReplicas "
                     f"{plan.min_replicas} / しきい値 "
                     f"{plan.target_queue_len:.1f} 件")
        lines.append(f"  スケールの遅れ  : {plan.lag.total_s:.1f} 秒"
                     f"（発火 {plan.lag.fire_s:.1f} ＋ 供給 "
                     f"{plan.lag.provision_s:.1f}）")
    return "\n".join(lines)


__all__ = [
    "DEFAULT_SCALE_DOWN", "DEFAULT_SCALE_UP", "HPA_KIND", "BehaviorSide",
    "Finding", "HpaReview", "MetricRef", "behavior_side", "explain", "hpas",
    "lint_hpa", "load_docs", "load_docs_text", "metric_refs", "review_docs",
    "review_hpa", "rules_of", "workload_names",
]
