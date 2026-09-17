"""evalkit — LLM アプリの評価・回帰テスト用の最小ハーネス。

APIキーが無くても演習が成立するよう、LLM 呼び出しは差し替え可能な
クライアント（スタブ／記録再生／実API）に抽象化してある。
"""

from evalkit.checks import CheckResult, run_rule_checks
from evalkit.client import (
    AnthropicClient,
    LLMClient,
    LLMResponse,
    RecordedClient,
    RecordingMissingError,
    StubClient,
    make_key,
)
from evalkit.dataset import EvalCase, load_dataset
from evalkit.judge import JudgeVerdict, judge_pointwise
from evalkit.report import CaseResult, Summary, render_markdown, summarize

__all__ = [
    "AnthropicClient",
    "CaseResult",
    "CheckResult",
    "EvalCase",
    "JudgeVerdict",
    "LLMClient",
    "LLMResponse",
    "RecordedClient",
    "RecordingMissingError",
    "StubClient",
    "Summary",
    "judge_pointwise",
    "load_dataset",
    "make_key",
    "render_markdown",
    "run_rule_checks",
    "summarize",
]
