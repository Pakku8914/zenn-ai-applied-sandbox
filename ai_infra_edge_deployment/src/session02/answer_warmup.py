#!/usr/bin/env python3
"""セッション2 問題5の解答：ウォームアップ0回と2回で数字がどれだけ動くかを測る。

    docker compose restart llama                                   # 冷えた状態を作る
    docker compose exec app python src/session02/answer_warmup.py

SKIP_SERVER=1 を付けると何もせず終了する。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from infrakit.client import LlamaClient  # noqa: E402
from infrakit.load import run_load  # noqa: E402
from metrics import spread  # noqa: E402
from tools.prompts import with_shared_prefix  # noqa: E402

MAX_TOKENS = 24
N = 8

if os.environ.get("SKIP_SERVER") == "1":
    print("SKIP_SERVER=1 のため推論サーバを使う計測を飛ばします。")
    sys.exit(0)

client = LlamaClient()
if not client.health():
    print("推論サーバに接続できません。`docker compose up -d llama` を実行してください。")
    sys.exit(1)

props = client.props()
model_path = props.get("model_path") or props.get(
    "default_generation_settings", {}).get("model", "")
n_ctx = props.get("default_generation_settings", {}).get("n_ctx") or props.get("n_ctx")
conditions = {"model": Path(str(model_path)).name, "n_ctx": n_ctx,
              "slots": len(client.slots())}
print(f"条件: {conditions} max_tokens={MAX_TOKENS} 件数={N}")

prompts = with_shared_prefix()[:N]

# 冷えている側を先に測る。順番を逆にすると warmup=0 を測る意味がなくなる
cold = run_load(client, prompts, concurrency=1, max_tokens=MAX_TOKENS, warmup=0,
                label="warmup_off", conditions=conditions)
warm = run_load(client, prompts, concurrency=1, max_tokens=MAX_TOKENS, warmup=2,
                label="warmup_on", conditions=conditions)

print()
print(cold.summary())
print(warm.summary())
print()
for name, report in (("ウォームアップ0回", cold), ("ウォームアップ2回", warm)):
    print(f"{name}: TTFT p50={report.ttft['p50']:.0f}ms max={report.ttft['max']:.0f}ms "
          f"ばらつき(p95/p50)={spread(report.ttft):.2f}")
print(f"TTFT max の差: {cold.ttft['max'] - warm.ttft['max']:+.0f}ms")
print(f"-> {cold.to_json()}  -> {warm.to_json()}")

if cold.errors or warm.errors:
    print(f"エラーが出ています（0回={cold.errors} / 2回={warm.errors}）。"
          "`docker compose logs llama` を確認してください。")
    sys.exit(1)
print("計測できました。差の向きと大きさは直前の状態で変わるので、条件を添えて記録してください。")
