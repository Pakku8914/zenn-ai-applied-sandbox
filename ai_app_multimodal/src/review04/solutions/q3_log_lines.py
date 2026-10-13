"""問題3：受付（S2）・レシート（S7）・音声認識（S8）・利用量（S14）のログ行を、ログのマスク（S13）に通す。

    docker compose exec api python -m src.review04.solutions.q3_log_lines

SHA256 の先頭12桁は実行環境によらず同じ値になるが、紙面では「…」と表示する。
"""

from __future__ import annotations

import logging
import re

from src.review04.kit import masked_handler

UP = "up_01M4RX5Q8J3T9W2B7KDN6CFGHA"
RCP = "rcp_01M4RX5Q8J3T9W2B7KDN6CFGHB"
REQ = "req_01M4RX5Q8J3T9W2B7KDN6CFGHC"
FILENAME = "山田家の冷蔵庫.jpg"
STORE = "こんだてマート"
TRANSCRIPT = "鶏むね肉とキャベツで20分で作れる料理は？"
CONTENTS = ("山田家の冷蔵庫", "こんだてマート", "鶏むね肉")   # ログに出てはいけない中身


class Collect(logging.Handler):
    """書式を通した1行を、画面ではなくリストに集める。"""

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


def write_logs() -> list[str]:
    collect = Collect()
    app = logging.getLogger("app")
    app.handlers[:] = [masked_handler(collect)]   # 子のロガー（app.uploads など）の記録もここで畳む
    app.setLevel(logging.INFO)
    app.propagate = False
    uploads, receipts, voice, usage = (logging.getLogger(f"app.{n}") for n in ("uploads", "receipts", "voice", "usage"))

    uploads.info("upload_saved", extra={"fields": {"user_id": "u001", "upload_id": UP, "kind": "image",
                                                   "bytes": 89080, "sha12": "9f2c4e1a7b30"}})          # 1 S2
    receipts.info("receipt_imported", extra={"fields": {"user_id": "u001", "receipt_id": RCP, "store": STORE,
                                                        "total": 1072, "needs_review": False, "issues": []}})  # 2 S7
    receipts.warning("receipt: 検証に失敗しました（%d回目）: %s", 1, ["items.0.price: int_parsing"])      # 3 S7
    voice.info("transcribed", extra={"fields": {"user_id": "u001", "audio_seconds": 3.81, "text": TRANSCRIPT}})  # 4 S8
    uploads.info("upload_saved", extra={"fields": {"user_id": "u001", "kind": FILENAME}})                 # 5
    try:                                                                                                  # 6 S8
        raise ValueError(f"WAV ではありません：{FILENAME}")
    except ValueError:
        voice.exception("transcribe_failed", extra={"fields": {"user_id": "u001", "request_id": REQ}})
    usage.info("usage_recorded", extra={"fields": {"user_id": "u001", "kind": "llm", "input_tokens": 1668,
                                                   "output_tokens": 194, "x_cache": "miss"}})          # 7 S14
    return [re.sub(r"sha=[0-9a-f]{12}", "sha=…", line) for line in collect.lines]


def run() -> list[str]:
    out = []
    for i, line in enumerate(write_logs(), 1):
        leaks = [w for w in CONTENTS if w in line]
        out.append(f"{i}. {line} → {'漏れあり（' + '・'.join(leaks) + '）' if leaks else '漏れなし'}")
    return out


def main() -> None:
    print("\n".join(run()))


if __name__ == "__main__":
    main()
