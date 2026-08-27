#!/usr/bin/env python3
"""復習2（セッション2〜8）の自己検証。

検証するのは**絶対値ではなく関係**である。推論サーバは要らない
（すべて式・文字列・YAML の静的検査で完結するので、環境によってぶれない）。

- セッション2: 条件が違うレポートは並べられない／サイズ順と速さ順は一致しない
- セッション3: KVキャッシュは `-c` で決まる／8B 級は 0.5B の 11 倍
- セッション4: `-c` はスロット数で割られる／どの条件の TPOT を使うかで結論が変わる
- セッション5: 入口の上限は上流の上限から決める
- セッション6: 鍵にテナントとモデルを含めると跨がない／含めないと漏れる
- セッション7: cold は「焼く」と「起動時取得」で同じ／warm で初めて差が出る
- セッション8: メモリ要求は式から出す／`-c` を変えると検査が落ちる
- 復習2: リリースの鎖（1つの変更が連れて動くフィールド）
"""

from __future__ import annotations

import copy
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from infrakit.cache import ExactCache  # noqa: E402
from infrakit.kvcache import LLAMA_8B  # noqa: E402
from src.review02.cache_capacity import (  # noqa: E402
    CEILING_RPS, cold_multiplier, entry_rps_allowed, rate_per_key,
    required_hit_rate, upstream_rps,
)
from src.review02.release_chain import (  # noqa: E402
    MODEL_FILES, ManifestState, Release, cache_action, compare,
    impact_markdown, remeasure, todo,
)
from src.session02.metrics import comparable  # noqa: E402
from src.session04.serving_config import ServingLimits, slot_context  # noqa: E402
from src.session06.cache_keys import CacheScope, ScopedCache, scoped_key  # noqa: E402
from src.session06.prefix_lab import mean_shared_ratio  # noqa: E402
from src.session07.imageplan import BAKED, FETCH, GGUF_MB, VOLUME  # noqa: E402
from src.session08.budget import (  # noqa: E402
    budget_for, grace_required_s, kv_mib, max_request_seconds, rollout_seconds,
    rollout_waves, startup_seconds, surge_memory_mib,
)
from src.session08.manifest import lint_manifest, load_docs, rules_of  # noqa: E402
from tools.prompts import with_shared_prefix, with_unique_prefix  # noqa: E402

SANDBOX = Path(__file__).resolve().parents[2]
REF = SANDBOX / "k8s" / "inference-deployment.yaml"

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def near(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


# 2026-08-15 実測（スロット1・コンテキスト1024・max_tokens=48・20リクエスト・並列1）
# 形式 -> (TTFT p50, TPOT p50)
QUANT = {"f16": (124.0, 26.54), "q8_0": (61.0, 14.63), "q4_k_m": (144.0, 19.58)}

Q4 = MODEL_FILES["q4_k_m"]
Q8 = MODEL_FILES["q8_0"]
PROMPT = "有給休暇の申請期限を教えてください。"

# --- 1. セッション2・3：サイズの順と速さの順は一致しない ---------------------
print("=== セッション2・3：小さいほど速いとは限らない ===")
by_size = sorted(GGUF_MB, key=lambda k: GGUF_MB[k])
by_tpot = sorted(QUANT, key=lambda k: QUANT[k][1])
check("サイズの小さい順は q4_k_m < q8_0 < f16",
      by_size == ["q4_k_m", "q8_0", "f16"],
      " < ".join(f"{k} {GGUF_MB[k]:.1f}MB" for k in by_size))
check("TPOT の速い順は q8_0 < q4_k_m < f16",
      by_tpot == ["q8_0", "q4_k_m", "f16"],
      " < ".join(f"{k} {QUANT[k][1]:.2f}ms" for k in by_tpot))
check("サイズ順と速さ順は一致しない（サイズは速度の代理指標にならない）",
      by_size != by_tpot,
      f"サイズ順 {by_size} / 速さ順 {by_tpot}")

cond_slot1 = {"model": "qwen05b-q8_0.gguf", "max_tokens": 48, "warmup": 2,
              "n_ctx": 1024, "slots": 1}
cond_slot2 = {**cond_slot1, "model": "qwen05b-q4_k_m.gguf", "n_ctx": 2048,
              "slots": 2}
check("量子化の表（スロット1）と同時実行の表（スロット2）は並べられない",
      sorted(comparable(cond_slot1, cond_slot2)) == ["model", "n_ctx", "slots"],
      f"揃っていない項目: {sorted(comparable(cond_slot1, cond_slot2))}")

# --- 2. セッション3・8：KVキャッシュとメモリ要求 -----------------------------
print("\n=== セッション3・8：`-c` を倍にするとメモリ要求が動く ===")
check("KVキャッシュは -c だけで決まる（2048 で 24.0 MiB / 4096 で 48.0 MiB）",
      near(kv_mib(2048), 24.0) and near(kv_mib(4096), 48.0),
      f"{kv_mib(2048):.1f} MiB / {kv_mib(4096):.1f} MiB")
check("8B 級の KVキャッシュは 0.5B の約11倍（-c 2048 で 256.0 MiB）",
      near(kv_mib(2048, LLAMA_8B), 256.0)
      and 10.0 < kv_mib(2048, LLAMA_8B) / kv_mib(2048) < 11.0,
      f"{kv_mib(2048, LLAMA_8B):.1f} MiB "
      f"（{kv_mib(2048, LLAMA_8B) / kv_mib(2048):.1f} 倍）")

b_2048 = budget_for(Q4, 2048)
b_4096 = budget_for(Q4, 4096)
b_q8 = budget_for(Q8, 2048)
check("Q4_K_M・-c 2048 のメモリ要求は 768Mi", b_2048.quantity() == "768Mi",
      b_2048.explain())
check("-c を 4096 にすると 832Mi に上がる（64Mi の段を1つ越える）",
      b_4096.quantity() == "832Mi", b_4096.explain())
check("Q8_0 に差し替えると 896Mi に上がる", b_q8.quantity() == "896Mi",
      b_q8.explain())
check("重みを変えても KVキャッシュは変わらない（動くのは別の項）",
      near(b_2048.kv_mib, b_q8.kv_mib) and b_2048.weights_mib < b_q8.weights_mib,
      f"KV {b_2048.kv_mib:.1f} MiB 共通 / 重み {b_2048.weights_mib:.1f} → "
      f"{b_q8.weights_mib:.1f} MiB")

# --- 3. セッション4・8：どの条件の TPOT を使うかで停止の予算が変わる ---------
print("\n=== セッション4・8：TPOT の条件が停止の予算を決める ===")
check("-c 4096 -np 2 なら1スロットは 2048、最長入力は 1984 トークン",
      slot_context(4096, 2) == 2048
      and ServingLimits(total_ctx=4096, slots=2).max_prompt_tokens == 1984)
req_par1 = max_request_seconds(960, tpot_ms=19.19)
req_par2 = max_request_seconds(960, tpot_ms=36.74)
check("並列2 の TPOT（36.74ms）は並列1（19.19ms）の約1.9倍",
      1.8 < 36.74 / 19.19 < 2.0, f"{36.74 / 19.19:.2f} 倍")
check("同じ 960 トークンでも、使う TPOT で生成の最長が2倍近く変わる",
      req_par2 > req_par1 * 1.8,
      f"並列1 前提 {req_par1:.1f} 秒 / 並列2 前提 {req_par2:.1f} 秒")
need_par1 = grace_required_s(15.0, req_par1, 5.0)
need_par2 = grace_required_s(15.0, req_par2, 5.0)
check("猶予 60 秒は並列2 前提でもまだ足りる（残りは 5 秒未満）",
      need_par2 <= 60.0 and 60.0 - need_par2 < 5.0,
      f"必要 {need_par2:.1f} 秒（並列1 前提なら {need_par1:.1f} 秒）")
need_long = grace_required_s(15.0, max_request_seconds(1984, tpot_ms=36.74), 5.0)
check("-c 4096 にして生成上限を 1984 まで上げると 60 秒では足りない",
      need_long > 60.0, f"必要 {need_long:.1f} 秒 → 94 秒以上に伸ばす")

# --- 4. セッション6：鍵の材料が境界を決める ---------------------------------
print("\n=== セッション6：鍵に何を入れたかが境界になる ===")
scope_soumu = CacheScope(tenant_id="soumu", visibility=frozenset({"general"}))
scope_eigyo = CacheScope(tenant_id="eigyo", visibility=frozenset({"general"}))
scope_hr = CacheScope(tenant_id="soumu",
                      visibility=frozenset({"general", "hr-confidential"}))
cache = ScopedCache()
cache.put(scope_soumu, PROMPT, "総務部の可視範囲で作った答え", 730.0)
check("同じ質問でもテナントが違えばヒットしない",
      cache.get(scope_eigyo, PROMPT) is None)
check("同じテナントでも可視範囲が違えばヒットしない",
      cache.get(scope_hr, PROMPT) is None)
check("同じスコープなら2回目はヒットする",
      cache.get(scope_soumu, PROMPT) == "総務部の可視範囲で作った答え")

leaky = ExactCache()
leaky.put(PROMPT, "人事部だけが見られる資料に基づく答え", 730.0)
check("鍵をプロンプトだけにすると、誰が聞いても同じ答えが返る（漏洩）",
      leaky.get(PROMPT) == "人事部だけが見られる資料に基づく答え")

hot = CacheScope(tenant_id="soumu", visibility=frozenset({"general"}),
                 temperature=0.7)
check("温度が 0 でないリクエストはキャッシュしない",
      not hot.cacheable and cache.get(hot, PROMPT) is None)

key_q4 = scoped_key(CacheScope(tenant_id="soumu",
                               visibility=frozenset({"general"}),
                               model="qwen05b-q4_k_m.gguf"), PROMPT)
key_q8 = scoped_key(CacheScope(tenant_id="soumu",
                               visibility=frozenset({"general"}),
                               model="qwen05b-q8_0.gguf"), PROMPT)
check("鍵にモデルが入っているので、差し替えると鍵が変わる", key_q4 != key_q8,
      f"{key_q4[:8]}... → {key_q8[:8]}...")

shared = mean_shared_ratio(with_shared_prefix())
unique = mean_shared_ratio(with_unique_prefix())
check("共通接頭辞があると前方一致率が上がる（文字列だけで決まるのでぶれない）",
      shared > unique * 5.0,
      f"共通接頭辞 {shared:.3f} / 先頭に一意な識別子 {unique:.3f}")

# --- 5. セッション5・6：ヒット率を入口の上限に翻訳する ----------------------
print("\n=== セッション5・6：ヒット率は入口の上限に翻訳できる ===")
check("上流の上限 1.13 rps・ヒット率 0.5 なら入口は 2.26 rps まで開けられる",
      near(entry_rps_allowed(CEILING_RPS, 0.5), 2.26),
      f"{entry_rps_allowed(CEILING_RPS, 0.5):.2f} rps")
check("そのとき上流に届くのは上限以内に収まる",
      upstream_rps(entry_rps_allowed(CEILING_RPS, 0.5), 0.5)
      <= CEILING_RPS + 1e-9,
      f"{upstream_rps(entry_rps_allowed(CEILING_RPS, 0.5), 0.5):.2f} rps "
      f"≤ {CEILING_RPS:.2f} rps")
check("3テナントに配ると1キーあたり 0.75 rps（切り捨て）",
      near(rate_per_key(entry_rps_allowed(CEILING_RPS, 0.5), 3), 0.75))
check("ヒット率 0 のときの入口は上流の上限そのもの",
      near(entry_rps_allowed(CEILING_RPS, 0.0), 1.13))
check("入口で 3.00 rps を受けるには 0.624 以上のヒット率が必要",
      near(required_hit_rate(3.0, CEILING_RPS), 0.624),
      f"{required_hit_rate(3.0, CEILING_RPS):.3f}")
check("キャッシュが冷えると、開けた入口はそのまま上流の 2.00 倍になる",
      near(cold_multiplier(entry_rps_allowed(CEILING_RPS, 0.5), CEILING_RPS),
           2.0),
      "冷えたら飽和する設計なので、縮退（503 と Retry-After）を先に用意する")

# --- 6. セッション7：cold は同じ、warm で差が出る ---------------------------
print("\n=== セッション7：配り方の差は warm でしか出ない ===")
w4 = GGUF_MB["q4_k_m"]
w8 = GGUF_MB["q8_0"]
check("cold は「焼く」と「起動時に取得」で一致する（重みを1回運ぶのは同じ）",
      near(startup_seconds(BAKED, w4), startup_seconds(FETCH, w4), 1e-9),
      f"どちらも {startup_seconds(BAKED, w4):.2f} 秒")
check("warm では「焼く」が最短になる（ここにしか利点は出ない）",
      startup_seconds(BAKED, w4, image_cached=True)
      < startup_seconds(FETCH, w4, image_cached=True),
      f"焼く {startup_seconds(BAKED, w4, image_cached=True):.2f} 秒 / "
      f"起動時取得 {startup_seconds(FETCH, w4, image_cached=True):.2f} 秒")
check("ボリュームの warm は「焼く」と同じ（重みがすでにある前提の値）",
      near(startup_seconds(VOLUME, w4, image_cached=True),
           startup_seconds(BAKED, w4, image_cached=True), 1e-9))
check("Q8_0 は生成が速いが、配るのは重くなる（起動が伸びる）",
      startup_seconds(FETCH, w8) > startup_seconds(FETCH, w4)
      and QUANT["q8_0"][1] < QUANT["q4_k_m"][1],
      f"起動 {startup_seconds(FETCH, w4):.1f} → "
      f"{startup_seconds(FETCH, w8):.1f} 秒 / TPOT 19.58 → 14.63 ms")
check("replicas 2・maxSurge 1・maxUnavailable 0 なら 2 波で置き換わる",
      rollout_waves(2, 1, 0) == 2
      and near(rollout_seconds(2, 1, startup_seconds(FETCH, w4)),
               startup_seconds(FETCH, w4) * 2, 1e-9),
      f"{rollout_seconds(2, 1, startup_seconds(FETCH, w4)):.1f} 秒")
check("maxSurge のあいだ余分に必要なメモリは 1 Pod ぶん",
      near(surge_memory_mib(1, 832.0), 832.0), "832 MiB を空けておく")

# --- 7. セッション8：マニフェストの検査は式に連動している -------------------
print("\n=== セッション8：`-c` を変えると検査が落ちる ===")
docs = load_docs(REF)
findings = lint_manifest(docs)
check("いまのマニフェストはエラー 0 件", rules_of(findings, "error") == set(),
      f"警告: {sorted(rules_of(findings, 'warn'))}")
check("残っている警告は理由を書いてある2件だけ",
      rules_of(findings, "warn") == {"image-digest", "probe-paths-shared"})


def with_ctx(source: list[dict], ctx: int) -> list[dict]:
    """`-c` の値だけを差し替えたコピーを返す（ファイルは書き換えない）。"""
    clone = copy.deepcopy(source)
    for doc in clone:
        if doc.get("kind") != "Deployment":
            continue
        spec = ((doc.get("spec") or {}).get("template") or {}).get("spec") or {}
        for container in spec.get("containers") or []:
            args = container.get("args") or []
            for i, item in enumerate(args):
                if str(item) == "-c" and i + 1 < len(args):
                    args[i + 1] = str(ctx)
    return clone


longer = lint_manifest(with_ctx(docs, 4096))
check("-c を 4096 にすると requests と limits の両方が足りなくなる",
      {"memory-requests", "memory-limits"} <= rules_of(longer, "error"),
      f"エラー: {sorted(rules_of(longer, 'error'))}")

# --- 8. 復習2：リリースの鎖 -------------------------------------------------
print("\n=== 復習2：リリースの鎖（S03 → S04 → S06 → S07 → S08）===")
before = Release("いま動いている構成")
to_q8 = replace(before, label="モデルを q8_0 に差し替える", model_path=Q8,
                tpot_measured=False)
rows = {c.item: c for c in compare(before, to_q8)}
check("モデルを変えると重み・メモリ要求・起動・鍵が動く",
      all(rows[k].changed for k in ("重みのサイズ", "requests/limits.memory",
                                    "起動の見積り（cold）",
                                    "応答キャッシュの鍵の材料")),
      f"requests {rows['requests/limits.memory'].before} → "
      f"{rows['requests/limits.memory'].after}")
check("モデルを変えても KVキャッシュとコンテキストは動かない",
      not rows["KVキャッシュ"].changed
      and not rows["1スロットのコンテキスト"].changed,
      "動くのは「重み」の項だけ")
check("測り直す対象に TPOT が入る",
      any("TPOT" in name for name, _ in remeasure(before, to_q8)),
      f"{len(remeasure(before, to_q8))} 件")
check("鍵が変わるので、古いエントリは使われない（TTL 対策として全消しを案内）",
      "invalidate_all" in cache_action(before, to_q8)[0])
items = todo(to_q8, ManifestState())
check("直すのは requests/limits.memory と、TPOT を測ってからの停止の猶予",
      len(items) == 2 and "896Mi" in items[0]
      and "terminationGracePeriodSeconds" in items[1],
      items[0])

to_long = replace(before, label="-c を 4096 にして生成上限を 1984 にする",
                  ctx_total=4096, max_output_tokens=1984, tpot_ms=36.74)
long_rows = {c.item: c for c in compare(before, to_long)}
check("-c を変えるとメモリ要求とコンテキストの取り分が動く",
      long_rows["KVキャッシュ"].changed
      and long_rows["requests/limits.memory"].after == "832Mi"
      and long_rows["受けられる最長入力"].after == "1984 トークン")
check("-c を変えても重みと起動時間は動かない",
      not long_rows["重みのサイズ"].changed
      and not long_rows["起動の見積り（cold）"].changed)
check("鍵の材料は変わらない（`-c` は答えの内容を変えないため）",
      not long_rows["応答キャッシュの鍵の材料"].changed
      and cache_action(before, to_long)[0] == "何もしなくてよい")
long_items = todo(to_long, ManifestState())
check("停止の猶予は 94 秒以上に伸ばす必要が出る",
      any("94 秒以上" in t for t in long_items),
      " / ".join(long_items))

no_change = replace(before, label="何も変えない")
check("何も変えなければ直すところも測り直すものも無い",
      todo(no_change, ManifestState()) == []
      and remeasure(before, no_change) == []
      and cache_action(before, no_change)[0] == "何もしなくてよい")

text = impact_markdown(before, to_q8)
check("引き継げるメモに測定条件と根拠のセッションが入る",
      "2026-08-15" in text and "S03+S08" in text and "測り直すもの" in text,
      text.splitlines()[0])

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\n復習2の検証はすべて成功しました。")
