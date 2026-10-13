"""発話セットの CER を文字数加重で集計し、設定ごとの比較表を出す（セッション12）。

    docker compose exec api python -m src.session12.eval_cer
    docker compose exec api python -m src.session12.eval_cer --beams 1 5

10文を VOICEVOX で合成（辞書あり）→ faster-whisper で認識 → 文ごとの編集距離を足し上げる。
CER は「加重（Σ編集距離 ÷ Σ正解の文字数）」と「単純平均（文ごとの CER の平均）」を並べて出す。結果は out/s12/cer.json。
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
from collections.abc import Callable, Sequence

import numpy as np
from faster_whisper import WhisperModel

from kondate import stt
from kondate.audio import wav_to_float32
from kondate.metrics import levenshtein, normalize_ja
from kondate.settings import get_settings
from kondate.tts import Voicevox
from src.session12.eval_extract import OUT, write_json
from src.session12.textnorm import normalize_relaxed

RATE = 16000
Norm = Callable[[str], str]

# セッション8の10文（phrases.py の写し）。1文目は閉ループ検査の文
SENTENCES = (
    "鶏むね肉とキャベツで20分で作れる料理は？",
    "冷蔵庫に卵と牛乳とにんじんがあります。",
    "タイマーを5分にセットして。",
    "大さじ2杯は何ミリリットル？",
    "肉じゃがの作り方を最初から教えて。",
    "次の手順に進んでください。",
    "小麦を使わない晩ごはんを探して。",
    "豚こま切れ肉と玉ねぎの生姜焼きを4人分作りたい。",
    "買い物リストに豆腐とわかめを追加して。",
    "今日は30分以内で作れる和食がいいな。",
)


def edit_counts(pairs: Sequence[tuple[str, str]], norm: Norm) -> list[tuple[int, int]]:
    """文ごとの (編集距離, 正解の文字数)。どちらも正規化したあとで数える。"""
    return [(levenshtein(norm(ref), norm(hyp)), len(norm(ref))) for ref, hyp in pairs]


def cer_weighted(pairs: Sequence[tuple[str, str]], norm: Norm = normalize_ja) -> float:
    """Σ編集距離 ÷ Σ正解の文字数。長い文ほど重く数える（1文字の誤りはどの文でも同じ重さ）。"""
    counts = edit_counts(pairs, norm)
    return round(sum(e for e, _ in counts) / max(1, sum(n for _, n in counts)), 3)


def cer_mean(pairs: Sequence[tuple[str, str]], norm: Norm = normalize_ja) -> float:
    """文ごとの CER の単純平均。短い文の1文字が、長い文の1文字より重くなる。"""
    counts = edit_counts(pairs, norm)
    return round(sum(e / max(1, n) for e, n in counts) / len(counts), 3)


def aggregate(pairs: Sequence[tuple[str, str]]) -> dict:
    return {
        "cer_weighted": cer_weighted(pairs),
        "cer_weighted_relaxed": cer_weighted(pairs, normalize_relaxed),
        "cer_mean": cer_mean(pairs),
        "cer_mean_relaxed": cer_mean(pairs, normalize_relaxed),
    }


async def synthesize_all(texts: Sequence[str]) -> list[np.ndarray]:
    """文を VOICEVOX で 16kHz の音声にする（セッション8の compare.py と同じ）。合成は決定的なので、毎回同じ音声になる。"""
    vv = Voicevox()
    try:
        await vv.ensure_user_dict()
        clips = []
        for text in texts:
            audio, _ = wav_to_float32((await vv.synthesize(text, sample_rate=RATE)).wav)
            clips.append(audio)
        return clips
    finally:
        await vv.aclose()


def evaluate_config(clips: list[np.ndarray], model: str, compute_type: str, beam: int, threads: int) -> dict:
    """1つの設定で10文を認識し、集計した行を返す。async の外から呼ぶ同期処理（CPU を使い切る）。"""
    m = WhisperModel(stt.model_path(model), device="cpu", compute_type=compute_type, cpu_threads=threads)
    hyps = []
    for audio in clips:
        segments, _ = m.transcribe(audio, language="ja", beam_size=beam, condition_on_previous_text=False)
        hyps.append("".join(s.text for s in segments).strip())
    pairs = list(zip(SENTENCES, hyps, strict=True))
    return {"model": model, "compute_type": compute_type, "beam": beam, "threads": threads,
            **aggregate(pairs), "transcripts": hyps}


def main() -> int:
    s = get_settings()
    p = argparse.ArgumentParser(description="10文の CER を設定ごとに集計する")
    p.add_argument("--models", nargs="+", default=[s.whisper_model], choices=sorted(stt.REVISIONS))
    p.add_argument("--compute-types", nargs="+", default=[s.whisper_compute_type])
    p.add_argument("--beams", nargs="+", type=int, default=[s.whisper_beam_size])
    a = p.parse_args()

    clips = asyncio.run(synthesize_all(SENTENCES))
    chars = sum(len(normalize_ja(t)) for t in SENTENCES)
    print(f"{len(SENTENCES)}文・正解 {chars} 文字（正規化後）・VOICEVOX で合成（辞書あり）")
    print("model  compute  beam  加重(厳密)  加重(ゆれ吸収)  平均(厳密)  平均(ゆれ吸収)")
    rows = []
    for model, ct, beam in itertools.product(a.models, a.compute_types, a.beams):
        row = evaluate_config(clips, model, ct, beam, s.whisper_cpu_threads)
        rows.append(row)
        print(f"{model:<6} {ct:<8} {beam:>4}  {row['cer_weighted']:>10.3f}  {row['cer_weighted_relaxed']:>14.3f}"
              f"  {row['cer_mean']:>10.3f}  {row['cer_mean_relaxed']:>14.3f}")
    print("誤りのあった文：")
    for row in rows:
        for ref, hyp in zip(SENTENCES, row["transcripts"], strict=True):
            if normalize_ja(ref) != normalize_ja(hyp):
                print(f"  [{row['model']}・{row['compute_type']}・beam {row['beam']}] {ref} → {hyp}")
    write_json(OUT / "cer.json", {"sentences": list(SENTENCES), "rows": rows})
    print(f"→ {OUT / 'cer.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
