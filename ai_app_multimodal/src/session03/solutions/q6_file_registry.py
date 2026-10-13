"""問題6：同じ画像は一度だけアップロードし、2回目からは file_id で参照する。

    docker compose exec api python -m src.session03.solutions.q6_file_registry

アップロードは関数として外から渡す（mockllm には upload が無いので、ここでは偽のアップローダを使う）。
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable

from anthropic import Anthropic

from kondate.media import media_path
from src.session03.count import count_input_tokens
from src.session03.images import base64_block, file_block, prepare_image
from src.session03.make_variants import make_all

Uploader = Callable[[bytes, str], str]  # (前処理後のバイト列, media_type) -> file_id


class FileRegistry:
    def __init__(self, upload: Uploader) -> None:
        self._upload = upload
        self._ids: dict[tuple[str, str], str] = {}
        self.uploads = 0

    def file_id_for(self, user_id: str, data: bytes, media_type: str) -> str:
        key = (user_id, hashlib.sha256(data).hexdigest())  # 利用者ごとに分ける（消すときに他人の参照を壊さない）
        if key not in self._ids:
            self._ids[key] = self._upload(data, media_type)
            self.uploads += 1
        return self._ids[key]

    def block_for(self, user_id: str, data: bytes, media_type: str) -> dict:
        return file_block(self.file_id_for(user_id, data, media_type))


def fake_uploader(data: bytes, media_type: str) -> str:
    """決定的な偽の file_id を返す（本物は API が採番する）。"""
    return f"file_fake_{hashlib.sha256(data).hexdigest()[:12]}"


def main() -> None:
    fridge = prepare_image(media_path("fridge.jpg").read_bytes())
    portrait = prepare_image(make_all()["portrait"].read_bytes())
    registry = FileRegistry(fake_uploader)
    client = Anthropic()
    try:
        for user_id, label, p in (("u001", "fridge", fridge), ("u001", "fridge", fridge),
                                  ("u002", "fridge", fridge), ("u001", "portrait", portrait)):
            block = registry.block_for(user_id, p.data, p.media_type)
            tokens = count_input_tokens(client, [block])
            print(f"{user_id} {label:<8} → {block['source']['file_id'][:10]}… input_tokens={tokens} アップロード累計={registry.uploads}")
    finally:
        client.close()
    b64_chars = len(base64_block(fridge.data, fridge.media_type)["source"]["data"])
    file_id = registry.file_id_for("u001", fridge.data, fridge.media_type)  # 登録済みなのでアップロードしない
    print(f"base64 で送ると data だけで {b64_chars} 文字／file_id は {len(file_id)} 文字")


if __name__ == "__main__":
    main()
