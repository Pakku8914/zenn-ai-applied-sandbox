#!/usr/bin/env python3
"""サービング構成の計算と判定（セッション4）。

推論サーバを起動しなくても試せる部分だけを集めてある。

- スロットとコンテキストの分割（`-c` は `-np` で割られる）
- 受け入れ判定（入力 + 出力の予約が1スロットに収まるか）
- 飽和点の判定（スループットが伸びず TTFT だけが悪化する最初の点）
- 「遅い」をプリフィル / デコード / キュー待ちに分解する

数値の出典は本文の実測表（2026-08-15 実測 / aarch64 / CPU 2コア /
メモリ 5.8GB / Python 3.12.13 / llama.cpp `-t 2`）。
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# スロットとコンテキストの分割
# ---------------------------------------------------------------------------


def slot_context(total_ctx: int, slots: int) -> int:
    """1スロットあたりのコンテキスト長。

    `-c` はサーバ全体のコンテキスト長で、`-np`（並列スロット数）で分割される。
    `-c 2048 -np 2` なら1スロットは 1024（`/props` の `n_ctx` もそう返る）。
    """
    if total_ctx <= 0 or slots <= 0:
        raise ValueError("total_ctx と slots は 1 以上を指定してください")
    return total_ctx // slots


@dataclass(frozen=True)
class ServingLimits:
    """1インスタンスのサービング上限。

    total_ctx             : `-c` に渡す値（サーバ全体）
    slots                 : `-np` に渡す値（並列スロット数）
    max_output_tokens     : 出力トークン数の上限（クライアントの指定は必ずここで抑える）
    reserve_output_tokens : 出力用に必ず残しておくトークン数
    queue_deadline_ms     : 待ち行列に置いておける上限（超えたら実行せず捨てる）
    """

    total_ctx: int
    slots: int
    max_output_tokens: int = 256
    reserve_output_tokens: int = 64
    queue_deadline_ms: float = 3000.0

    @property
    def ctx_per_slot(self) -> int:
        return slot_context(self.total_ctx, self.slots)

    @property
    def max_prompt_tokens(self) -> int:
        """出力の枠を残したうえで受けられる最長の入力。

        スロットを増やすとここが短くなる。これが本章の取引そのもの。
        """
        return self.ctx_per_slot - self.reserve_output_tokens


@dataclass(frozen=True)
class Admission:
    ok: bool
    max_tokens: int
    reason: str = ""


def admit(prompt_tokens: int, requested_max_tokens: int,
          limits: ServingLimits) -> Admission:
    """受け入れるか、受けるとして出力を何トークンまで許すかを決める。

    入力が長すぎるリクエストは**受ける前に断る**。受けてから途中で打ち切ると、
    プリフィルに使った計算がまるごと無駄になる。
    """
    if prompt_tokens <= 0 or requested_max_tokens <= 0:
        return Admission(False, 0, "入力と出力はどちらも 1 トークン以上が必要です")
    if prompt_tokens > limits.max_prompt_tokens:
        return Admission(False, 0,
                         f"入力が長すぎます（{prompt_tokens} > "
                         f"{limits.max_prompt_tokens} トークン）")
    room = limits.ctx_per_slot - prompt_tokens
    granted = min(requested_max_tokens, limits.max_output_tokens, room)
    if granted <= 0:
        return Admission(False, 0, "出力の枠が残っていません")
    if granted < requested_max_tokens:
        return Admission(True, granted,
                         f"出力を {granted} トークンに切り詰めました"
                         f"（要求は {requested_max_tokens}）")
    return Admission(True, granted)


def expired(waited_ms: float, limits: ServingLimits) -> bool:
    """待ち行列に置かれてからの経過時間が上限を超えたか。

    期限切れのリクエストは**実行しない**。クライアントはすでに待っていないので、
    ここで計算を始めても誰も受け取らないまま CPU を使うだけになる。
    """
    return waited_ms > limits.queue_deadline_ms


@dataclass(frozen=True)
class QueuedRequest:
    """待ち行列に入ったリクエスト（時刻は単調増加のミリ秒）。"""

    enqueued_at_ms: float
    prompt_tokens: int
    requested_max_tokens: int


@dataclass
class DrainResult:
    runnable: list[tuple[QueuedRequest, int]]   # (リクエスト, 許可した出力トークン数)
    dropped: dict[str, int]                     # 捨てた理由 -> 件数


def drain_queue(queued: list[QueuedRequest], now_ms: float,
                limits: ServingLimits) -> DrainResult:
    """実行してよいものだけを残す。

    打ち切りは**プリフィルを始める前**に行うのが最も安い。捨てた件数は理由ごとに
    数えておく（記録がないと「なぜ処理されなかったか」を後から説明できない）。
    """
    runnable: list[tuple[QueuedRequest, int]] = []
    dropped: dict[str, int] = {}

    def drop(reason: str) -> None:
        dropped[reason] = dropped.get(reason, 0) + 1

    for req in queued:
        if expired(now_ms - req.enqueued_at_ms, limits):
            drop("期限切れ")
            continue
        decision = admit(req.prompt_tokens, req.requested_max_tokens, limits)
        if not decision.ok:
            drop("受け入れ不可")
            continue
        runnable.append((req, decision.max_tokens))
    return DrainResult(runnable, dropped)


# ---------------------------------------------------------------------------
# 飽和点の判定
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SweepRow:
    """同時実行を1段変えて測った1行。"""

    concurrency: int
    ttft_p50_ms: float
    total_p50_ms: float
    throughput_tps: float


# 2026-08-15 実測（Q4_K_M・スロット2・コンテキスト2048＝1スロット1024・
# max_tokens=48・20リクエスト・aarch64 / CPU 2コア / llama.cpp -t 2）
MEASURED_SLOTS2 = [
    SweepRow(1, 155.0, 1034.0, 45.0),
    SweepRow(2, 52.0, 1737.0, 53.0),
    SweepRow(4, 1772.0, 3379.0, 53.9),
]

# 同じ環境・別条件（max_tokens=24・8リクエスト）で 1 と 4 だけ測った場合。
# 刻みが粗いと飽和点を見落とす、という教材用のデータ。
MEASURED_COARSE = [
    SweepRow(1, 81.0, 452.0, 52.0),
    SweepRow(4, 633.0, 1206.0, 73.8),
]


def find_saturation(rows: list[SweepRow], gain_threshold: float = 0.10) -> int | None:
    """飽和点を返す。見つからなければ None。

    定義：同時実行を1段上げたときに
      (1) スループット（トークン/秒）の伸びが gain_threshold 未満で、
      (2) TTFT p50 が悪化する
    最初の同時実行数。「これ以上入れても待ち時間だけが伸びる」点である。
    """
    ordered = sorted(rows, key=lambda r: r.concurrency)
    for prev, cur in zip(ordered, ordered[1:]):
        if prev.throughput_tps <= 0:
            continue
        gain = (cur.throughput_tps - prev.throughput_tps) / prev.throughput_tps
        if gain < gain_threshold and cur.ttft_p50_ms > prev.ttft_p50_ms:
            return cur.concurrency
    return None


def queue_wait_ms(ttft_ms: float, baseline_ttft_ms: float) -> float:
    """キュー待ちの近似値。

    並列1 で測った TTFT を「待ちゼロのプリフィル時間」の代理として引く。
    **同じプロンプト集・同じ max_tokens で測った値を渡すこと。**
    条件の違う数字を混ぜると、プリフィルが遅いだけの状態を待ちと誤診する。
    """
    return max(ttft_ms - baseline_ttft_ms, 0.0)


# ---------------------------------------------------------------------------
# 「遅い」の3分解
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Budget:
    """1リクエストに許す時間の目標値。"""

    ttft_ms: float
    tpot_ms: float


def diagnose(ttft_ms: float, tpot_ms: float, budget: Budget,
             baseline_ttft_ms: float) -> list[str]:
    """「遅い」を プリフィル / デコード / キュー待ち に分解する。

    baseline_ttft_ms には**同じプロンプトを並列1で測った TTFT** を渡す。
    """
    labels: list[str] = []
    if ttft_ms > budget.ttft_ms:
        # 待ちが基準の TTFT を上回る＝処理そのものより待ちのほうが長い
        if queue_wait_ms(ttft_ms, baseline_ttft_ms) > baseline_ttft_ms:
            labels.append("キュー待ち")
        else:
            labels.append("プリフィル")
    if tpot_ms > budget.tpot_ms:
        labels.append("デコード")
    return labels


def markdown_table(rows: list[SweepRow], conditions: dict) -> str:
    """引き継げる形（Markdown の表）にして返す。条件を必ず添える。"""
    cond = " / ".join(f"{k}={v}" for k, v in conditions.items())
    lines = [f"測定条件: {cond}", "",
             "| 並列 | TTFT p50 | 総時間 p50 | スループット | キュー待ち（近似） |",
             "| --: | --: | --: | --: | --: |"]
    base = sorted(rows, key=lambda r: r.concurrency)[0].ttft_p50_ms
    for r in sorted(rows, key=lambda r: r.concurrency):
        lines.append(f"| {r.concurrency} | {r.ttft_p50_ms:.0f} ms | "
                     f"{r.total_p50_ms:.0f} ms | {r.throughput_tps:.1f} tok/s | "
                     f"{queue_wait_ms(r.ttft_p50_ms, base):.0f} ms |")
    point = find_saturation(rows)
    lines.append("")
    lines.append(f"飽和点: {point if point is not None else '検出されず（刻みを細かくする）'}")
    return "\n".join(lines)
