"""問題5：利用者のファイル名をパスに使うと何が起きるかを確かめ、採番で保存する。

    docker compose exec api python -m src.session02.solutions.p5_paths
"""

from __future__ import annotations

import ntpath
from pathlib import Path

from ulid import ULID

BASE = Path("out/uploads")
NAMES = ["receipt.png", "../../kondate/main.py", "/etc/passwd", "..\\..\\kondate\\main.py"]


def naive_path(name: str) -> Path:
    """Bad：利用者のファイル名をそのままつなぐ。"""
    return BASE / name


def escapes(path: Path) -> bool:
    """解決したパスが BASE の外を指すか。"""
    return not path.resolve().is_relative_to(BASE.resolve())


def new_upload_name(ext: str) -> str:
    """Good：名前はサーバーが採番し、拡張子は判定した形式から付ける。"""
    return f"up_{ULID()}.{ext}"


def yes_no(flag: bool) -> str:
    return "はい" if flag else "いいえ"


def run() -> list[str]:
    lines = [f"{n} → {naive_path(n)}（外に出る：{yes_no(escapes(naive_path(n)))}）" for n in NAMES]

    win = ntpath.normpath(ntpath.join("out\\uploads", NAMES[3]))  # Windows のサーバーでは \ も区切り文字
    win_escapes = not win.startswith("out\\uploads\\")
    lines.append(f"Windows のサーバーでは {NAMES[3]} → {win}（外に出る：{yes_no(win_escapes)}）")

    # u001 と u002 が、たまたま同じ名前（スマホの連番）のファイルを送る
    same = naive_path("IMG_0001.jpg") == naive_path("IMG_0001.jpg")
    lines.append(f"u001 と u002 が同じ IMG_0001.jpg を送る → 同じパス：{yes_no(same)}（後から来た方が上書きする）")

    names = [new_upload_name("png") for _ in range(1000)]
    lines.append(f"採番した名前 1000 件 → すべて異なる：{yes_no(len(set(names)) == 1000)}・{len(names[0])} 文字（up_＋ULID 26文字＋.png）")
    return lines


if __name__ == "__main__":
    print("\n".join(run()))
