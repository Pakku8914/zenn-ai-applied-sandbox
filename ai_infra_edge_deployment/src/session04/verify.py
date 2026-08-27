#!/usr/bin/env python3
"""セッション4の自己検証：サービング構成を決められていること。

- `-c` はスロット数で分割される（`-c 2048 -np 2` で1スロット 1024）
- スロットを増やすと受けられる入力が短くなる（取引）
- 飽和点の判定と、刻みが粗いと見落とすこと
- 起動・準備完了・生存が別物であること（ロード中は live だが not ready）
- 同時実行がスロット数を超えると TTFT が悪化し、待ちが支配的になること

推論サーバを使う検証は SKIP_SERVER=1 で飛ばせる。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from infrakit.client import GenResult  # noqa: E402
from infrakit.kvcache import QWEN_05B, kv_cache_bytes  # noqa: E402
from src.session04.health_app import probe_response  # noqa: E402
from src.session04.readiness import Phase, ReadinessGate, run_startup  # noqa: E402
from src.session04.serving_config import (  # noqa: E402
    MEASURED_COARSE, MEASURED_SLOTS2, Budget, QueuedRequest, ServingLimits, admit,
    diagnose, drain_queue, expired, find_saturation, markdown_table, queue_wait_ms,
    slot_context,
)

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


# --- 1. スロットとコンテキストの分割 ----------------------------------------
print("=== スロットとコンテキストの分割 ===")
check("-c 2048 -np 2 で1スロットは 1024", slot_context(2048, 2) == 1024,
      f"{slot_context(2048, 2)} トークン")
check("1スロット 2048 が欲しければ -c 4096 -np 2", slot_context(4096, 2) == 2048,
      f"{slot_context(4096, 2)} トークン")
check("スロットを4本にすると1スロットは 512", slot_context(2048, 4) == 512,
      f"{slot_context(2048, 4)} トークン")

kv = {k: v for k, v in QWEN_05B.items() if k != "hidden"}
split = kv_cache_bytes(**kv, seq_len=1024, batch=2)
whole = kv_cache_bytes(**kv, seq_len=2048, batch=1)
check("KVキャッシュの総量は分け方によらず同じ", split.total_bytes == whole.total_bytes,
      f"1024×2本 = {split.total_mb:.1f}MB / 2048×1本 = {whole.total_mb:.1f}MB")

# --- 2. 受け入れ判定（入力 + 出力の予約が1スロットに収まるか）---------------
print("\n=== 受け入れ判定 ===")
np2 = ServingLimits(total_ctx=2048, slots=2)
np4 = ServingLimits(total_ctx=2048, slots=4)
check("スロット2 なら 960 トークンまで受けられる", np2.max_prompt_tokens == 960,
      f"1スロット {np2.ctx_per_slot} − 予約 {np2.reserve_output_tokens}")
check("スロット4 にすると 448 トークンまで縮む", np4.max_prompt_tokens == 448,
      "同時実行を取るとコンテキストを諦めることになる")

short = admit(200, 64, np2)
check("短い入力はそのまま受ける", short.ok and short.max_tokens == 64, short.reason or "-")
long_in = admit(1000, 64, np2)
check("長すぎる入力は受ける前に断る", not long_in.ok, long_in.reason)
clipped = admit(900, 256, np2)
check("枠が足りないときは出力を切り詰める",
      clipped.ok and clipped.max_tokens == 124, clipped.reason)
moved = admit(900, 64, np4)
check("スロット4 では同じ入力が通らなくなる", not moved.ok, moved.reason)
check("期限切れは実行しない", expired(4000.0, np2) and not expired(1000.0, np2),
      f"上限 {np2.queue_deadline_ms:.0f}ms")

drained = drain_queue([QueuedRequest(0.0, 200, 64),        # 4000ms 待ち -> 期限切れ
                       QueuedRequest(3500.0, 200, 64),     # 500ms 待ち -> 実行
                       QueuedRequest(3500.0, 1000, 64)],   # 入力が長すぎる
                      now_ms=4000.0, limits=np2)
check("期限切れと受け入れ不可を実行前に捨てる",
      len(drained.runnable) == 1
      and drained.dropped == {"期限切れ": 1, "受け入れ不可": 1},
      f"実行 {len(drained.runnable)} 件 / 捨てた内訳 {drained.dropped}")

# --- 3. 飽和点の判定 --------------------------------------------------------
print("\n=== 飽和点 ===")
point = find_saturation(MEASURED_SLOTS2)
check("実測（並列1・2・4）の飽和点は 4", point == 4, f"飽和点 = {point}")
check("並列4 ではスループットの伸びが 10% 未満",
      (53.9 - 53.0) / 53.0 < 0.10, f"{(53.9 - 53.0) / 53.0 * 100:.1f}%")
check("刻みが粗い（1 と 4 だけ）と飽和点を見落とす",
      find_saturation(MEASURED_COARSE) is None,
      "スループットが 52.0 → 73.8 tok/s と伸びて見えるため")
check("キュー待ちの近似が計算できる", queue_wait_ms(1772.0, 155.0) == 1617.0,
      f"{queue_wait_ms(1772.0, 155.0):.0f}ms（TTFT 1,772 − 基準 155）")
check("待ちがない場合は 0 になる", queue_wait_ms(52.0, 155.0) == 0.0)

table = markdown_table(MEASURED_SLOTS2,
                       {"model": "qwen05b-q4_k_m.gguf", "slots": 2, "n_ctx_per_slot": 1024,
                        "max_tokens": 48, "requests": 20})
check("引き継げる表に条件と飽和点が入る",
      "測定条件" in table and "飽和点: 4" in table, table.splitlines()[0])

# --- 4. 「遅い」の3分解 -----------------------------------------------------
print("\n=== 失敗診断 ===")
budget = Budget(ttft_ms=300.0, tpot_ms=40.0)
check("並列4 の遅さはキュー待ちと診断される",
      diagnose(1772.0, 20.0, budget, baseline_ttft_ms=155.0) == ["キュー待ち"],
      "TTFT 1,772ms / 基準 155ms")
check("並列1 でも遅いならプリフィルと診断される",
      diagnose(900.0, 20.0, budget, baseline_ttft_ms=900.0) == ["プリフィル"],
      "入力が長い場合")
check("TPOT だけ超えるならデコードと診断される",
      diagnose(155.0, 60.0, budget, baseline_ttft_ms=155.0) == ["デコード"])
check("目標内なら何も返さない",
      diagnose(155.0, 20.0, budget, baseline_ttft_ms=155.0) == [])

# --- 5. ヘルスチェックの3種 -------------------------------------------------
print("\n=== 起動・準備完了・生存 ===")
gate = ReadinessGate(warmup_required=2)
check("起動直後：生きているが準備完了ではない",
      gate.live().ok and not gate.ready().ok and not gate.startup().ok,
      f"phase={gate.phase.value}")
gate.mark_model_loaded()
check("ロード完了：起動は済んだが、まだ受け付けない",
      gate.startup().ok and not gate.ready().ok, f"phase={gate.phase.value}")
gate.record_warmup()
check("ウォームアップ1回目では準備完了にならない", not gate.ready().ok,
      f"warmup={gate.warmup_done}/{gate.warmup_required}")
gate.record_warmup()
check("必要回数のウォームアップで準備完了になる", gate.ready().ok,
      f"phase={gate.phase.value}")
gate.begin_drain()
check("停止処理中は準備完了を外すが生存は保つ",
      not gate.ready().ok and gate.live().ok, f"phase={gate.phase.value}")
broken = ReadinessGate(warmup_required=1)
broken.mark_broken("モデルファイルが読めない")
check("回復不能なときだけ生存が false になる", not broken.live().ok,
      broken.live().detail.get("reason", ""))

check("準備完了は 200、そうでなければ 503",
      probe_response(gate.live()).status_code == 200
      and probe_response(gate.ready()).status_code == 503,
      "監視はステータスコードだけで判定できる")


class _FakeClient:
    """health() が n 回目から True になるスタブ。待たずに起動手順を試せる。"""

    def __init__(self, healthy_after: int) -> None:
        self.calls = 0
        self.healthy_after = healthy_after
        self.generated = 0

    def health(self) -> bool:
        self.calls += 1
        return self.calls >= self.healthy_after

    def generate(self, prompt: str, max_tokens: int = 64) -> GenResult:
        self.generated += 1
        return GenResult("準備完了", 10.0, 30.0, 4, 5.0, 0)


late = ReadinessGate(warmup_required=2)
client = _FakeClient(healthy_after=3)
run_startup(late, client, warmups=2, attempts=5, sleep_s=0.0, sleep=lambda _: None)
check("ロードを待ってからウォームアップし、最後に準備完了になる",
      late.ready().ok and client.generated == 2,
      f"health 呼び出し {client.calls} 回 / ウォームアップ {client.generated} 回")

never = ReadinessGate(warmup_required=2)
run_startup(never, _FakeClient(healthy_after=99), attempts=3, sleep_s=0.0,
            sleep=lambda _: None)
check("待っても読み込めなければ生存を落として再起動に委ねる",
      never.phase is Phase.BROKEN and not never.live().ok,
      never.reason)

# --- 6. 実サーバでの飽和（SKIP_SERVER=1 で飛ばせる）-------------------------
if os.environ.get("SKIP_SERVER") == "1":
    print("\nSKIP_SERVER=1 のため推論サーバを使う検証を飛ばします。")
else:
    from infrakit.client import LlamaClient  # noqa: E402
    from infrakit.load import run_load  # noqa: E402
    from src.session04.sweep import server_conditions  # noqa: E402
    from tools.prompts import with_shared_prefix  # noqa: E402

    print("\n=== 実サーバの設定と飽和 ===")
    live = LlamaClient()
    check("推論サーバに接続できる", live.health(),
          "つながらない場合は `docker compose up -d llama` を実行してください")
    if failures:
        print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
        sys.exit(1)

    cond = server_conditions(live)
    n_slots = int(cond["slots"] or 0)
    n_ctx = int(cond["n_ctx_per_slot"] or 0)
    check("サーバから設定（スロット数・コンテキスト長）が取れる",
          n_slots >= 1 and n_ctx > 0, f"slots={n_slots} / n_ctx={n_ctx}")
    if failures:
        print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
        sys.exit(1)
    print(f"モデル {cond['model']} / スロット {n_slots} / "
          f"1スロット {n_ctx} トークン（全体 {cond['total_ctx']}）")
    check("サーバの n_ctx が計算と一致する",
          slot_context(n_ctx * n_slots, n_slots) == n_ctx,
          f"{n_ctx * n_slots} ÷ {n_slots} = {n_ctx}")

    limits = ServingLimits(total_ctx=n_ctx * n_slots, slots=n_slots)
    check("この設定で受けられる最長の入力が決まる",
          0 < limits.max_prompt_tokens < n_ctx, f"{limits.max_prompt_tokens} トークン")

    prompts = with_shared_prefix()[:6]
    low = run_load(live, prompts, concurrency=1, max_tokens=16,
                   label="s04_c1", conditions=cond)
    over = run_load(live, prompts, concurrency=n_slots * 2, max_tokens=16,
                    label=f"s04_c{n_slots * 2}", conditions=cond)
    print(f"並列 1                : {low.summary()}")
    print(f"並列 {n_slots * 2}（スロット数の2倍）: {over.summary()}")

    check("どちらもエラーなく完走する", low.errors == 0 and over.errors == 0)
    check("スロット数を超えると TTFT が悪化する",
          over.ttft["p50"] > low.ttft["p50"],
          f"{low.ttft['p50']:.0f}ms -> {over.ttft['p50']:.0f}ms")
    check("1リクエストの総時間も悪化する",
          over.total["p50"] > low.total["p50"],
          f"{low.total['p50']:.0f}ms -> {over.total['p50']:.0f}ms")
    wait = queue_wait_ms(over.ttft["p50"], low.ttft["p50"])
    check("悪化ぶんの大半はキュー待ちである",
          wait / max(over.ttft["p50"], 1e-9) > 0.4,
          f"待ち {wait:.0f}ms / TTFT {over.ttft['p50']:.0f}ms "
          f"（{wait / max(over.ttft['p50'], 1e-9) * 100:.0f}%）")
    check("スループットは同時実行の倍率ほど伸びない",
          over.throughput_tps < low.throughput_tps * n_slots * 2,
          f"{low.throughput_tps:.1f} -> {over.throughput_tps:.1f} tok/s")
    print("※ 2点しか測っていないので飽和点そのものは特定できません。"
          "刻みを細かくするのは練習問題で行います。")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション4の検証はすべて成功しました。")
