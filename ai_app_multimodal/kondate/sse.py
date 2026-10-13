"""自前の SSE（①バックエンド編 API契約③ と同じ形）。event: 名と JSON の data:（ensure_ascii=False）。

start {message_id} → delta {text}… → usage {input_tokens, output_tokens} → done {stop_reason}。失敗は error {type, message, request_id} で終える。
③では音声の進行を通知する名前を足す（requirements.md の API契約③）。
"""

from __future__ import annotations

import json

from fastapi.sse import ServerSentEvent


def event(name: str, payload: dict) -> ServerSentEvent:
    # data= に dict を渡すと json.dumps の既定（ensure_ascii=True）で日本語が \uXXXX になるため、自分で直列化する
    return ServerSentEvent(event=name, raw_data=json.dumps(payload, ensure_ascii=False))
