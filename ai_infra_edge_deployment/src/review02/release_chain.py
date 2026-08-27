#!/usr/bin/env python3
"""リリースの鎖：1つの変更がどこまで波及するかを数える（復習2・問題7）。

セッション3（KVキャッシュの式）→ セッション4（`-c` と `-np` の分割）→
セッション6（応答キャッシュの鍵）→ セッション7（配り方と起動時間）→
セッション8（マニフェストの数字）を1本につなぐ。

「モデルを差し替える」「`-c` を倍にする」「生成上限を上げる」といった1行の
変更が、どのフィールドを連れて動くかを機械的に洗い出すのが目的である。手で
洗い出すと必ず漏れる。漏れたぶんは本番で OOMKilled や CrashLoopBackOff の
形で現れる。

  docker compose exec app python src/review02/release_chain.py --to-model q8_0
  docker compose exec app python src/review02/release_chain.py --to-ctx 4096
  docker compose exec app python src/review02/release_chain.py \
      --to-ctx 4096 --to-max-output 1984 --tpot-ms 36.74

サイズと TTFT・TPOT は 2026-08-15 実測（aarch64 / CPU 2コア / メモリ 5.8GB /
Python 3.12.13 / llama.cpp `-t 2`）。**起動時間はセッション7の仮定の積み上げ
であって実測ではない。** ここで学ぶのは絶対値ではなく「何が何を連れて動くか」
という関係である。
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.session04.serving_config import ServingLimits  # noqa: E402
from src.session06.cache_keys import CacheScope, scoped_key  # noqa: E402
from src.session07.imageplan import (  # noqa: E402
    BAKED, FETCH, METHOD_NAMES, VOLUME, image_mb,
)
from src.session08.budget import (  # noqa: E402
    TPOT_P50_MS, TTFT_P50_MS, MemoryBudget, Overhead, budget_for,
    grace_required_s, kv_mib, max_request_seconds, rollout_seconds,
    rollout_waves, startup_seconds, surge_memory_mib, weights_mib_for,
)

MODEL_FILES = {
    "f16": "/models/qwen05b-f16.gguf",
    "q8_0": "/models/qwen05b-q8_0.gguf",
    "q4_k_m": "/models/qwen05b-q4_k_m.gguf",
}
DELIVERY_CHOICES = {"baked": BAKED, "volume": VOLUME, "fetch": FETCH}

# 鍵が変わるかどうかを見るための固定のリクエスト（対話画面からの標準的な1件）
PROBE_PROMPT = "有給休暇の申請期限を教えてください。"
PROBE_MAX_TOKENS = 64
PROBE_TENANT = "soumu"
PROBE_VISIBILITY = frozenset({"general"})


@dataclass(frozen=True)
class Release:
    """1つの構成。変更前と変更後を2つ作って並べる。

    tpot_measured : **変更後の条件で TPOT を測り直したか。** False のときは
                    停止の予算を数字で出さない。測っていない値で猶予を決めるのは、
                    条件の違うレポートを並べるのと同じ間違いである（セッション2）。
    """

    label: str
    model_path: str = "/models/qwen05b-q4_k_m.gguf"
    ctx_total: int = 2048
    slots: int = 2
    delivery: str = FETCH
    max_output_tokens: int = 512
    tpot_ms: float = TPOT_P50_MS
    tpot_measured: bool = True
    prestop_s: float = 15.0
    drain_margin_s: float = 5.0
    corpus_version: str = "2026-08-15"
    overhead: Overhead = field(default_factory=Overhead)

    @property
    def model_name(self) -> str:
        return self.model_path.rsplit("/", 1)[-1]

    @property
    def weights_mib(self) -> float:
        mib = weights_mib_for(self.model_path)
        if mib is None:
            raise ValueError(f"{self.model_path} のサイズが分かりません。"
                             "実測した値を budget.py の GGUF_MB に足してください")
        return mib

    @property
    def kv_cache_mib(self) -> float:
        """KVキャッシュの合計。`-c` の値だけで決まり、`-np` では変わらない。"""
        return kv_mib(self.ctx_total)

    @property
    def budget(self) -> MemoryBudget:
        b = budget_for(self.model_path, self.ctx_total, self.overhead)
        if b is None:
            raise ValueError(f"{self.model_path} のメモリ要求を計算できません")
        return b

    @property
    def limits(self) -> ServingLimits:
        return ServingLimits(total_ctx=self.ctx_total, slots=self.slots,
                             max_output_tokens=self.max_output_tokens)

    @property
    def image_size_mb(self) -> float:
        return image_mb(self.delivery, self.weights_mib)

    @property
    def cold_s(self) -> float:
        """新しいノードで起動するときの見積り（仮定の積み上げ）。"""
        return startup_seconds(self.delivery, self.weights_mib)

    @property
    def warm_s(self) -> float:
        """イメージがノードにある状態での見積り。"""
        return startup_seconds(self.delivery, self.weights_mib, image_cached=True)

    @property
    def request_s(self) -> float:
        return max_request_seconds(self.max_output_tokens, TTFT_P50_MS, self.tpot_ms)

    @property
    def grace_needed_s(self) -> float:
        return grace_required_s(self.prestop_s, self.request_s, self.drain_margin_s)

    @property
    def scope(self) -> CacheScope:
        return CacheScope(tenant_id=PROBE_TENANT, visibility=PROBE_VISIBILITY,
                          model=self.model_name, max_tokens=PROBE_MAX_TOKENS,
                          temperature=0.0, corpus_version=self.corpus_version)

    @property
    def cache_key(self) -> str:
        return scoped_key(self.scope, PROBE_PROMPT)

    @property
    def cache_key_material(self) -> str:
        """鍵の材料のうち、リリースで動きうる部分だけを文字列にする。

        鍵そのもの（sha256）は読んでも意味が取れないので、比較には材料を使う。
        """
        return f"model={self.model_name} / corpus={self.corpus_version}"


@dataclass(frozen=True)
class ManifestState:
    """いま動いているマニフェストの値（`k8s/inference-deployment.yaml`）。

    startup_budget_s は `initialDelaySeconds + periodSeconds × (failureThreshold − 1)`
    = 10 + 5 × 59 = 305 秒、liveness_budget_s は 0 + 30 × 2 = 60 秒。
    """

    requests_mib: float = 768.0
    startup_budget_s: float = 305.0
    liveness_budget_s: float = 60.0
    grace_s: float = 60.0
    replicas: int = 2
    max_surge: int = 1


@dataclass(frozen=True)
class Change:
    """1行ぶんの差分。`changed` は文字列が違うかどうかで決める。"""

    item: str
    before: str
    after: str
    source: str

    @property
    def changed(self) -> bool:
        return self.before != self.after

    @property
    def mark(self) -> str:
        return "変わる" if self.changed else "同じ"


def _time_cell(r: Release) -> str:
    if not r.tpot_measured:
        return "未確定（TPOT を測り直す）"
    return (f"{r.request_s:.1f} 秒（{r.max_output_tokens} トークン・"
            f"TPOT {r.tpot_ms:.2f} ms）")


def _grace_cell(r: Release) -> str:
    if not r.tpot_measured:
        return "未確定（TPOT を測り直す）"
    return f"{r.grace_needed_s:.1f} 秒以上"


def compare(before: Release, after: Release) -> list[Change]:
    """変更前と変更後を、根拠のセッションつきで並べる。"""
    return [
        Change("重みのサイズ", f"{before.weights_mib:.1f} MiB",
               f"{after.weights_mib:.1f} MiB", "S07"),
        Change("KVキャッシュ", f"{before.kv_cache_mib:.1f} MiB",
               f"{after.kv_cache_mib:.1f} MiB", "S03"),
        Change("requests/limits.memory", before.budget.quantity(),
               after.budget.quantity(), "S03+S08"),
        Change("1スロットのコンテキスト", f"{before.limits.ctx_per_slot}",
               f"{after.limits.ctx_per_slot}", "S04"),
        Change("受けられる最長入力", f"{before.limits.max_prompt_tokens} トークン",
               f"{after.limits.max_prompt_tokens} トークン", "S04"),
        Change("配るイメージ", f"{before.image_size_mb:.1f} MB",
               f"{after.image_size_mb:.1f} MB", "S07"),
        Change("起動の見積り（cold）", f"{before.cold_s:.1f} 秒",
               f"{after.cold_s:.1f} 秒", "S07"),
        Change("起動の見積り（warm）", f"{before.warm_s:.1f} 秒",
               f"{after.warm_s:.1f} 秒", "S07"),
        Change("生成の最長", _time_cell(before), _time_cell(after), "S02+S08"),
        Change("必要な停止の猶予", _grace_cell(before), _grace_cell(after),
               "S02+S08"),
        Change("応答キャッシュの鍵の材料", before.cache_key_material,
               after.cache_key_material, "S06"),
    ]


def _dedupe(rows: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """同じ指標が2つのトリガーで挙がったとき、最初に付いた理由を残す。"""
    seen: set[str] = set()
    uniq: list[tuple[str, str]] = []
    for name, why in rows:
        if name in seen:
            continue
        seen.add(name)
        uniq.append((name, why))
    return uniq


def remeasure(before: Release, after: Release) -> list[tuple[str, str]]:
    """測り直すべき指標と理由。測り直さずに数字を引き継ぐのが最も多い事故。"""
    rows: list[tuple[str, str]] = []
    if before.model_path != after.model_path:
        rows += [
            ("TTFT p50/p95・TPOT p50・tok/s（S02）",
             "生成の速さはモデルで変わる。量子化は小さいほど速いとは限らない"),
            ("飽和点（S04）",
             "1件の処理時間が変われば、同時実行を上げたときの待ち方も変わる"),
            ("モデル階層の並び（S05）", "階層は測った順に並べる。測る前に順序を変えない"),
        ]
    if (before.ctx_total, before.slots) != (after.ctx_total, after.slots):
        rows += [
            ("TTFT p50（S02・S03）",
             "プリフィルする長さと1スロットのコンテキストが変わる"),
            ("飽和点（S04）", "スロットの分け方が変わると待ち行列の伸び方も変わる"),
        ]
    if before.delivery != after.delivery:
        rows += [("起動の内訳（S07）", "起動時間だけが変わる。生成の速さは変わらない")]
    # 同じ指標が2つのトリガーで挙がることがあるので、名前で重複を落とす
    # （最初に付いた理由を残す）
    return _dedupe(rows)


def cache_action(before: Release, after: Release) -> tuple[str, str]:
    """応答キャッシュに対して打つ手を1つ返す（打つ手・根拠）。"""
    if before.corpus_version != after.corpus_version:
        return (f'invalidate_stale("{after.corpus_version}") を打つ',
                "資料バージョンが鍵の材料に入っているので、"
                "古い版のエントリだけを捨てられる（S06）")
    if before.cache_key != after.cache_key:
        return ("鍵が変わるので古い答えは返らない。ただし TTL まで残ってメモリを"
                "食うので invalidate_all() を打つか TTL の経過を待つ",
                f"鍵の材料が「{before.cache_key_material}」から"
                f"「{after.cache_key_material}」へ変わる（S06）")
    return ("何もしなくてよい",
            "鍵の材料（テナント・可視範囲・モデル・生成パラメータ・資料バージョン）"
            "が変わらない（S06）")


def todo(after: Release, state: ManifestState | None = None) -> list[str]:
    """マニフェストで直す必要があるフィールドを、理由つきで返す。"""
    st = state or ManifestState()
    out: list[str] = []
    if st.requests_mib < after.budget.required_mib:
        out.append(f"requests.memory / limits.memory: {st.requests_mib:.0f}Mi → "
                   f"{after.budget.quantity()}（{after.budget.explain()}）")
    if st.startup_budget_s < after.cold_s:
        out.append(f"startupProbe の猶予: {st.startup_budget_s:.0f} 秒 → "
                   f"{math.ceil(after.cold_s)} 秒以上"
                   f"（起動の見積り {after.cold_s:.1f} 秒）")
    if not after.tpot_measured:
        out.append("terminationGracePeriodSeconds: TPOT を測り直してから決める"
                   "（変更後の条件で測っていない値を停止の予算に使わない）")
    elif st.grace_s < after.grace_needed_s:
        out.append(f"terminationGracePeriodSeconds: {st.grace_s:.0f} 秒 → "
                   f"{math.ceil(after.grace_needed_s)} 秒以上"
                   f"（preStop {after.prestop_s:.0f} ＋ 生成 "
                   f"{after.request_s:.1f} ＋ 余裕 {after.drain_margin_s:.0f} = "
                   f"{after.grace_needed_s:.1f} 秒）")
    if after.max_output_tokens > after.limits.max_prompt_tokens:
        out.append(f"生成上限 {after.max_output_tokens} トークンは1スロットの"
                   f"コンテキスト {after.limits.ctx_per_slot} に収まりません"
                   "（`-c` を増やすか上限を下げる）")
    return out


def impact_markdown(before: Release, after: Release,
                    state: ManifestState | None = None) -> str:
    """引き継げる形（Markdown）。値と根拠と再測条件を必ず並べて書く。"""
    st = state or ManifestState()
    lines = [
        f"# 変更の影響: {before.label} → {after.label}",
        "",
        "## 1. 値の比較",
        "",
        "| 項目 | 変更前 | 変更後 | 変化 | 根拠 |",
        "| :--- | :--- | :--- | :-- | :--- |",
    ]
    for c in compare(before, after):
        lines.append(f"| {c.item} | {c.before} | {c.after} | {c.mark} | {c.source} |")

    lines += ["", "## 2. 測り直すもの", ""]
    rows = remeasure(before, after)
    if rows:
        lines += ["| 測り直す指標 | 理由 |", "| :--- | :--- |"]
        lines += [f"| {name} | {why} |" for name, why in rows]
    else:
        lines.append("- なし（生成の条件が変わっていません）")

    action, why = cache_action(before, after)
    lines += ["", "## 3. 応答キャッシュの手当て", "", f"- 打つ手: {action}",
              f"- 根拠: {why}"]

    lines += ["", "## 4. マニフェストで直すフィールド", ""]
    items = todo(after, st)
    lines += [f"- {t}" for t in items] if items else ["- なし（いまの値で足ります）"]

    waves = rollout_waves(st.replicas, st.max_surge)
    total = rollout_seconds(st.replicas, st.max_surge, after.cold_s)
    lines += [
        "", "## 5. ロールアウトの見積り", "",
        f"- 起動 {after.cold_s:.2f} 秒 × {waves} 波（replicas {st.replicas} / "
        f"maxSurge {st.max_surge} / maxUnavailable 0）= {total:.1f} 秒",
        f"- maxSurge のあいだ余分に必要なメモリ: "
        f"{surge_memory_mib(st.max_surge, after.budget.rounded_mib()):.0f} MiB",
        "",
        "※ サイズと TTFT・TPOT は 2026-08-15 実測（aarch64 / CPU 2コア / "
        "メモリ 5.8GB / Python 3.12.13 / llama.cpp `-t 2`）。"
        "起動時間はセッション7の仮定（レジストリ 100 MB/s ほか）の積み上げで、"
        "実測ではありません。絶対値ではなく向きを読んでください。",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="1つの変更がどこまで波及するかを洗い出す（復習2）")
    ap.add_argument("--to-model", choices=sorted(MODEL_FILES))
    ap.add_argument("--to-ctx", type=int, help="変更後の -c")
    ap.add_argument("--to-slots", type=int, help="変更後の -np")
    ap.add_argument("--to-delivery", choices=sorted(DELIVERY_CHOICES))
    ap.add_argument("--to-max-output", type=int, help="変更後の生成上限")
    ap.add_argument("--to-corpus", help="変更後の資料バージョン")
    ap.add_argument("--tpot-ms", type=float,
                    help="変更後の条件で測り直した TPOT p50。省略してモデルを"
                         "変えると「未測定」として扱う")
    args = ap.parse_args()

    before = Release("いま動いている構成")
    kwargs: dict = {}
    notes: list[str] = []
    if args.to_model:
        kwargs["model_path"] = MODEL_FILES[args.to_model]
        notes.append(f"モデルを {args.to_model} に差し替える")
    if args.to_ctx:
        kwargs["ctx_total"] = args.to_ctx
        notes.append(f"-c を {args.to_ctx} にする")
    if args.to_slots:
        kwargs["slots"] = args.to_slots
        notes.append(f"-np を {args.to_slots} にする")
    if args.to_delivery:
        method = DELIVERY_CHOICES[args.to_delivery]
        kwargs["delivery"] = method
        notes.append(f"配り方を「{METHOD_NAMES[method]}」に変える")
    if args.to_max_output:
        kwargs["max_output_tokens"] = args.to_max_output
        notes.append(f"生成上限を {args.to_max_output} トークンにする")
    if args.to_corpus:
        kwargs["corpus_version"] = args.to_corpus
        notes.append(f"資料バージョンを {args.to_corpus} にする")
    if args.tpot_ms is not None:
        kwargs["tpot_ms"] = args.tpot_ms
        kwargs["tpot_measured"] = True
    elif args.to_model:
        kwargs["tpot_measured"] = False

    after = replace(before, label="／".join(notes) or "何も変えない", **kwargs)
    print(impact_markdown(before, after))


if __name__ == "__main__":
    main()
