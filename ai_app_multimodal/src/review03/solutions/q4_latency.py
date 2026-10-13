"""問題4：遅延の内訳（セッション10）から支配的な区間を見つけ、認識の RTF と待ち時間（セッション8）、
文ごとの合成の効果（セッション9）を数字で確かめて、対策を選ぶ。

    docker compose exec api python -m src.review03.solutions.q4_latency
"""

from __future__ import annotations

from src.review03.kit import TurnTimes, plan_sentences, plan_whole

PARTS = ("vad", "stt", "llm_first_sentence", "tts_first")
OTHER = "その他"

# (時刻の記録, 発話の秒数, 認識の処理時間〔利用量の processing_seconds〕)
TURNS = {
    "A": (TurnTimes(10.0, 10.6, 12.25, 12.3, 15.7, 15.712), 3.81, 1.62),
    "B": (TurnTimes(20.0, 20.6, 22.25, 23.72, 27.12, 27.132), 3.81, 1.62),
    "C": (TurnTimes(30.0, 30.6, 34.45, 34.5, 37.9, 37.912), 3.81, 1.65),
    "D": (TurnTimes(40.0, 40.6, 41.0), 0.9, 0.38),
}
AUDIO = [8.5, 4.5, 5.5, 4.5, 7.5]   # 返答5文の音声の秒数


def countermeasure(name: str, stt_wait: int, stt_processing: int) -> str:
    if name == "vad":
        return "終端の無音を短くする"
    if name == "stt":
        return "認識の順番待ちを減らす" if stt_wait > stt_processing else "認識の設定を見直す"
    if name == "llm_first_sentence":
        return "最初の文を早く出させる"
    if name == "tts_first":
        return "最初の文を短くする"
    return "送る WAV と処理の詰まりを調べる"


def diagnose(label: str, times: TurnTimes, audio_s: float, processing_s: float) -> str:
    lat = times.latency_ms()
    processing = round(processing_s * 1000)
    wait = lat["stt"] - processing                   # stt の区間には limiter の順番待ちも入る
    rtf = processing_s / audio_s                     # セッション8の RTF は「処理時間 ÷ 音声の長さ」
    stt = f"stt {lat['stt']}（待ち {wait}・RTF {rtf:.2f}）"
    if lat["first_audio"] is None:
        return f"{label}: vad {lat['vad']}・{stt}・返答なし → 内訳を比べない"
    other = lat["first_audio"] - sum(lat[k] for k in PARTS)
    parts = {**{k: lat[k] for k in PARTS}, OTHER: other}
    name = max(parts, key=parts.get)
    share = round(parts[name] / lat["first_audio"] * 100, 1)
    shown = "・".join(stt if k == "stt" else f"{k} {v}" for k, v in parts.items())
    return f"{label}: {shown} → {name} が {share}% → {countermeasure(name, wait, processing)}"


def timeline(rtf: float) -> str:
    synth = [round(a * rtf, 3) for a in AUDIO]
    each = plan_sentences(synth, AUDIO)
    whole = plan_whole(sum(synth), sum(AUDIO))
    gaps = "/".join(str(g) for g in each.gaps)
    return (f"文ごと（RTF {rtf}）: 最初の音 {each.first_audio} 秒・途切れ {gaps}・鳴り終わり {each.finished} 秒"
            f" ／ 全文: 最初の音 {whole.first_audio} 秒・鳴り終わり {whole.finished} 秒")


def main() -> None:
    for label, (times, audio_s, processing_s) in TURNS.items():
        print(diagnose(label, times, audio_s, processing_s))
    for rtf in (0.4, 1.2):
        print(timeline(rtf))


if __name__ == "__main__":
    main()
