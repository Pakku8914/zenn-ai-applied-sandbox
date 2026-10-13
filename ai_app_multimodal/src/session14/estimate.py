"""月の費用の見積もり。単価は pricing.yaml（例示用の仮の値）から読み、計算は Decimal で行う（小数の誤差を出さない）。

    docker compose exec api python -m src.session14.estimate

LLM は「1回あたりのトークン×回数×単価」、音声は「処理秒数（CPU を占有する時間）」で見積もる。
1回あたりのトークンは mockllm で測った値（冷蔵庫の写真 1668/194、recipe_book.pdf への質問 4888/38）。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import yaml

PRICING = Path(__file__).with_name("pricing.yaml")
UNIT_TOKENS = {"fridge_scan": (1668, 194), "pdf_ask": (4888, 38)}  # 1回あたり（入力, 出力）
MTOK = Decimal(1_000_000)
CENT, TENTH = Decimal("0.01"), Decimal("0.1")


def q(value: Decimal, unit: Decimal) -> Decimal:
    return value.quantize(unit, rounding=ROUND_HALF_UP)


def to_decimal(obj):
    """YAML の数値を Decimal にする（float のまま掛け算すると 6.390000000000001 のような値になる）。"""
    if isinstance(obj, dict):
        return {k: to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, (int, float)) and not isinstance(obj, bool):
        return Decimal(str(obj))
    return obj


def load_pricing(path: Path = PRICING) -> dict:
    return to_decimal(yaml.safe_load(path.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class Workload:
    """1日あたりの利用の想定（仮定。自分のアプリの数字に置き換える）。"""
    fridge_scans: int = 200
    pdf_asks: int = 100
    voice_turns: int = 300
    utterance_seconds: Decimal = Decimal("4.0")     # 1回の発話の長さ
    reply_audio_seconds: Decimal = Decimal("10.0")  # 1回の返答を読み上げる長さ
    stt_rtf: Decimal = Decimal("0.6")               # 実測 0.45〜0.60 の上側
    tts_rtf: Decimal = Decimal("0.55")              # 実測 0.39〜0.55 の上側
    peak_share: Decimal = Decimal("0.3")            # 1日の会話のうち、いちばん混む1時間に集まる割合
    response_cache_hit_rate: Decimal = Decimal("0")
    server_vcpus: int = 4
    days: int = 30


def estimate(w: Workload, p: dict) -> dict:
    miss = 1 - w.response_cache_hit_rate                      # 応答キャッシュに当たらず LLM を呼ぶ割合
    scans = w.fridge_scans * w.days * miss
    asks = w.pdf_asks * w.days * miss
    in_tok = scans * UNIT_TOKENS["fridge_scan"][0] + asks * UNIT_TOKENS["pdf_ask"][0]
    out_tok = scans * UNIT_TOKENS["fridge_scan"][1] + asks * UNIT_TOKENS["pdf_ask"][1]
    in_cost = in_tok / MTOK * p["llm"]["input_per_mtok"]
    out_cost = out_tok / MTOK * p["llm"]["output_per_mtok"]

    stt_turn = w.utterance_seconds * w.stt_rtf               # 1ターンの音声認識の処理秒数
    tts_turn = w.reply_audio_seconds * w.tts_rtf             # 1ターンの音声合成の処理秒数
    peak_turns = w.voice_turns * w.peak_share
    server = p["server"]["vcpu_hour"] * w.server_vcpus * 24 * w.days  # 常時起動（使っていない時間も払う）
    return {
        "llm_input_tokens": int(in_tok),
        "llm_output_tokens": int(out_tok),
        "llm_input_cost": q(in_cost, CENT),
        "llm_output_cost": q(out_cost, CENT),
        "llm_cost": q(in_cost + out_cost, CENT),
        "stt_seconds_per_day": q(w.voice_turns * stt_turn, TENTH),
        "tts_seconds_per_day": q(w.voice_turns * tts_turn, TENTH),
        "processing_hours_per_month": q(w.voice_turns * (stt_turn + tts_turn) * w.days / 3600, CENT),
        "peak_stt_percent": q(peak_turns * stt_turn / 3600 * 100, TENTH),
        "peak_tts_percent": q(peak_turns * tts_turn / 3600 * 100, TENTH),
        "server_cost": q(server, CENT),
        "total_cost": q(in_cost + out_cost + server, CENT),
    }


def report(w: Workload, p: dict) -> list[str]:
    e = estimate(w, p)
    cached = estimate(replace(w, response_cache_hit_rate=Decimal("0.2")), p)
    cur = p["currency"]
    lines = []
    if p["placeholder"]:
        lines.append("※ pricing.yaml の単価は例示用の仮の値です。実際の料金は公式の料金ページで確認して書き換えてください")
    lines += [
        f"1日の想定：冷蔵庫の写真 {w.fridge_scans}回・PDF への質問 {w.pdf_asks}回・音声のターン {w.voice_turns}回（{w.days}日）",
        f"LLM 入力：{e['llm_input_tokens']:,} トークン/月 → {e['llm_input_cost']} {cur}",
        f"LLM 出力：{e['llm_output_tokens']:,} トークン/月 → {e['llm_output_cost']} {cur}",
        f"LLM 合計：{e['llm_cost']} {cur}/月（応答キャッシュの命中率 0%）",
        f"LLM 合計：{cached['llm_cost']} {cur}/月（応答キャッシュの命中率 20%）",
        f"音声の処理秒数：STT {e['stt_seconds_per_day']:,} 秒/日・TTS {e['tts_seconds_per_day']:,} 秒/日"
        f"（月 {e['processing_hours_per_month']} 時間）",
        f"混む1時間の使用率：STT {e['peak_stt_percent']}%・TTS {e['peak_tts_percent']}%",
        f"サーバー（{w.server_vcpus} vCPU・常時起動）：{e['server_cost']} {cur}/月",
        f"合計（仮の値での計算例）：{e['total_cost']} {cur}/月",
    ]
    return lines


def main() -> None:
    for line in report(Workload(), load_pricing()):
        print(line)


if __name__ == "__main__":
    main()
