"""Whisper のモデルと設定を変えて、10文の CER と RTF を比べる。RTF は表示するだけで、合否には使わない。

    docker compose exec api python -m src.session08.compare
    docker compose exec api python -m src.session08.compare --models tiny base small --beams 1 5

まだ取得していないモデルは、最初に Hugging Face から取得する（tiny 75MiB・base 142MiB）。
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import time
from dataclasses import dataclass

import numpy as np
from faster_whisper import WhisperModel

from kondate import stt
from kondate.audio import wav_to_float32
from kondate.metrics import levenshtein, normalize_ja
from kondate.settings import get_settings
from kondate.tts import Voicevox
from src.session08.phrases import SENTENCES
from src.session08.textnorm import normalize_relaxed

RATE = 16000


@dataclass(frozen=True)
class Row:
    model: str
    compute_type: str
    beam: int
    threads: int
    cer: float           # 厳密（normalize_ja だけ）
    cer_relaxed: float   # 表記ゆれを吸収
    rtf: float           # 表示のみ（合否に使わない）
    transcripts: tuple[str, ...]


async def synthesize_all(texts) -> list[np.ndarray]:
    """文を VOICEVOX で 16kHz の音声にする。辞書の有無で結果が変わらないよう、先に辞書を登録する。"""
    vv = Voicevox()
    try:
        await vv.ensure_user_dict()
        clips = []
        for text in texts:
            tts = await vv.synthesize(text, sample_rate=RATE)
            audio, _ = wav_to_float32(tts.wav)
            clips.append(audio)
        return clips
    finally:
        await vv.aclose()


def corpus_cer(refs, hyps, norm) -> float:
    """全文の編集距離の合計 ÷ 全文の文字数の合計（長い文ほど重く数える）。"""
    edits = sum(levenshtein(norm(r), norm(h)) for r, h in zip(refs, hyps, strict=True))
    return edits / max(1, sum(len(norm(r)) for r in refs))


def evaluate(clips, texts, model: str, *, compute_type: str = "int8", beam: int = 1, threads: int = 2) -> Row:
    m = WhisperModel(stt.model_path(model), device="cpu", compute_type=compute_type, cpu_threads=threads)
    hyps, busy = [], 0.0
    for audio in clips:
        started = time.perf_counter()
        segments, _ = m.transcribe(audio, language="ja", beam_size=beam, condition_on_previous_text=False)
        hyps.append("".join(s.text for s in segments).strip())   # segments は遅延評価。ここで認識が走る
        busy += time.perf_counter() - started
    seconds = sum(len(a) for a in clips) / RATE
    return Row(
        model, compute_type, beam, threads,
        round(corpus_cer(texts, hyps, normalize_ja), 3),
        round(corpus_cer(texts, hyps, normalize_relaxed), 3),
        round(busy / seconds, 2),
        tuple(hyps),
    )


def main() -> int:
    s = get_settings()
    p = argparse.ArgumentParser(description="Whisper のモデルと設定を比べる")
    p.add_argument("--models", nargs="+", default=[s.whisper_model], choices=sorted(stt.REVISIONS))
    p.add_argument("--compute-types", nargs="+", default=[s.whisper_compute_type])
    p.add_argument("--beams", nargs="+", type=int, default=[s.whisper_beam_size])
    p.add_argument("--threads", nargs="+", type=int, default=[s.whisper_cpu_threads])
    a = p.parse_args()

    clips = asyncio.run(synthesize_all(SENTENCES))
    print(f"{len(clips)}文・合計 {sum(len(c) for c in clips) / RATE:.1f} 秒（16kHz・モノラル・辞書あり）")
    print("model  compute  beam  threads  CER(厳密)  CER(ゆれ吸収)  RTF(表示のみ)")
    rows = []
    for model, ct, beam, th in itertools.product(a.models, a.compute_types, a.beams, a.threads):
        row = evaluate(clips, SENTENCES, model, compute_type=ct, beam=beam, threads=th)
        rows.append(row)
        print(f"{model:<6} {ct:<8} {beam:>4}  {th:>7}  {row.cer:>9.3f}  {row.cer_relaxed:>13.3f}  {row.rtf:>12.2f}")
    print("誤りのあった文：")
    for row in rows:
        for ref, hyp in zip(SENTENCES, row.transcripts, strict=True):
            if normalize_ja(ref) != normalize_ja(hyp):
                print(f"  [{row.model}・{row.compute_type}・beam {row.beam}] {ref} → {hyp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
