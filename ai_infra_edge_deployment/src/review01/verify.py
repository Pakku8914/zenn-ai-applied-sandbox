#!/usr/bin/env python3
"""復習1（セッション2〜5）の自己検証。

検証するのは**絶対値ではなく関係**である。

- セッション2: 総時間の式で組み直せること／p95 に必要な件数／条件が違えば比べられない
- セッション3: KVキャッシュの式と、モデル規模で1桁変わること
- セッション4: `-c` はスロット数で割られること／飽和点／キュー待ちの分離
- セッション5: トークンバケット（時計を注入して決定的に）／429 と 503／
               リトライ予算とタイムアウトの階段／サーキットブレーカ／振り分け
- 復習1: 容量の鎖（メモリと飽和点のどちらが先に来るか）と一次切り分け

推論サーバを使う検証は SKIP_SERVER=1 で飛ばせる。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from infrakit.kvcache import LLAMA_8B, QWEN_05B, kv_cache_bytes, max_concurrent  # noqa: E402
from src.review01.capacity_chain import build_chain, memo  # noqa: E402
from src.review01.triage import CASES, Observation, triage  # noqa: E402
from src.session02.metrics import (  # noqa: E402
    check_slo, comparable, effective_quantile, min_samples, rebuild_total,
    requests_per_second, tokens_per_second,
)
from src.session04.serving_config import (  # noqa: E402
    MEASURED_COARSE, MEASURED_SLOTS2, Budget, ServingLimits, find_saturation,
    queue_wait_ms, slot_context,
)
from src.session05.gateway_policy import GateLimits, KeyedRateLimiter, decide  # noqa: E402
from src.session05.resilience import (  # noqa: E402
    CircuitBreaker, IdempotencyStore, RetryPolicy, TimeoutPlan,
    offered_load_multiplier, per_try_timeout_ms,
)
from src.session05.routing import route  # noqa: E402

failures: list[str] = []
now = 0.0                     # 注入する時計（時間依存の挙動を決定的に確かめる）


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def near(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


# 2026-08-15 実測（スロット1・コンテキスト1024・max_tokens=48・20リクエスト・並列1・
# aarch64 / CPU 2コア / メモリ 5.8GB / Python 3.12.13 / llama.cpp `-t 2`）
# 形式 -> (TTFT p50, TTFT p95, TPOT p50, 総時間 p50)
QUANT = {
    "f16": (124.0, 174.0, 26.54, 1353.0),
    "q8_0": (61.0, 82.0, 14.63, 730.0),
    "q4_k_m": (144.0, 189.0, 19.58, 1051.0),
}

# --- 1. セッション2：定規 ---------------------------------------------------
print("=== セッション2：測り方 ===")
for name, (ttft, _p95, tpot, total) in QUANT.items():
    built = rebuild_total(ttft, tpot, 48)
    gap = abs(built - total) / total
    check(f"{name}: TTFT と TPOT から総時間を組み直せる", gap < 0.03,
          f"式 {built:.0f}ms / 実測 p50 {total:.0f}ms（差 {gap * 100:.1f}%）")

long_out = {k: rebuild_total(v[0], v[2], 256) for k, v in QUANT.items()}
check("出力 256 トークンでも総時間の順位は Q8_0 < Q4_K_M < f16",
      long_out["q8_0"] < long_out["q4_k_m"] < long_out["f16"],
      " / ".join(f"{k} {v:.0f}ms" for k, v in long_out.items()))
check("TTFT p95 で見ると f16 が Q4_K_M より速い（指標を変えると順位が変わる）",
      QUANT["q8_0"][1] < QUANT["f16"][1] < QUANT["q4_k_m"][1],
      f"Q8_0 {QUANT['q8_0'][1]:.0f} < f16 {QUANT['f16'][1]:.0f} "
      f"< Q4_K_M {QUANT['q4_k_m'][1]:.0f} ms")
check("総時間 4,000ms なら Q8_0 だけが通り、3,000ms では全滅する",
      long_out["q8_0"] < 4000.0 and long_out["q8_0"] > 3000.0
      and min(long_out.values()) > 3000.0,
      f"最速でも {min(long_out.values()):.0f}ms")

check("p95 は 20 件、p99 は 100 件が必要", min_samples(0.95) == 20
      and min_samples(0.99) == 100)
check("8 件で p95 と名乗ると実際は p87.5 でしかない",
      near(effective_quantile(8, 0.95), 0.875),
      f"実効 {effective_quantile(8, 0.95):.3f}")
check("20 件なら p95 が p95 になる", near(effective_quantile(20, 0.95), 0.95, 1e-12))

cond_a = {"max_tokens": 48, "warmup": 2, "model": "qwen05b-q4_k_m.gguf", "slots": 2}
check("max_tokens が違うレポートは並べられない",
      comparable(cond_a, {**cond_a, "max_tokens": 24}) == ["max_tokens"])
check("条件が同じなら並べてよい", comparable(cond_a, dict(cond_a)) == [])

tps = tokens_per_second(48, 1000.0)
rps = requests_per_second(1, 1000.0)
check("tok/s と rps は別の単位である", near(tps, 48.0) and near(rps, 1.0),
      f"{tps:.1f} tok/s = {rps:.2f} rps（出力 48 トークンのとき）")
ratio = 53.0 / 1.13
check("実測の tok/s ÷ rps は1リクエストの出力トークン数に近い",
      40.0 < ratio < 56.0, f"53.0 tok/s ÷ 1.13 rps = {ratio:.1f} トークン/件")
check("SLO 違反は指標.分位点の形で返る",
      check_slo({"ttft": {"p50": 1772.0, "p95": 2064.0}}, {"ttft.p95": 500.0})
      == ["ttft.p95"])

# --- 2. セッション3：KVキャッシュ -------------------------------------------
print("\n=== セッション3：KVキャッシュ ===")
qwen = {k: v for k, v in QWEN_05B.items() if k != "hidden"}
llama = {k: v for k, v in LLAMA_8B.items() if k != "hidden"}

one_qwen = kv_cache_bytes(**qwen, seq_len=1, batch=1)
one_llama = kv_cache_bytes(**llama, seq_len=1, batch=1)
check("0.5B は1トークン 12,288 バイト（12.00 KB）",
      one_qwen.per_token_bytes == 12288 and near(one_qwen.per_token_kb, 12.0))
check("8B 級は1トークン 128.00 KB",
      one_llama.per_token_bytes == 131072 and near(one_llama.per_token_kb, 128.0))
check("8B 級は 0.5B の約11倍",
      one_llama.per_token_bytes / one_qwen.per_token_bytes > 10.0,
      f"{one_llama.per_token_bytes / one_qwen.per_token_bytes:.1f} 倍")

split = kv_cache_bytes(**qwen, seq_len=1024, batch=2)
whole = kv_cache_bytes(**qwen, seq_len=2048, batch=1)
check("同時2本×1024 と 1本×2048 は同じメモリ量",
      split.total_bytes == whole.total_bytes,
      f"どちらも {split.total_mb:.1f} MB")

GB = 1024 ** 3
check("1GB で持てる本数は 0.5B が 42 本、8B 級が 4 本（系列長 2048）",
      max_concurrent(GB, 2048, **qwen) == 42
      and max_concurrent(GB, 2048, **llama) == 4,
      f"0.5B {max_concurrent(GB, 2048, **qwen)} 本 / "
      f"8B 級 {max_concurrent(GB, 2048, **llama)} 本")

# --- 3. セッション4：スロットと飽和点 ---------------------------------------
print("\n=== セッション4：サービング構成 ===")
check("-c 2048 -np 2 で1スロットは 1024", slot_context(2048, 2) == 1024)
np2 = ServingLimits(total_ctx=2048, slots=2)
np4 = ServingLimits(total_ctx=2048, slots=4)
check("スロットを増やすと受けられる入力が短くなる",
      np2.max_prompt_tokens == 960 and np4.max_prompt_tokens == 448,
      f"-np 2 で {np2.max_prompt_tokens} / -np 4 で {np4.max_prompt_tokens} トークン")
check("実測（並列1・2・4）の飽和点は 4", find_saturation(MEASURED_SLOTS2) == 4)
check("刻みが粗い（1 と 4 だけ）と飽和点を見落とす",
      find_saturation(MEASURED_COARSE) is None)
check("並列4 の TTFT 悪化はほぼキュー待ちである",
      queue_wait_ms(1772.0, 155.0) == 1617.0,
      "1,772 − 155 = 1,617ms が待ち")
check("並列2 では待ちが発生していない（TTFT が基準より良い）",
      queue_wait_ms(52.0, 155.0) == 0.0)
check("スループットは飽和後ほとんど伸びない",
      (53.9 - 53.0) / 53.0 < 0.10, f"{(53.9 - 53.0) / 53.0 * 100:.1f}%")

# --- 4. セッション5：入口 ---------------------------------------------------
print("\n=== セッション5：入口の守り ===")
now = 0.0
limiter = KeyedRateLimiter(rate=2.0, burst=4.0, clock=lambda: now)
allowed = [limiter.check("tenant-a").allowed for _ in range(4)]
denied = limiter.check("tenant-a")
check("burst 分は通り、空になったら断る（時計を注入して決定的に）",
      all(allowed) and not denied.allowed,
      f"通した {sum(allowed)} 件 → 5件目は 429")
check("断るときは待つべき秒数を返す", near(denied.retry_after_s, 0.5),
      f"Retry-After = {denied.retry_after_s:.2f} 秒")
check("バケットはキーごとに独立している", limiter.check("tenant-b").allowed,
      "tenant-a が使い切っても tenant-b は通る")
now = 0.5
refilled = limiter.check("tenant-a")
check("0.5 秒で rate × 0.5 = 1 件ぶん補充される",
      refilled.allowed and near(refilled.tokens_left, 0.0, 1e-6))

gate = GateLimits(max_inflight=2, max_queue=2, queue_deadline_ms=1034.0)
check("空きがあれば走らせる", decide(1, 0, gate).action == "run")
check("埋まっていて待ち枠があれば待たせる", decide(2, 0, gate).action == "queue")
reject = decide(2, 2, gate)
check("処理中と待ちが上限なら 503 で断る",
      reject.action == "reject" and reject.status_code == 503,
      "429 は相手が速い、503 はこちらが手一杯")

check("再送3回・予算なしは入力が4倍になる", near(offered_load_multiplier(4), 4.0))
check("リトライ予算 10% なら 1.1 倍に収まる",
      near(offered_load_multiplier(4, 0.1), 1.1))
storm = offered_load_multiplier(4) * 1.13
check("4倍の入力は実測の上限スループットをはるかに超える", storm > 1.15,
      f"1.13 rps × 4 = {storm:.2f} rps（実測の最大は 1.15 rps）")

per_try = per_try_timeout_ms(3000.0, 2, 200.0)
check("1回分のタイムアウトはバックオフを引いてから割る", near(per_try, 1400.0),
      f"(3000 − 200) ÷ 2 = {per_try:.0f} ms")
good = TimeoutPlan(client_ms=5000.0, gateway_ms=3000.0, per_try_ms=per_try,
                   attempts=2, backoff_total_ms=200.0)
bad = TimeoutPlan(client_ms=3000.0, gateway_ms=3000.0, per_try_ms=2000.0,
                  attempts=2, backoff_total_ms=0.0)
check("外側から内側へ短くなる計画は指摘なし", good.problems() == [],
      f"最悪 {good.worst_case_ms:.0f}ms ≤ ゲートウェイ {good.gateway_ms:.0f}ms")
check("同じ値・超過する計画は2つ指摘される", len(bad.problems()) == 2,
      " / ".join(bad.problems()))
check("1回分 1,400ms は並列1 の総時間（1,034ms）を通すが飽和時（3,379ms）は通さない",
      1034.0 < per_try < 3379.0,
      "飽和しているときは待たせるのではなく落とす判断になる")

policy = RetryPolicy()
check("429 は再送しない（相手に速度を伝えるべき応答）",
      policy.should_retry(429, 0, idempotent=True)[0] is False,
      policy.should_retry(429, 0, idempotent=True)[1])
check("503 は再送してよい", policy.should_retry(503, 0, idempotent=True)[0] is True)
check("冪等でない要求は再送しない",
      policy.should_retry(503, 0, idempotent=False)[0] is False)
check("試行回数の上限を超えたら再送しない",
      policy.should_retry(503, 1, idempotent=True)[0] is False)

now = 0.0
store = IdempotencyStore(clock=lambda: now)
check("同じ冪等キーの2回目は処理中として断る",
      store.begin("req-1").state == "new"
      and store.begin("req-1").status_code == 409)
store.complete("req-1", {"text": "有給は前日までに申請してください"})
done = store.begin("req-1")
check("完了後は保存した応答をそのまま返す（二重生成しない）",
      done.state == "done" and done.response is not None)

breaker = CircuitBreaker(failure_threshold=5, cooldown_s=10.0,
                         success_threshold=2, clock=lambda: now)
for _ in range(5):
    breaker.record(False)
check("失敗が続くと open になり、呼ぶのをやめる",
      breaker.state == "open" and not breaker.allow())
check("open のときは残りの冷却時間を返せる", near(breaker.retry_after_s(), 10.0),
      f"Retry-After = {breaker.retry_after_s():.0f} 秒")
now = 10.0
check("冷却が明けたら half_open で試しに1本通す",
      breaker.allow() and breaker.state == "half_open")
breaker.record(True)
breaker.record(True)
check("成功が続けば closed に戻る", breaker.state == "closed")

check("既定は測って速かった階層に流す", route(200, 64).tier == "fast")
check("長い出力が要るときだけ品質階層へ", route(200, 200).tier == "quality")
batch = route(200, 200, priority="batch")
check("急がない要求は速い階層に落として出力も切り詰める",
      batch.tier == "fast" and batch.degraded and batch.max_tokens == 64)
check("どの階層にも収まらない入力は受ける前に断る",
      route(1200, 64).status_code == 413)

# --- 5. 復習1：容量の鎖 -----------------------------------------------------
print("\n=== 復習1：容量の鎖（S3 → S4 → S5）===")
chain = build_chain()
check("① メモリだけなら 85 本持てる（0.5B・系列長1024・1GB）",
      chain.kv_max_streams == 85, f"{chain.kv_max_streams} 本")
check("② 採用する -np は飽和点の手前（2）になる",
      chain.slots == 2 and chain.saturation_at == 4
      and chain.safe_concurrency == 2,
      f"飽和点 {chain.saturation_at} / 採用 -np {chain.slots}")
check("② メモリではなく飽和点が先に来ている", chain.binding == "飽和点",
      f"メモリ {chain.kv_max_streams} 本 vs 飽和点の手前 {chain.safe_concurrency}")
check("②' -c は 2048、1スロット 1024、最長入力 960 トークン",
      chain.total_ctx == 2048 and chain.ctx_per_slot == 1024
      and chain.max_prompt_tokens == 960)
check("③ rate はテナント数で割って切り捨てる",
      near(chain.rate_per_key, 0.37),
      f"{chain.ceiling_rps:.2f} rps ÷ {chain.tenants} = "
      f"{chain.rate_per_key:.2f} rps/キー")
check("③ 全テナントが上限まで使っても上流の処理能力を超えない",
      chain.rate_total <= chain.ceiling_rps + 1e-9,
      f"合計 {chain.rate_total:.2f} rps ≤ 上限 {chain.ceiling_rps:.2f} rps")
check("③ burst と max_inflight は上流のスロット数に揃う",
      chain.max_inflight == chain.slots and near(chain.burst_per_key, 2.0))

tight = build_chain(model="llama8b", seq_len=2048, memory_gb=0.25)
check("予算を絞ると今度はメモリが先に来る",
      tight.kv_max_streams == 1 and tight.slots == 1 and tight.binding == "メモリ",
      f"メモリ {tight.kv_max_streams} 本 / 採用 -np {tight.slots}")
check("メモリが効く側では 1スロットに系列長ぶんのコンテキストを取れる",
      tight.ctx_per_slot == 2048 and tight.max_prompt_tokens == 1984)
text = memo(chain)
check("メモに値と根拠と再測条件が入る",
      "根拠" in text and "再測が必要になる条件" in text and "2026-08-15" in text,
      text.splitlines()[0])

# --- 6. 復習1：一次切り分け -------------------------------------------------
print("\n=== 復習1：一次切り分け（S02 → S05 → S04）===")
expected = {
    "A": ["比較不能"],
    "B": ["キュー待ち"],
    "C": ["デコード"],
    "D": ["入口・レート制限"],
    "E": ["入口・容量", "キュー待ち"],
    "F": ["目標内"],
}
for obs, baseline, budget, against in CASES:
    key = obs.label.split()[0]
    got = [f.label for f in triage(obs, baseline_ttft_ms=baseline, budget=budget,
                                   against=against)]
    check(f"{obs.label} → {' / '.join(expected[key])}", got == expected[key],
          f"実際: {' / '.join(got)}")

# --- 7. 実サーバでの関係の確認（SKIP_SERVER=1 で飛ばせる）-------------------
if os.environ.get("SKIP_SERVER") == "1":
    print("\nSKIP_SERVER=1 のため推論サーバを使う検証を飛ばします。")
else:
    from infrakit.client import LlamaClient  # noqa: E402
    from infrakit.load import run_load  # noqa: E402
    from src.session04.sweep import server_conditions  # noqa: E402
    from tools.prompts import with_shared_prefix  # noqa: E402

    print("\n=== 実サーバ：条件を揃えて並列1 と スロット数×2 を比べる ===")
    live = LlamaClient()
    check("推論サーバに接続できる", live.health(),
          "つながらない場合は `docker compose up -d llama` を実行してください")
    if failures:
        print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
        sys.exit(1)

    cond = server_conditions(live)
    n_slots = max(int(cond["slots"] or 1), 1)
    over_c = max(n_slots * 2, 2)
    prompts = with_shared_prefix()[:6]
    low = run_load(live, prompts, concurrency=1, max_tokens=16,
                   label="review01_c1", conditions=cond)
    over = run_load(live, prompts, concurrency=over_c, max_tokens=16,
                    label=f"review01_c{over_c}", conditions=cond)
    low.to_json()
    over.to_json()
    print(f"並列 1        : {low.summary()}")
    print(f"並列 {over_c}（スロット数の2倍）: {over.summary()}")

    check("どちらもエラーなく完走する", low.errors == 0 and over.errors == 0)
    keys = ("max_tokens", "warmup", "model", "n_ctx_per_slot", "slots")
    check("2本のレポートは条件が揃っているので並べてよい",
          comparable(low.conditions, over.conditions, keys=keys) == [],
          f"model={cond['model']} / 1スロット {cond['n_ctx_per_slot']} / "
          f"slots={cond['slots']}")
    check("スロット数を超えると TTFT が悪化する",
          over.ttft["p50"] > low.ttft["p50"],
          f"{low.ttft['p50']:.0f}ms -> {over.ttft['p50']:.0f}ms")
    wait = queue_wait_ms(over.ttft["p50"], low.ttft["p50"])
    check("悪化ぶんの大半はキュー待ちである",
          wait / max(over.ttft["p50"], 1e-9) > 0.3,
          f"待ち {wait:.0f}ms / TTFT {over.ttft['p50']:.0f}ms")
    check("スループットは同時実行の倍率ほど伸びない",
          over.throughput_tps < low.throughput_tps * over_c,
          f"{low.throughput_tps:.1f} -> {over.throughput_tps:.1f} tok/s")
    if over.throughput_rps > 0:
        per_req = over.throughput_tps / over.throughput_rps
        check("tok/s ÷ rps は1件の出力トークン数に収まる",
              0 < per_req <= 17.0, f"{per_req:.1f} トークン/件（max_tokens=16）")

    budget = Budget(ttft_ms=low.ttft["p50"] * 1.2,
                    tpot_ms=max(low.tpot["p50"] * 3.0, 1.0))
    obs = Observation("実サーバ（スロット数の2倍）", over.ttft["p50"],
                      over.tpot["p50"], over.total["p50"], over.errors, {},
                      over.conditions)
    labels = [f.label for f in triage(obs, baseline_ttft_ms=low.ttft["p50"],
                                      budget=budget)]
    check("一次切り分けが時間の問題として候補を立てる",
          any(x in labels for x in ("キュー待ち", "プリフィル")),
          f"候補: {' / '.join(labels)}")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\n復習1の検証はすべて成功しました。")
