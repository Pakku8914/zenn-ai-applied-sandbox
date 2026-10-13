"""問題3：7通りのログの書き方が、MaskFilter を通るとどう出るかを確かめる（ハッシュの値は「…」と表示する）。

    docker compose exec api python -m src.session13.solutions.q3_mask_cases
"""

from __future__ import annotations

import logging
import re

from src.session13.logmask import masked_handler
from src.session13.testkit import TEXT, Collect


def run() -> list[str]:
    collect = Collect()
    log = logging.getLogger("q3")
    log.handlers[:] = [masked_handler(collect)]
    log.setLevel(logging.INFO)
    log.propagate = False

    log.info("transcript", extra={"fields": {"user_id": "u001", "transcript": TEXT}})          # 1
    log.info("認識結果 %s", TEXT)                                                              # 2
    log.info("upload_saved", extra={"fields": {"upload_id": "up_test", "filename": "山田家の冷蔵庫.jpg",
                                               "bytes": 89080}})                                # 3
    log.info("voice_saved", extra={"fields": {"voice_id": "vc_test", "pcm": bytes(640)}})       # 4
    log.info("odd", extra={"fields": {"bytes": b"abc"}})                                        # 5 許可したキーでも中身が bytes
    log.info("receipt_read", extra={"fields": {"receipt": {"store": "こんだてマート"}}})          # 6 辞書
    try:                                                                                        # 7 例外の文
        raise ValueError(f"形式が正しくありません：{TEXT}")
    except ValueError:
        log.exception("turn_failed", extra={"fields": {"request_id": "req_test"}})
    return [re.sub(r"sha=[0-9a-f]{12}", "sha=…", line) for line in collect.lines]


if __name__ == "__main__":
    print("\n".join(run()))
