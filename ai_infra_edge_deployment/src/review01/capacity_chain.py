#!/usr/bin/env python3
"""容量の鎖：KVキャッシュ → 並列スロット → 飽和点 → 入口の上限（復習1・問題4）。

セッション3（KVキャッシュの式）、セッション4（スロットと飽和点）、
セッション5（レート制限と受け入れ制御）の判断を1本につなぐ。読者が入力
（メモリ予算・系列長・テナント数）を変えたら、下流の値がすべて再計算される。

上流の実測値は 2026-08-15 実測 / aarch64 / CPU 2コア / メモリ 5.8GB /
Python 3.12.13 / llama.cpp `-t 2`（Q4_K_M・スロット2・1スロット1024・
max_tokens=48・20リクエスト）。**絶対値は環境によって変わる。** この鎖が
学ばせるのは「どの上限が先に来るか」という関係である。

  docker compose exec app python src/review01/capacity_chain.py
  docker compose exec app python src/review01/capacity_chain.py --memo
  docker compose exec app python src/review01/capacity_chain.py \
      --model llama8b --seq-len 2048 --memory-gb 0.25
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from infrakit.kvcache import LLAMA_8B, QWEN_05B, kv_cache_bytes, max_concurrent  # noqa: E402
from src.session04.serving_config import (  # noqa: E402
    MEASURED_SLOTS2, ServingLimits, SweepRow, find_saturation,
)

GB = 1024 ** 3
MB = 1024 ** 2
MODELS = {"qwen05b": QWEN_05B, "llama8b": LLAMA_8B}

# 並列ごとの rps（実測）。SweepRow は tok/s しか持たないので、リクエスト/秒は
# ここに置く。tok/s と rps は別の単位であり、出力トークン数を決めないと
# 相互に変換できない（セッション2）。
MEASURED_RPS = {1: 0.96, 2: 1.13, 4: 1.15}


def shape(name: str) -> dict:
    """kv_cache_bytes / max_concurrent に渡せる形（hidden を除く）にする。"""
    return {k: v for k, v in MODELS[name].items() if k != "hidden"}


def safe_concurrency(rows: list[SweepRow] | None = None) -> tuple[int, int | None]:
    """(安全に流せる同時実行数, 飽和点) を返す。

    飽和点は「これ以上入れても待ち時間だけが伸びる点」なので、採用するのは
    その1つ前に**実際に測った**点である。飽和点そのものを設定値にしてはいけない。
    刻みが粗くて飽和点が見つからない場合は、測った中で最大の点を返す
    （＝まだ飽和点を知らない状態。刻みを細かくして測り直すべき）。
    """
    measured_rows = list(rows if rows is not None else MEASURED_SLOTS2)
    point = find_saturation(measured_rows)
    measured = sorted(r.concurrency for r in measured_rows)
    if point is None:
        return measured[-1], None
    below = [c for c in measured if c < point]
    return (below[-1] if below else 1), point


@dataclass(frozen=True)
class Chain:
    """1インスタンスの容量を決める鎖。上から順に下流が決まる。"""

    model: str
    seq_len: int
    kv_budget_bytes: int
    per_token_bytes: int
    per_stream_bytes: int
    kv_max_streams: int          # ① メモリだけで決まる上限（セッション3）
    saturation_at: int | None    # ② 実測の飽和点（セッション4）
    safe_concurrency: int        # ② 飽和点の1つ前に測った点
    slots: int                   # ②' 採用する -np
    total_ctx: int               # ②' 採用する -c
    ctx_per_slot: int
    max_prompt_tokens: int
    ceiling_rps: float           # ③ 上限スループット（セッション2の単位・セッション4の実測）
    tenants: int
    rate_per_key: float          # ③ 入口の上限（セッション5）
    burst_per_key: float
    max_inflight: int
    max_queue: int
    queue_deadline_ms: float

    @property
    def binding(self) -> str:
        """どちらの上限が先に来ているか。"""
        return "メモリ" if self.kv_max_streams <= self.safe_concurrency else "飽和点"

    @property
    def rate_total(self) -> float:
        return self.rate_per_key * self.tenants


def floor_at(value: float, digits: int = 2) -> float:
    """切り捨て。四捨五入すると合計が上限を超えるので必ず切り捨てる。

    9桁で丸めてから切り捨てるのは二進小数の誤差対策（`metrics.min_samples` と
    同じ理由）。素直に書くと 0.96 / 3 * 100 が 31.999999999999996 になり、
    0.31 rps と返ってしまう。
    """
    scale = 10 ** digits
    return math.floor(round(value * scale, 9)) / scale


def build_chain(model: str = "qwen05b", seq_len: int = 1024, memory_gb: float = 1.0,
                tenants: int = 3, service_ms: float = 1034.0,
                rows: list[SweepRow] | None = None,
                rps: dict[int, float] | None = None) -> Chain:
    """鎖を組み立てる。順序（メモリ → 飽和点 → 入口）が方針そのものである。"""
    if model not in MODELS:
        raise ValueError(f"未知のモデル: {model}（{sorted(MODELS)} から選んでください）")
    if seq_len <= 0 or memory_gb <= 0:
        raise ValueError("seq_len と memory_gb は正の数を指定してください")
    if tenants < 1:
        raise ValueError("tenants は 1 以上を指定してください")

    table = dict(rps if rps is not None else MEASURED_RPS)
    budget = int(memory_gb * GB)

    # ① KVキャッシュ（セッション3）
    one = kv_cache_bytes(seq_len=seq_len, batch=1, **shape(model))
    streams = max_concurrent(budget, seq_len, **shape(model))

    # ② 飽和点（セッション4）。小さいほうが効く上限になる
    safe, point = safe_concurrency(rows)
    slots = max(min(streams, safe), 1)
    limits = ServingLimits(total_ctx=seq_len * slots, slots=slots,
                           queue_deadline_ms=service_ms)

    # ③ 入口の上限（セッション5）。上限スループットをテナント数で割る
    ceiling = table.get(slots) or table[min(table, key=lambda c: abs(c - slots))]
    rate = floor_at(ceiling / tenants, 2)
    if rate <= 0.0:
        rate = floor_at(ceiling / tenants, 4)

    return Chain(
        model=model, seq_len=seq_len, kv_budget_bytes=budget,
        per_token_bytes=one.per_token_bytes, per_stream_bytes=one.total_bytes,
        kv_max_streams=streams, saturation_at=point, safe_concurrency=safe,
        slots=slots, total_ctx=limits.total_ctx, ctx_per_slot=limits.ctx_per_slot,
        max_prompt_tokens=limits.max_prompt_tokens,
        ceiling_rps=ceiling, tenants=tenants, rate_per_key=rate,
        burst_per_key=float(slots), max_inflight=slots, max_queue=slots,
        queue_deadline_ms=service_ms,
    )


def show(c: Chain) -> None:
    m = MODELS[c.model]
    point = f"並列 {c.saturation_at}" if c.saturation_at else "検出されず（刻みを細かく）"
    print("=== 入力（読者が決める値）===")
    print(f"モデル形状          : {c.model}（層 {m['n_layers']} / "
          f"KVヘッド {m['n_kv_heads']} / ヘッド次元 {m['head_dim']}）")
    print(f"系列長              : {c.seq_len:,} トークン")
    print(f"KVキャッシュ予算    : {c.kv_budget_bytes / GB:.2f} GB")
    print(f"テナント数          : {c.tenants}")
    print(f"1件の処理時間       : {c.queue_deadline_ms:.0f} ms（並列1 の総時間 p50・実測）")
    print()
    print("=== ① KVキャッシュ（セッション3）===")
    print(f"1トークンあたり     : {c.per_token_bytes:,} バイト"
          f"（{c.per_token_bytes / 1024:.2f} KB）")
    print(f"系列1本あたり       : {c.per_stream_bytes / MB:.1f} MB")
    print(f"メモリで持てる本数  : {c.kv_max_streams} 本")
    print()
    print("=== ② 飽和点と採用する設定（セッション4）===")
    print(f"実測の飽和点        : {point}")
    print(f"安全に流せる同時実行: {c.safe_concurrency}（飽和点の1つ前に測った点）")
    print(f"採用する -np        : {c.slots} ← min(メモリ {c.kv_max_streams}, "
          f"飽和点の手前 {c.safe_concurrency})")
    print(f"採用する -c         : {c.total_ctx}（1スロット {c.ctx_per_slot}）")
    print(f"受けられる最長入力  : {c.max_prompt_tokens} トークン")
    print(f"効いている上限      : {c.binding}")
    print()
    print("=== ③ 入口の上限（セッション5）===")
    print(f"上限スループット    : {c.ceiling_rps:.2f} rps（並列 {c.slots} の実測）")
    print(f"rate（キーあたり）  : {c.rate_per_key:.2f} rps × {c.tenants} "
          f"= {c.rate_total:.2f} rps")
    print(f"burst（キーあたり） : {c.burst_per_key:.0f}（上流の並列スロット数に揃える）")
    print(f"max_inflight        : {c.max_inflight}（上流の並列スロット数と同じ）")
    print(f"max_queue           : {c.max_queue} / 待ち行列の期限 "
          f"{c.queue_deadline_ms:.0f} ms")


def memo(c: Chain) -> str:
    """引き継げる形（Markdown）。値と根拠を必ず並べて書く。"""
    return "\n".join([
        "# 容量の決定メモ（復習1・問題4）",
        "",
        f"- 再生成: `python src/review01/capacity_chain.py --model {c.model} "
        f"--seq-len {c.seq_len} --memory-gb {c.kv_budget_bytes / GB:.2f} "
        f"--tenants {c.tenants} --service-ms {c.queue_deadline_ms:.0f} --memo`",
        "- 上流の実測条件: 2026-08-15 実測 / aarch64 / CPU 2コア / メモリ 5.8GB / "
        "Python 3.12.13 / llama.cpp `-t 2`（Q4_K_M・スロット2・1スロット1024・"
        "max_tokens=48・20リクエスト）",
        "",
        "| 決めた値 | 値 | 根拠 |",
        "| :--- | --: | :--- |",
        f"| `-np`（並列スロット） | {c.slots} | メモリ上限 {c.kv_max_streams} 本"
        f"（S3）と飽和点の手前 {c.safe_concurrency}（S4）の小さいほう |",
        f"| `-c`（全体のコンテキスト） | {c.total_ctx} | 系列長 {c.seq_len} × "
        f"`-np` {c.slots}（S4） |",
        f"| 受けられる最長入力 | {c.max_prompt_tokens} | 1スロット {c.ctx_per_slot} − "
        "出力予約 64（S4） |",
        f"| `rate`（キーあたり） | {c.rate_per_key:.2f} rps | 上限 "
        f"{c.ceiling_rps:.2f} rps ÷ {c.tenants} テナント・切り捨て（S2 の単位・S5） |",
        f"| `burst`（キーあたり） | {c.burst_per_key:.0f} | 上流の並列スロット数（S4・S5） |",
        f"| `max_inflight` | {c.max_inflight} | 上流の並列スロット数（S4・S5） |",
        f"| `max_queue` / 期限 | {c.max_queue} / {c.queue_deadline_ms:.0f} ms | "
        "1件の処理時間を超えて待たせない（S4・S5） |",
        "",
        f"効いている上限: {c.binding}（メモリ {c.kv_max_streams} 本 vs "
        f"飽和点の手前 {c.safe_concurrency}）。",
        "",
        "## 再測が必要になる条件",
        "",
        "- `-np` か `-c` を変えた（飽和点も上限スループットも動く）",
        "- 量子化形式を変えた（TTFT・TPOT・tok/s がすべて動く）",
        "- テナントが増えた（`rate` の分母が変わる）",
        "",
        "※ 絶対値は環境ごとに変わる。ここに書いた数字は「この環境ではこうなった」"
        "という記録であり、他環境での保証ではない。",
    ])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=sorted(MODELS), default="qwen05b")
    ap.add_argument("--seq-len", type=int, default=1024)
    ap.add_argument("--memory-gb", type=float, default=1.0)
    ap.add_argument("--tenants", type=int, default=3)
    ap.add_argument("--service-ms", type=float, default=1034.0,
                    help="1件の処理時間。並列1 の総時間 p50 を入れる")
    ap.add_argument("--memo", action="store_true", help="Markdown のメモも出力する")
    args = ap.parse_args()

    chain = build_chain(model=args.model, seq_len=args.seq_len,
                        memory_gb=args.memory_gb, tenants=args.tenants,
                        service_ms=args.service_ms)
    show(chain)
    if args.memo:
        print()
        print(memo(chain))


if __name__ == "__main__":
    main()
