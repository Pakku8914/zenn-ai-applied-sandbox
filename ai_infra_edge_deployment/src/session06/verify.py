#!/usr/bin/env python3
"""セッション6の自己検証：キャッシュが効いていて、かつ混ざっていないこと。

検証するのは「関係」だけである（絶対値の期待値は書かない）。
  - スコープを鍵に含めると、立場ごとに別の鍵になる
  - 鍵に権限を含めないと他テナントの答えが返る（意図的な欠けの再現）
  - 共通の接頭辞があると前方一致率が上がる
  - TTL・テナント単位・資料バージョン単位で消せる
  - セマンティックキャッシュは閾値を緩めるほど誤ヒットが増える

推論サーバとゲートウェイを使う検証は SKIP_SERVER=1 で飛ばせる。

    python src/session06/verify.py
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.session06.cache_keys import (  # noqa: E402
    CacheScope, ScopedCache, scoped_key, unsafe_key,
)
from src.session06.prefix_lab import compare_layouts, mean_shared_ratio  # noqa: E402
from src.session06.safe_gateway import create_app, visibility_of  # noqa: E402
from src.session06.semantic_cache import (  # noqa: E402
    PAIRS, SemanticCache, markdown_table, sweep,
)
from src.session06.tenant_leak import GENERAL, HR, print_report, replay  # noqa: E402
from tools.prompts import with_shared_prefix, with_unique_prefix  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


QUESTION = "駐車場の月額利用料はいくらですか。"

# --- 1. キャッシュキーに何を含めるか ----------------------------------------
print("=== キャッシュキー ===")
hq = CacheScope(tenant_id="minato-hq", visibility=GENERAL)
hq_again = CacheScope(tenant_id="minato-hq", visibility=frozenset({"general"}))
check("同じスコープ・同じプロンプトなら鍵は同じ",
      scoped_key(hq, QUESTION) == scoped_key(hq_again, QUESTION))

variants = {
    "テナント": replace(hq, tenant_id="minato-logi"),
    "可視範囲": replace(hq, visibility=HR),
    "モデル": replace(hq, model="qwen05b-q8_0.gguf"),
    "生成長": replace(hq, max_tokens=128),
    "資料バージョン": replace(hq, corpus_version="2026-09-01"),
}
for name, scope in variants.items():
    check(f"{name}が違えば鍵が変わる",
          scoped_key(scope, QUESTION) != scoped_key(hq, QUESTION))

three_scopes = [hq, variants["テナント"], variants["可視範囲"]]
check("スコープを含めると3つの立場で別々の鍵になる",
      len({scoped_key(s, QUESTION) for s in three_scopes}) == 3)
check("【意図的な欠け】プロンプトだけの鍵は3つの立場で同じ鍵になる",
      len({unsafe_key(QUESTION) for _ in three_scopes}) == 1,
      "infrakit.cache.ExactCache がこの鍵を使っている")
check("温度が0でなければキャッシュ対象外",
      hq.cacheable and not replace(hq, temperature=0.7).cacheable)
check("ロールから可視範囲が決まる",
      visibility_of("employee") == GENERAL and visibility_of("employee,hr") == HR,
      f"employee -> {sorted(visibility_of('employee'))} / "
      f"employee,hr -> {sorted(visibility_of('employee,hr'))}")

# --- 2. テナントと権限を跨ぐ事故 --------------------------------------------
print("\n=== キャッシュがテナントを跨ぐ事故 ===")
unsafe_report = replay("unsafe")
scoped_report = replay("scoped")
print_report(unsafe_report)
print()
print_report(scoped_report)
print()
check("鍵に権限を含めないと他テナント・他権限の答えが返る",
      len(unsafe_report.leaks) == 2, f"漏洩 {unsafe_report.leaks}")
check("スコープを鍵に含めると漏れない", len(scoped_report.leaks) == 0,
      f"漏洩 {len(scoped_report.leaks)} 件")
check("同じ立場からの再質問は正しくヒットする", scoped_report.hits == 1,
      f"ヒット {scoped_report.hits} 件（5. 本社の一般社員の再質問）")
check("事故を塞ぐと推論回数は増える",
      scoped_report.misses > unsafe_report.misses,
      f"{unsafe_report.misses} 回 -> {scoped_report.misses} 回（安全のための費用）")

# --- 3. 前方一致（プロンプトキャッシュ）が効く条件 --------------------------
print("\n=== 前方一致 ===")
shared_ratio = mean_shared_ratio(with_shared_prefix())
unique_ratio = mean_shared_ratio(with_unique_prefix())
print(f"共通のシステムプロンプトを先頭に置く: 平均 {shared_ratio:.3f}")
print(f"先頭に一意なリクエストIDを付ける: 平均 {unique_ratio:.3f}")
check("共通の接頭辞があると前方一致率が上がる",
      shared_ratio > unique_ratio * 1.5,
      f"{shared_ratio:.3f} vs {unique_ratio:.3f}（{shared_ratio / unique_ratio:.1f} 倍）")

layouts = compare_layouts()
print(f"ユーザー情報を先頭に置く: 共有できた先頭 {layouts['bad_chars']} 文字")
print(f"ユーザー情報を後ろに回す: 共有できた先頭 {layouts['good_chars']} 文字")
check("可変情報を先頭に置くと何も共有できない", layouts["bad_chars"] == 0,
      "1文字目から違うため")
check("可変情報を後ろに回すとシステムプロンプト分を共有できる",
      layouts["good_chars"] > layouts["bad_chars"]
      and layouts["good_ratio"] > layouts["bad_ratio"],
      "先頭配置 < 末尾配置")

# --- 4. TTL・無効化・観測 ---------------------------------------------------
print("\n=== TTL と無効化 ===")
expiring = ScopedCache(ttl_seconds=0.05)
expiring.put(hq, QUESTION, "月額 12,000 円です。", cost_ms=730.0)
time.sleep(0.1)
check("TTL を過ぎるとミスになる", expiring.get(hq, QUESTION) is None)

cache = ScopedCache(ttl_seconds=300.0)
logi = variants["テナント"]
cache.put(hq, QUESTION, "本社ビルの駐車場は月額 12,000 円です。", cost_ms=730.0)
cache.put(logi, QUESTION, "物流センターの駐車場は無料です。", cost_ms=730.0)
removed = cache.invalidate_tenant("minato-hq")
check("テナント単位で消せる", removed == 1 and cache.get(hq, QUESTION) is None,
      f"{removed} 件削除")
check("他テナントの分は残る",
      cache.get(logi, QUESTION) == "物流センターの駐車場は無料です。")

versioned = ScopedCache(ttl_seconds=300.0)
versioned.put(hq, QUESTION, "旧規程の答え", cost_ms=730.0)
new_version = replace(hq, corpus_version="2026-09-01")
check("資料バージョンが変わると古い答えは使われない",
      versioned.get(new_version, QUESTION) is None,
      "鍵にバージョンが入っているため")
check("古い版は掃除で消える", versioned.invalidate_stale("2026-09-01") == 1,
      "鍵が変わるだけではメモリに残り続ける")

hot = ScopedCache(ttl_seconds=300.0)
hot.put(hq, QUESTION, "本社ビルの駐車場は月額 12,000 円です。", cost_ms=730.0)
hot.get(hq, QUESTION)
hot.get(hq, "打刻を忘れた場合はどう修正しますか。")
hot.get(replace(hq, temperature=0.7), QUESTION)
report = hot.report_markdown()
print(report)
check("観測レポートにヒット率と節約時間が載る",
      "ヒット率" in report and "節約できた推論時間" in report
      and abs(hot.stats.hit_rate - 0.5) < 1e-9,
      f"ヒット率 {hot.stats.hit_rate:.3f}（ヒット1 / ミス1）")
check("温度が0でないリクエストはヒットにもミスにも数えない", hot.skipped == 1,
      f"skipped={hot.skipped}")

# --- 5. セマンティックキャッシュの閾値 --------------------------------------
print("\n=== セマンティックキャッシュの閾値 ===")
rows = {row.threshold: row for row in sweep([0.99, 0.96, 0.95, 0.90, 0.85])}
print(markdown_table(list(rows.values())))
check("閾値 0.99 では何も拾えない",
      rows[0.99].hits == 0 and rows[0.99].false_hits == 0,
      f"取りこぼし {rows[0.99].misses} 件")
check("閾値 0.95 では同義2件だけを拾える",
      rows[0.95].hits == 2 and rows[0.95].false_hits == 0)
check("閾値 0.90 に緩めると誤ヒットが出る", rows[0.90].false_hits == 1,
      "USBメモリの肯定と否定を同じ質問とみなす")
check("緩めるほど誤ヒット率が上がる",
      rows[0.85].false_hit_rate > rows[0.90].false_hit_rate > rows[0.95].false_hit_rate,
      f"{rows[0.95].false_hit_rate:.3f} -> {rows[0.90].false_hit_rate:.3f} "
      f"-> {rows[0.85].false_hit_rate:.3f}")

pair = PAIRS[0]
semantic = SemanticCache(threshold=0.95)
semantic.put(hq, pair.a, "前営業日までに申請してください。")
check("同義の質問は閾値内でヒットする", semantic.get(hq, pair.b) is not None,
      f"類似度 {pair.similarity:.2f} ≧ 閾値 0.95")
check("スコープが違えば意味が近くてもヒットしない",
      semantic.get(logi, pair.b) is None,
      "テナントを跨ぐ比較はしない")

# --- 6. 権限を含むゲートウェイ（推論サーバ不要）------------------------------
print("\n=== 権限を含むゲートウェイ ===")
from fastapi.testclient import TestClient  # noqa: E402

calls: list[str] = []


def stub_generate(prompt: str, max_tokens: int, temperature: float) -> str:
    """上流の推論のスタブ。呼ばれた回数と、呼ばれるたびに違う答えを返す。"""
    calls.append(prompt)
    return f"回答{len(calls)}"


client = TestClient(create_app(generate=stub_generate, cache=ScopedCache(ttl_seconds=60)))
HQ_EMP = {"X-Tenant-Id": "minato-hq"}
HQ_HR = {"X-Tenant-Id": "minato-hq", "X-Roles": "hr"}
LOGI_EMP = {"X-Tenant-Id": "minato-logi"}

no_tenant = client.post("/generate", json={"prompt": QUESTION})
check("テナントIDが無ければ 400 で断る", no_tenant.status_code == 400,
      f"status={no_tenant.status_code}")

first = client.post("/generate", json={"prompt": QUESTION}, headers=HQ_EMP).json()
second = client.post("/generate", json={"prompt": QUESTION}, headers=HQ_EMP).json()
other_tenant = client.post("/generate", json={"prompt": QUESTION}, headers=LOGI_EMP).json()
other_role = client.post("/generate", json={"prompt": QUESTION}, headers=HQ_HR).json()

check("同じ立場の2回目はキャッシュヒット",
      second["cached"] is True and second["text"] == first["text"])
check("別テナントの同じ質問は上流を呼び直す",
      other_tenant["cached"] is False and other_tenant["text"] != first["text"])
check("同じテナントでも可視範囲が違えば呼び直す",
      other_role["cached"] is False and other_role["text"] != first["text"])
check("上流を呼んだのは3回（ヒットした1回は呼ばない）", len(calls) == 3,
      f"{len(calls)} 回")

stats = client.get("/cache/stats").json()
check("ヒット率を観測できる",
      stats["hits"] == 1 and stats["misses"] == 3 and stats["keys"] == 3,
      f"hits={stats['hits']} misses={stats['misses']} keys={stats['keys']}")

purged = client.post("/cache/invalidate", params={"tenant_id": "minato-hq"}).json()
check("テナント単位で消せる（消せる設計にしておく）", purged["removed"] == 2,
      f"{purged['removed']} 件削除（本社の一般社員ぶんと人事ぶん）")
after = client.post("/generate", json={"prompt": QUESTION}, headers=HQ_EMP).json()
check("消したあとは上流を呼び直す", after["cached"] is False and len(calls) == 4)

client.post("/generate", json={"prompt": QUESTION, "temperature": 0.7}, headers=HQ_EMP)
warm = client.post("/generate", json={"prompt": QUESTION, "temperature": 0.7},
                   headers=HQ_EMP).json()
check("温度が0でなければキャッシュしない", warm["cached"] is False,
      "毎回違う答えになるものを配ってはいけない")

# --- 7. 実サーバとゲートウェイ（SKIP_SERVER=1 で飛ばせる）--------------------
if os.environ.get("SKIP_SERVER") == "1":
    print("\nSKIP_SERVER=1 のため推論サーバとゲートウェイを使う検証を飛ばします。")
else:
    import httpx  # noqa: E402

    from infrakit.client import LlamaClient  # noqa: E402

    print("\n=== 実サーバのキャッシュ ===")
    base = os.environ.get("GATEWAY_URL", "http://gateway:8000").rstrip("/")

    def post_generate(prompt: str, max_tokens: int = 16,
                      attempts: int = 6) -> tuple[int, dict, float]:
        """レート制限（セッション5）に当たったら待って再送する。

        戻り値は (ステータス, JSON, 成功した1回だけの所要ミリ秒)。
        """
        for _ in range(attempts):
            started = time.perf_counter()
            res = httpx.post(f"{base}/generate",
                             json={"prompt": prompt, "max_tokens": max_tokens},
                             timeout=180.0)
            elapsed = (time.perf_counter() - started) * 1000
            if res.status_code in (429, 503):
                time.sleep(1.5)
                continue
            return res.status_code, (res.json() if res.status_code == 200 else {}), elapsed
        return res.status_code, {}, 0.0

    # 実行ごとに違うプロンプトにする。既存のキャッシュに当たらないようにするため
    fresh = f"[{time.time():.3f}] " + with_shared_prefix()[0]
    status, miss, miss_ms = post_generate(fresh)
    check("ゲートウェイ経由で生成できる", status == 200, f"status={status}")
    if status == 200:
        check("初回はキャッシュミス", miss.get("cached") is False)
        _, hit, hit_ms = post_generate(fresh)
        check("2回目はキャッシュヒット", hit.get("cached") is True)
        check("ヒットは上流を呼ばないので速い", hit_ms < miss_ms,
              f"{miss_ms:.0f}ms -> {hit_ms:.0f}ms")

    live = LlamaClient()
    check("推論サーバに接続できる", live.health(),
          "つながらない場合は `docker compose up -d llama` を実行してください")
    if live.health():
        prompts = with_shared_prefix()[:3]
        for prompt in prompts:
            live.generate(prompt, max_tokens=8)      # ウォームアップ
        results = [live.generate(prompt, max_tokens=16) for prompt in prompts]
        check("共通接頭辞のリクエストがすべて成功する", all(r.ok for r in results),
              f"エラー {sum(1 for r in results if not r.ok)} 件")
        print("参考 TTFT: " + " / ".join(f"{r.ttft_ms:.0f}ms" for r in results))
        print("※ この規模のプロンプト（数十トークン）ではプリフィルが短く、")
        print("  KVキャッシュ再利用の差は測定ノイズに埋もれます。値は検証しません。")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション6の検証はすべて成功しました。")
