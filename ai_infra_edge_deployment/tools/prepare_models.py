#!/usr/bin/env python3
"""推論サーバで使うモデルを準備する（初回のみ）。

  1. HuggingFace からモデルを取得する（models/hf/qwen05b）
  2. GGUF に変換する（f16）  … llama.cpp のコンテナで行う
  3. 量子化する（Q8_0 / Q4_K_M）… 同上

このスクリプトは 1 だけを行う。2・3 は llama.cpp のコンテナ側で実行するため、
次のコマンドを使う（README とセッション1の本文に手順を書く）。

  docker compose --profile prepare run --rm llamacpp \
      -c --outtype f16 /work/models/hf/qwen05b
  docker compose --profile prepare run --rm llamacpp \
      -q /work/models/hf/qwen05b/Qwen2.5-0.5B-Instruct-F16.gguf \
         /work/models/gguf/qwen05b-q4_k_m.gguf Q4_K_M
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SANDBOX = Path(__file__).resolve().parent.parent
HF_DIR = SANDBOX / "models" / "hf"
GGUF_DIR = SANDBOX / "models" / "gguf"

MODEL_ID = "Qwen/Qwen2.5-0.5B-Instruct"
MODEL_REVISION = "main"


def dir_size_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1024 / 1024


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-id", default=MODEL_ID)
    ap.add_argument("--name", default="qwen05b")
    args = ap.parse_args()

    from huggingface_hub import snapshot_download

    target = HF_DIR / args.name
    target.mkdir(parents=True, exist_ok=True)
    print(f"取得中: {args.model_id} -> {target.relative_to(SANDBOX)}")
    snapshot_download(
        repo_id=args.model_id, revision=MODEL_REVISION, local_dir=str(target),
        # GGUF 変換に必要なファイルだけを取る（無駄なダウンロードを避ける）
        allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model"],
    )
    print(f"取得完了: {dir_size_mb(target):.1f} MB")

    GGUF_DIR.mkdir(parents=True, exist_ok=True)
    print("\n次に GGUF へ変換します（ホスト側で実行してください）:")
    print("  docker compose --profile prepare run --rm llamacpp \\")
    print(f"      -c --outtype f16 /work/models/hf/{args.name}")
    print("\n変換後、量子化します:")
    for quant in ("Q8_0", "Q4_K_M"):
        print(f"  docker compose --profile prepare run --rm llamacpp \\")
        print(f"      -q /work/models/hf/{args.name}/*F16.gguf \\")
        print(f"         /work/models/gguf/{args.name}-{quant.lower()}.gguf {quant}")

    existing = sorted(GGUF_DIR.glob("*.gguf"))
    if existing:
        print("\n=== 既にある GGUF ===")
        for path in existing:
            print(f"{path.name:<32}{path.stat().st_size / 1024 / 1024:>9.1f} MB")
    else:
        print("\n（GGUF はまだありません）")
        sys.exit(0)


if __name__ == "__main__":
    main()
