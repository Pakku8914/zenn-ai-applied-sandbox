"""LLM 呼び出しを差し替え可能にする薄い層。

評価ハーネスがモデル呼び出しに直結していると、テストの実行にお金と時間、
そして「毎回違う結果」が付いてくる。ここではアプリ側から見た呼び出し口を
1 つの Protocol に固定し、実装だけを差し替えられるようにしている。

- StubClient      : 決定的な固定応答を返す（ロジックの単体テスト用）
- RecordedClient  : 記録済みレスポンス（カセット）を再生する（回帰テスト用）
- AnthropicClient : 実際の Claude API を呼ぶ（APIキーがあるときだけ使う）
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

# 1M トークンあたりの単価（USD）。2026-08 時点の Claude API 標準料金。
# 単価は改定されるため、コスト計算に使う前に公式の料金ページで確認すること。
PRICING_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    # モデルID: (入力単価, 出力単価)
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "stub": (0.0, 0.0),
}


@dataclass(frozen=True)
class LLMResponse:
    """1 回の LLM 呼び出しの結果。評価と会計に必要な情報だけを持つ。"""

    text: str
    model: str = "stub"
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    stop_reason: str = "end_turn"
    latency_ms: float = 0.0
    replayed: bool = False

    def cost_usd(self) -> float:
        """このレスポンスの概算コスト（USD）を返す。"""
        price_in, price_out = PRICING_USD_PER_MTOK.get(self.model, (0.0, 0.0))
        # キャッシュ読み出し分は入力単価の約 1/10 で課金される
        billable_in = self.input_tokens + self.cache_read_input_tokens * 0.1
        return (billable_in * price_in + self.output_tokens * price_out) / 1_000_000


@runtime_checkable
class LLMClient(Protocol):
    """評価ハーネスが依存する唯一の呼び出し口。"""

    def complete(self, prompt: str, *, system: str | None = None) -> LLMResponse:
        """プロンプトを渡して 1 回応答を得る。"""
        ...


def make_key(prompt: str, system: str | None = None) -> str:
    """プロンプトから記録の検索キーを作る。

    プロンプトが 1 文字でも変われば別のキーになる。これは意図した挙動で、
    「プロンプトを変えたのに古い記録で緑になる」事故を防ぐための設計。
    """
    payload = json.dumps({"system": system, "prompt": prompt}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class RecordingMissingError(KeyError):
    """記録済みレスポンスが見つからないときに投げる。"""


@dataclass
class StubClient:
    """キーワードに対して固定文字列を返す決定的なクライアント。

    ルールベース検査や集計ロジックのテストは、モデルの気分に左右されては
    いけない。そういうテストではこれを使う。
    """

    rules: dict[str, str] = field(default_factory=dict)
    default: str = "（スタブ応答）該当する回答が用意されていません。"
    model: str = "stub"
    calls: list[str] = field(default_factory=list)

    def complete(self, prompt: str, *, system: str | None = None) -> LLMResponse:
        self.calls.append(prompt)
        text = self.default
        for keyword, answer in self.rules.items():
            if keyword in prompt:
                text = answer
                break
        return LLMResponse(
            text=text,
            model=self.model,
            input_tokens=len(prompt),
            output_tokens=len(text),
        )


@dataclass
class RecordedClient:
    """記録済みレスポンス（カセット）を再生するクライアント。

    APIキーが無くても回帰テストを回せるようにする仕組み。実 API を叩いた
    結果を JSON に保存しておき、テスト時はそれを読み出すだけにする。
    """

    path: Path
    strict: bool = True
    _cassette: dict[str, dict] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        if self.path.exists():
            self._cassette = json.loads(self.path.read_text(encoding="utf-8"))

    def complete(self, prompt: str, *, system: str | None = None) -> LLMResponse:
        key = make_key(prompt, system)
        entry = self._cassette.get(key)
        if entry is None:
            if self.strict:
                raise RecordingMissingError(
                    f"記録が見つかりません: key={key}\n"
                    f"  プロンプト先頭: {prompt[:60]!r}\n"
                    f"  `python record.py` で記録を更新してください（要 APIキー）。"
                )
            return LLMResponse(text="", model="missing", stop_reason="missing_recording")
        return LLMResponse(
            text=entry["text"],
            model=entry.get("model", "unknown"),
            input_tokens=entry.get("input_tokens", 0),
            output_tokens=entry.get("output_tokens", 0),
            cache_read_input_tokens=entry.get("cache_read_input_tokens", 0),
            stop_reason=entry.get("stop_reason", "end_turn"),
            replayed=True,
        )

    def save(self, key: str, response: LLMResponse) -> None:
        """1 件の応答を記録に追加してファイルへ書き出す。"""
        self._cassette[key] = {
            "text": response.text,
            "model": response.model,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "cache_read_input_tokens": response.cache_read_input_tokens,
            "stop_reason": response.stop_reason,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._cassette, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


@dataclass
class AnthropicClient:
    """実際の Claude API を呼ぶクライアント（APIキーが必要）。

    APIキーが無い環境でも import だけは通るように、SDK の読み込みは
    メソッド内で遅延させている。
    """

    model: str = "claude-opus-5"
    max_tokens: int = 1024
    _client: object | None = field(default=None, init=False, repr=False)

    def complete(self, prompt: str, *, system: str | None = None) -> LLMResponse:
        import time

        import anthropic

        if self._client is None:
            # APIキーはコードに書かず、環境変数から読む
            self._client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

        kwargs: dict = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system is not None:
            kwargs["system"] = system

        started = time.perf_counter()
        message = self._client.messages.create(**kwargs)  # type: ignore[attr-defined]
        latency_ms = (time.perf_counter() - started) * 1000

        # 拒否や打ち切りは content を読む前に stop_reason で判定する
        text = "".join(block.text for block in message.content if block.type == "text")
        return LLMResponse(
            text=text,
            model=message.model,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            cache_read_input_tokens=getattr(message.usage, "cache_read_input_tokens", 0) or 0,
            stop_reason=message.stop_reason or "end_turn",
            latency_ms=latency_ms,
        )
