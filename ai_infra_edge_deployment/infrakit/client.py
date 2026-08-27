"""推論サーバのクライアント（セッション2の参照実装）。

TTFT（最初のトークンが返るまで）と TPOT（1トークンあたりの生成時間）を分けて測る。
ストリーミングで受けないと TTFT は測れない。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class GenResult:
    text: str
    ttft_ms: float
    total_ms: float
    tokens_out: int
    tpot_ms: float
    slot_id: int | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class LlamaClient:
    """llama.cpp サーバの `/completion` を叩く最小のクライアント。

    **再試行しない**（意図的な欠け）。サーバが飽和して待たされる状況に
    読者がぶつかることが狙い。再試行はセッション5でゲートウェイ側に実装する。
    """

    def __init__(self, base_url: str | None = None, timeout: float = 120.0) -> None:
        self.base_url = (base_url or os.environ.get("LLAMA_URL", "http://llama:8080")).rstrip("/")
        self.timeout = timeout

    def health(self) -> bool:
        try:
            res = httpx.get(f"{self.base_url}/health", timeout=5.0)
            return res.status_code == 200
        except httpx.HTTPError:
            return False

    def props(self) -> dict:
        """モデル名・コンテキスト長・スロット数などのサーバ設定を返す。"""
        res = httpx.get(f"{self.base_url}/props", timeout=10.0)
        res.raise_for_status()
        return res.json()

    def slots(self) -> list[dict]:
        """スロットの状態。飽和しているかを見るのに使う。"""
        res = httpx.get(f"{self.base_url}/slots", timeout=10.0)
        if res.status_code != 200:
            return []
        return res.json()

    def generate(self, prompt: str, max_tokens: int = 64, temperature: float = 0.0,
                 stream: bool = True) -> GenResult:
        payload = {"prompt": prompt, "n_predict": max_tokens, "temperature": temperature,
                   "cache_prompt": True, "stream": stream}
        started = time.perf_counter()
        ttft: float | None = None
        chunks: list[str] = []
        slot_id: int | None = None
        try:
            if not stream:
                res = httpx.post(f"{self.base_url}/completion", json=payload, timeout=self.timeout)
                res.raise_for_status()
                data = res.json()
                total = (time.perf_counter() - started) * 1000
                text = data.get("content", "")
                n_out = int(data.get("tokens_predicted", 0)) or max(len(text) // 3, 1)
                return GenResult(text, total, total, n_out, total / max(n_out, 1),
                                 data.get("id_slot"))

            with httpx.stream("POST", f"{self.base_url}/completion", json=payload,
                              timeout=self.timeout) as res:
                res.raise_for_status()
                for line in res.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = json.loads(line[6:])
                    if data.get("content"):
                        if ttft is None:
                            ttft = (time.perf_counter() - started) * 1000
                        chunks.append(data["content"])
                    if data.get("id_slot") is not None:
                        slot_id = data["id_slot"]
        except httpx.HTTPError as exc:
            total = (time.perf_counter() - started) * 1000
            return GenResult("", ttft or total, total, 0, 0.0, slot_id,
                             f"{type(exc).__name__}: {exc}")

        total = (time.perf_counter() - started) * 1000
        text = "".join(chunks)
        n_out = len(chunks) or 1
        # 生成にかかった時間 ÷ 生成トークン数。TTFT を差し引くのが要点
        tpot = (total - (ttft or 0)) / max(n_out - 1, 1)
        return GenResult(text, ttft or total, total, n_out, tpot, slot_id)
