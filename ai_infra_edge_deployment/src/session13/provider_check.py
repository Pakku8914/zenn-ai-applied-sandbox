#!/usr/bin/env python3
"""実行プロバイダ（EP）の一覧と、安全な選び方（セッション13）。

  python src/session13/provider_check.py

実行プロバイダは「この計算を誰にやらせるか」の指定である。CPU・GPU・NPU などが
候補になるが、**使えるかどうかはインストールしたビルドと端末で決まる**。
コードに名前を書いたから使えるようになる、ということは絶対にない。

このスクリプトは3つを見せる。

  ① このビルドで実際に使える EP の一覧（環境で変わる）
  ② 要求した EP のうち、実在するものだけを残す選び方（フォールバック）
  ③ 実在しない名前をそのまま渡すとどうなるか
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime_knobs import (  # noqa: E402
    Knobs, available_providers, build_session, fixed_input, model_pair,
    run_once, select_providers,
)

# 端末で名前が挙がりやすい EP。**本書は実測しない**（一次情報の確認先だけ示す）
KNOWN = [
    ("CPUExecutionProvider", "CPU。どのビルドにも必ず入っている最後の砦"),
    ("CoreMLExecutionProvider", "Apple 系の端末（別ビルドが必要）"),
    ("NnapiExecutionProvider", "Android（別ビルドが必要）"),
    ("QNNExecutionProvider", "Qualcomm 系 NPU（別ビルド・ドライバが必要）"),
    ("CUDAExecutionProvider", "NVIDIA GPU（CUDA 版のビルドが必要）"),
]


def main() -> None:
    import onnxruntime as ort

    have = available_providers()
    print(f"onnxruntime : {ort.__version__}")
    print(f"使える EP   : {have}")
    print("（この一覧はインストールしたホイールと端末で変わります。"
          "本書のサンドボックスは CPU 版です）")

    print("\n=== 名前を知っていても、使えるとは限らない ===")
    print("| EP の名前 | このビルドで使えるか | 説明 |")
    print("| :--- | :--- | :--- |")
    for name, note in KNOWN:
        print(f"| `{name}` | {'使える' if name in have else '使えない'} | {note} |")

    print("\n=== 要求と実際（フォールバック）===")
    wanted = ["QNNExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"]
    picked = select_providers(wanted)
    print(f"要求（優先順）: {wanted}")
    print(f"実在するものだけ残す: {picked}")

    _fp32, int8 = model_pair()
    session = build_session(int8, Knobs(intra=1, providers=tuple(wanted)))
    print(f"セッションが実際に使った EP: {session.get_providers()}")
    probs = run_once(session, fixed_input())
    print(f"出力の形: {tuple(probs.shape)} / 確率の合計: {float(probs.sum()):.6f}")

    print("\n=== 実在しない名前をそのまま渡すと ===")
    try:
        ort.InferenceSession(str(int8), providers=["NoSuchExecutionProvider"])
        print("例外は出ませんでした（この環境ではその名前が実在します）")
    except Exception as exc:  # noqa: BLE001  何が起きるかを見せるのが目的
        print(f"例外: {type(exc).__name__}")
        print("-> 例外メッセージは版で変わります。見るべきは"
              "「実在しない名前は事前に落とす」という設計のほうです。")

    print("\n覚えておくこと")
    print("・EP は**優先順のリスト**。前から順に、その EP が扱えるノードを引き取る")
    print("・扱えないノードは後ろの EP（最終的に CPU）に落ちる。"
          "つまり「指定したから全部そこで動く」ではない")
    print("・グラフが細かく分割されると、EP をまたぐデータの受け渡しが増えて"
          "**遅くなることもある**。だから必ず測る")
    print("・一次情報: ONNX Runtime 公式ドキュメント Execution Providers "
          "https://onnxruntime.ai/docs/execution-providers/ （最終閲覧 2026-08-15）")


if __name__ == "__main__":
    main()
