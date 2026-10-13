"""閉ループ検査：VOICEVOX で読み上げ → faster-whisper で認識し直し → CER が上限以下か。1件でも超えたら終了コード 1。

    docker compose exec api python -m src.session08.loopback_check
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import anyio

from kondate import stt
from kondate.audio import wav_to_float32
from kondate.metrics import cer
from kondate.settings import get_settings
from kondate.tts import Voicevox
from src.session08.phrases import LOOPBACK_TEXT
from src.session08.textnorm import cer_relaxed


@dataclass(frozen=True)
class Case:
    text: str
    max_cer: float = 0.10
    relaxed: bool = False      # True なら表記ゆれ（カタカナ・ひらがな等）を吸収した CER で判定する


@dataclass(frozen=True)
class Outcome:
    case: Case
    transcript: str
    score: float

    @property
    def passed(self) -> bool:
        return self.score <= self.case.max_cer


CASES = (
    Case(LOOPBACK_TEXT),                                          # ユーザー辞書（鶏むね肉）が効いているか
    Case("冷蔵庫に卵と牛乳とにんじんがあります。", relaxed=True),   # 「ニンジン」と書かれるのは誤りに数えない
)


def judge(case: Case, transcript: str) -> Outcome:
    score = cer_relaxed(case.text, transcript) if case.relaxed else cer(case.text, transcript)
    return Outcome(case, transcript, round(score, 4))


async def run_cases(cases=CASES) -> list[Outcome]:
    limiter = anyio.CapacityLimiter(1)
    vv = Voicevox()
    try:
        await vv.ensure_user_dict()      # 辞書も「検査するシステム」の一部
        outcomes = []
        for case in cases:
            tts = await vv.synthesize(case.text, sample_rate=get_settings().stt_sample_rate)
            audio, rate = wav_to_float32(tts.wav)
            res = await anyio.to_thread.run_sync(stt.transcribe, audio, rate, limiter=limiter)
            outcomes.append(judge(case, res.text))
        return outcomes
    finally:
        await vv.aclose()


def main() -> int:
    outcomes = asyncio.run(run_cases())
    for o in outcomes:
        mark = "PASS" if o.passed else "FAIL"
        kind = "ゆれ吸収" if o.case.relaxed else "厳密"
        print(f"{mark} {o.case.text} → {o.transcript}（CER {o.score}・{kind}・上限 {o.case.max_cer}）")
    failed = sum(not o.passed for o in outcomes)
    print(f"{len(outcomes) - failed}/{len(outcomes)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
