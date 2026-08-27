#!/usr/bin/env python3
"""1台の端末に通しで適用してみる（セッション15）。

    python src/session15/update_sim.py

門は5つ（署名・互換性・書き込み・チェックサム・起動確認）あるので、落ち方も
5通りある。**そのどれで落ちても、動いている版は変わらない**ことを目で見る。

ネットワークは使わない。配布物は決定的なダミーのバイト列で、誰の環境でも
同じ結果になる。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fleet import INT8_MB  # noqa: E402
from ota import (Device, DeviceSpec, Release, SignedRelease, install, rollback,
                 sha256_bytes, sign, signed, sweep_partials)  # noqa: E402

SIM_ROOT = Path(tempfile.gettempdir()) / "session15"
KEY = b"session15-demo-key"   # 教材用の固定鍵（実機では端末に埋め込んだ鍵で検証する）
SPEC = DeviceSpec(app_version="2.1.0", input_dim=384, n_classes=10,
                  free_bytes=104_857_600)


def blob(version: str, size: int = 4096) -> bytes:
    """決定的なダミーの重み。誰の環境でも同じバイト列になる。"""
    unit = f"model {version} ".encode("ascii")
    return (unit * (size // len(unit) + 1))[:size]


def release(version: str, data: bytes, *, min_app: str = "2.0.0") -> Release:
    return Release(model_id="helpdesk-intent", version=version,
                   sha256=sha256_bytes(data), size_bytes=len(data),
                   min_app=min_app, max_app=None, input_dim=384, n_classes=10)


def _line(result, device: Device, *, note: str = "") -> None:
    print(f"    結果: {'成功' if result.ok else '失敗'} / 段階: {result.stage} / "
          f"動いている版: {device.active_version}{note}")


def main() -> int:
    root = SIM_ROOT / "dev-0001"
    if root.exists():
        shutil.rmtree(root)
    device = Device(root=root, spec=SPEC)
    data12, data13 = blob("1.2.0"), blob("1.3.0")
    rel12, rel13 = release("1.2.0", data12), release("1.3.0", data13)

    print("=== 1台の端末に通しで適用する ===")
    print(f"端末      : {root}")
    print(f"端末の前提: アプリ版 {SPEC.app_version} / 入力 {SPEC.input_dim} / "
          f"クラス {SPEC.n_classes} / 空き {SPEC.free_bytes:,} バイト（③前提値）")
    print(f"配布物    : {len(data12):,} バイトのダミー（実機の {INT8_MB} MB でも手順は同じ）")

    print("\n[1] 初回導入（1.2.0）")
    result = install(device, signed(rel12, KEY), data12, KEY, probe=lambda _: True)
    _line(result, device, note=f"（面 {device.state()['slot']}）")

    print("\n[2] 署名が合わない（第三者がサイズを書き換えた）")
    tampered = SignedRelease(release=replace(rel13, size_bytes=len(data13) + 1),
                             signature=sign(rel13, KEY))
    result = install(device, tampered, data13, KEY, probe=lambda _: True)
    _line(result, device, note="（変わらない）")

    print("\n[3] 互換性が合わない（アプリ版 3.0.0 以上が必要）")
    result = install(device, signed(release("1.3.0", data13, min_app="3.0.0"), KEY),
                     data13, KEY, probe=lambda _: True)
    _line(result, device, note="（変わらない）")

    print("\n[4] 書き込み中に電源が切れる（1,000 バイト書いた時点）")
    result = install(device, signed(rel13, KEY), data13, KEY,
                     probe=lambda _: True, cut_at=1000)
    _line(result, device, note="（変わらない）")
    print(f"    残った .part を起動時の掃除で {len(sweep_partials(root))} 個削除")

    print("\n[5] 中身が壊れて届く（サイズは同じでチェックサムだけ違う）")
    result = install(device, signed(rel13, KEY), data13[:-1] + b"X", KEY,
                     probe=lambda _: True)
    _line(result, device, note="（変わらない）")

    print("\n[6] 起動確認に失敗する（載ったが動かない）")
    result = install(device, signed(rel13, KEY), data13, KEY, probe=lambda _: False)
    print(f"    結果: {'成功' if result.ok else '失敗'} / 段階: {result.stage} / "
          f"戻した: {'はい' if result.rolled_back else 'いいえ'} / "
          f"動いている版: {device.active_version}（面 {device.state()['slot']}）")

    print("\n[7] 正しい 1.3.0")
    result = install(device, signed(rel13, KEY), data13, KEY, probe=lambda _: True)
    _line(result, device, note=f"（面 {device.state()['slot']}）")

    print("\n[8] 明示的なロールバック")
    did = rollback(device)
    print(f"    結果: {'戻した' if did else '戻せない'} / "
          f"動いている版: {device.active_version}（面 {device.state()['slot']}）")

    print("\n5通りの失敗すべてで、動いている版は一度も壊れませんでした。")

    # デモが崩れていたら気づけるように、最後だけ機械的に確かめる
    if device.active_version != "1.2.0" or device.active_bytes() != data12:
        print("NG デモの前提が崩れています（src/session15/verify.py を実行してください）")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
