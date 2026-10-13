"""問題7：最初の文だけ「、」で早めに区切り、最初の音までの時間を縮める（ストリーミング版）。

    docker compose exec api python -m src.session10.solutions.q7_early_first --ttft-ms 400 --tps 40
"""

from __future__ import annotations

import argparse
import asyncio

from fastapi import FastAPI, WebSocket

from src.session10.app import accept_voice, lifespan
from src.session10.app import app as base_app
from src.session10.measure import LOOPBACK_TEXT, measure
from src.session10.sentence_buffer import SentenceBuffer
from src.session10.sentences import strip_markdown
from src.session10.session import VoiceSession
from src.session10.talk import speech_pcm


class EarlyFirstBuffer:
    """最初の文だけ、読む文字が min_chars 以上たまった最初の「、」で区切る。2つ目からは SentenceBuffer と同じ。"""

    def __init__(self, min_chars: int = 10) -> None:
        self.min_chars = min_chars
        self._head = ""                              # 最初の文が出るまでに届いた差分
        self._rest: SentenceBuffer | None = None     # 最初の文が出たあとを受け持つ

    def feed(self, delta: str) -> list[str]:
        if self._rest is not None:
            return self._rest.feed(delta)
        self._head += delta
        normal = SentenceBuffer()
        done = normal.feed(self._head)
        if done:                                     # 「、」より先に、ふつうに文が完成した
            self._rest = normal
            return done
        line = self._head[self._head.rfind("\n") + 1:]   # 書きかけの行（それより前の行に読む文字は無かった）
        for pos, ch in enumerate(line):
            if ch == "、" and len(strip_markdown(line[:pos + 1])) >= self.min_chars:
                self._rest = SentenceBuffer()
                return [strip_markdown(line[:pos + 1]), *self._rest.feed(line[pos + 1:])]
        return []

    def flush(self) -> list[str]:
        if self._rest is not None:
            return self._rest.flush()
        normal = SentenceBuffer()
        return normal.feed(self._head) + normal.flush()


class EarlyFirstSession(VoiceSession):
    def sentence_buffer(self) -> EarlyFirstBuffer:   # type: ignore[override]
        return EarlyFirstBuffer()


app = FastAPI(title="こんだてAI セッション10 問題7（最初の文を早める）", lifespan=lifespan)


@app.websocket("/ws/voice")
async def voice(ws: WebSocket) -> None:
    if await accept_voice(ws):
        await EarlyFirstSession(ws, ws.app.state).run()


def first_delta(buffer, text: str, size: int = 6) -> tuple[int, list[str]]:
    """size 文字ずつ流したとき、最初の文が出る差分の番号と、最後まで流した文の列。"""
    first, out = 0, []
    for n, i in enumerate(range(0, len(text), size), 1):
        got = buffer.feed(text[i:i + size])
        if got and not first:
            first = n
        out += got
    return first, out + buffer.flush()


async def main_async(args: argparse.Namespace) -> int:
    headers = {"x-mock-ttft-ms": str(args.ttft_ms), "x-mock-tps": str(args.tps)}
    pcm = await speech_pcm(LOOPBACK_TEXT)
    for label, target in (("ふつう", base_app), ("最初の文を早める", app)):
        results = await measure(target, pcm, headers, args.turns)
        values = [r["llm_first_sentence"] for r in results]
        firsts = [r["first_audio"] for r in results]
        print(f"{label}: llm_first_sentence {values}ms ／ first_audio {firsts}ms")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--ttft-ms", type=int, default=400)
    p.add_argument("--tps", type=int, default=40)
    p.add_argument("--turns", type=int, default=2)
    raise SystemExit(asyncio.run(main_async(p.parse_args())))
