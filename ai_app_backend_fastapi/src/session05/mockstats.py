"""mockllm の統計を見る・消す。api コンテナの中で実行する：

    docker compose exec api python -m src.session05.mockstats          # 直近の呼び出しを表示
    docker compose exec api python -m src.session05.mockstats --reset  # 統計を消す
"""

from __future__ import annotations

import sys

import httpx2

from kondate.settings import get_settings

URL = get_settings().mockllm_url

if "--reset" in sys.argv:
    httpx2.post(f"{URL}/_mock/reset", timeout=5).raise_for_status()
    print("mockllm の統計を消しました")
else:
    stats = httpx2.get(f"{URL}/_mock/stats", timeout=5).json()
    print(f"呼び出し回数 total={stats['total']}")
    for r in stats["requests"][-5:]:
        print(f"  seq={r['seq']} path={r['path']} stream={r['stream']} status={r['status']} "
              f"output_tokens={r.get('output_tokens')}")
