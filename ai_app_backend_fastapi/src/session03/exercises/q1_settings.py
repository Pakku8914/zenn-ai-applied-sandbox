"""問題1の解答：quick 用のタイムアウトを設定に追加する（本文の LLMSettings に1項目足すのと同じ）。"""

from __future__ import annotations

from pydantic import Field

from src.session03.config import LLMSettings


class QuickSettings(LLMSettings):
    # 環境変数 LLM_QUICK_TIMEOUT_SECONDS。0 や負の値は起動時に ValidationError にする
    llm_quick_timeout_seconds: float = Field(default=2.0, gt=0)
