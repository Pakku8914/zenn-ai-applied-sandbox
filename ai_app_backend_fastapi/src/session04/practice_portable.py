"""練習問題6の解答：ChatRequest を OpenAI 互換へ持ち出したときに失われる・失敗する指定を点検する。"""

from __future__ import annotations

from .providers import ChatRequest

SENDABLE = {"text", "tool_use", "tool_result"}  # to_openai_messages が変換できるブロック


def check_portable(req: ChatRequest) -> list[str]:
    """見つかった順に「場所: 種類」を返す。種類は cache_control / is_error / unsupported:<型> / model。"""
    found: list[str] = []
    for i, m in enumerate(req.messages):
        content = m.get("content")
        if isinstance(content, str):
            continue
        for j, block in enumerate(content):
            where = f"messages[{i}].content[{j}]"
            if block.get("type") not in SENDABLE:
                found.append(f"{where}: unsupported:{block.get('type')}")  # 送る前に ProviderError になる
            if "cache_control" in block:
                found.append(f"{where}: cache_control")  # 黙って捨てられる（キャッシュ料金の前提が崩れる）
            if block.get("type") == "tool_result" and block.get("is_error"):
                found.append(f"{where}: is_error")  # role: tool には失敗の印が無い
    for k, tool in enumerate(req.tools):
        if "cache_control" in tool:
            found.append(f"tools[{k}]: cache_control")
    if req.model is not None:
        found.append("model")  # モデル ID はプロバイダ固有。差し替え先で通じない
    return found
