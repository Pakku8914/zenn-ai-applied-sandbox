#!/usr/bin/env python3
"""ゲートウェイの完全一致キャッシュを2回叩いて確かめる（セッション6）。

セッション5で作ったゲートウェイ（`gateway/main.py`）には `ExactCache` が
入っている。同じプロンプトの2回目が `cached: true` で返り、推論サーバが
呼ばれないことを確認する。

    docker compose exec app python src/session06/exact_cache_demo.py
"""

from __future__ import annotations

import os
import time

import httpx

BASE = os.environ.get("GATEWAY_URL", "http://gateway:8000").rstrip("/")

# 実行するたびに新しい質問にする（前回の実行が残したキャッシュに当たらないように）。
# 本章の作法どおり、可変情報はプロンプトの末尾に置く
PROMPT = ("みなと商事の社内ヘルプデスクです。会議室は連続で何時間まで使えますか。\n"
          f"（照会番号: {int(time.time())}）")


def ask() -> dict:
    """レート制限（セッション5）に当たったら待って再送する。"""
    for _ in range(6):
        res = httpx.post(f"{BASE}/generate",
                         json={"prompt": PROMPT, "max_tokens": 16}, timeout=180.0)
        if res.status_code in (429, 503):
            time.sleep(1.5)
            continue
        res.raise_for_status()
        return res.json()
    raise RuntimeError("ゲートウェイが受け付けませんでした。`docker compose up -d` を確認してください。")


def main() -> None:
    for i in (1, 2):
        body = ask()
        print(f"{i} 回目: cached={body['cached']}")


if __name__ == "__main__":
    main()
