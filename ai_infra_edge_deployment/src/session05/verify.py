#!/usr/bin/env python3
"""セッション5・6の自己検証：ゲートウェイが守れていること。

レート制限・バックプレッシャ・キャッシュを、サーバを呼ばずに検証する
（TokenBucket と ExactCache は単体で試せる）。ゲートウェイ経由の疎通だけ
実サーバを使うので、SKIP_SERVER=1 で飛ばせる。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from infrakit.cache import ExactCache, PrefixCache  # noqa: E402
from tools.prompts import with_shared_prefix, with_unique_prefix  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


# --- レート制限（トークンバケット）------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "gateway"))
from gateway.main import TokenBucket  # noqa: E402

bucket = TokenBucket(rate=2.0, burst=4.0)
allowed = sum(1 for _ in range(10) if bucket.allow())
check("バースト分だけ即座に通る", allowed == 4, f"{allowed} 件（burst=4）")
time.sleep(1.05)
refilled = sum(1 for _ in range(5) if bucket.allow())
check("1秒後に rate 分だけ補充される", refilled == 2, f"{refilled} 件（rate=2/s）")

# --- 完全一致キャッシュ -----------------------------------------------------
cache = ExactCache(ttl_seconds=60)
check("初回はミス", cache.get("こんにちは") is None)
cache.put("こんにちは", "はい", cost_ms=500.0)
check("2回目はヒット", cache.get("こんにちは") == "はい")
check("ヒット率が計算できる", abs(cache.stats.hit_rate - 0.5) < 1e-9,
      f"{cache.stats.hit_rate:.3f}（ヒット1 / ミス1）")
check("短縮時間が積算される", cache.stats.saved_ms == 500.0)

expiring = ExactCache(ttl_seconds=0.05)
expiring.put("q", "a", 1.0)
time.sleep(0.1)
check("TTL を過ぎるとミスになる", expiring.get("q") is None)

# --- キャッシュキーに権限が入っていない（意図的な欠け・S06 の題材）----------
shared = ExactCache(ttl_seconds=60)
shared.put("社員の住所を教えて", "東京都港区1-1-1", 100.0)
# 別のテナント／別の権限のユーザーが同じ質問をすると、同じ答えが返ってしまう
check("【意図的な欠陥】キャッシュがテナントを跨いでしまう",
      shared.get("社員の住所を教えて") == "東京都港区1-1-1",
      "S06 でキャッシュキーに権限を含める設計に直す")

# --- 前方一致（プロンプトキャッシュが効く条件）------------------------------
shared_report = PrefixCache().report(with_shared_prefix())
unique_report = PrefixCache().report(with_unique_prefix())
print(f"\n共通の接頭辞あり: 平均共有率 {shared_report['mean_shared_ratio']:.3f}")
print(f"接頭辞が毎回違う: 平均共有率 {unique_report['mean_shared_ratio']:.3f}")
check("共通の接頭辞があると前方一致率が高い",
      shared_report["mean_shared_ratio"] > unique_report["mean_shared_ratio"] * 1.5,
      f"{shared_report['mean_shared_ratio']:.3f} vs {unique_report['mean_shared_ratio']:.3f}")

# --- ゲートウェイ経由の疎通 -------------------------------------------------
if os.environ.get("SKIP_SERVER") == "1":
    print("\nSKIP_SERVER=1 のためゲートウェイ経由の疎通確認を飛ばします。")
else:
    import httpx

    base = os.environ.get("GATEWAY_URL", "http://gateway:8000")
    try:
        health = httpx.get(f"{base}/healthz", timeout=10.0).json()
        check("ゲートウェイが生きている", health.get("ok") is True, str(health))
        check("上流の推論サーバも生きている", health.get("upstream_healthy") is True, str(health))

        res = httpx.post(f"{base}/generate",
                         json={"prompt": with_shared_prefix()[0], "max_tokens": 16},
                         timeout=120.0)
        check("ゲートウェイ経由で生成できる", res.status_code == 200,
              f"status={res.status_code}")
        if res.status_code == 200:
            body = res.json()
            check("キャッシュミスとして返る", body.get("cached") is False, str(body)[:80])
            again = httpx.post(f"{base}/generate",
                               json={"prompt": with_shared_prefix()[0], "max_tokens": 16},
                               timeout=120.0).json()
            check("2回目はキャッシュヒットになる", again.get("cached") is True, str(again)[:80])

        # レート制限に当たるまで連打する（RATE_LIMIT_RPS=2 / BURST=4 の既定）
        codes = []
        for i in range(8):
            r = httpx.post(f"{base}/generate",
                           json={"prompt": f"[{i}] 短い質問", "max_tokens": 4},
                           timeout=120.0)
            codes.append(r.status_code)
        check("連打すると 429 か 503 が返る",
              any(c in (429, 503) for c in codes), f"status={codes}")
    except httpx.HTTPError as exc:
        check("ゲートウェイに接続できる", False, f"{type(exc).__name__}: {exc}")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション5・6の検証はすべて成功しました。")
