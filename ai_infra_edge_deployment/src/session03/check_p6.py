"""問題6の確認（セッション3）。KVキャッシュ予算 1.5GB で何本持てるか。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from infrakit.kvcache import QWEN_05B, max_concurrent  # noqa: E402

# hidden は KVキャッシュの式に使わないので除いてから渡す
shape = {k: v for k, v in QWEN_05B.items() if k != "hidden"}
budget = int(1.5 * 1024 ** 3)

print(max_concurrent(budget, 4096, **shape))                    # 32
print(max_concurrent(budget, 1024, **shape))                    # 128
print(max_concurrent(budget, 4096, bytes_per_elem=1, **shape))  # 64
