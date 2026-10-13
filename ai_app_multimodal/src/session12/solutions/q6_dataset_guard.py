"""問題6：評価セットの指紋（fingerprint）を記録し、基準と評価セットが違えば比べずに止める。

    docker compose exec api python -m src.session12.solutions.q6_dataset_guard --update-baseline
    docker compose exec api python -m src.session12.solutions.q6_dataset_guard

終了コード：0 回帰なし／1 回帰あり／2 基準がない・評価セットが違う。遅延は測らない（決定的な指標だけ）。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections.abc import Sequence

from kondate.media import EXPECTED_SHA12
from kondate.settings import get_settings
from src.session12 import eval_cer, eval_extract
from src.session12.eval_extract import OUT, write_json
from src.session12.evaluate import build_report, find_regressions
from src.session12.gold import Gold, fridge_gold, receipt_gold
from src.session12.matching import summarize

BASELINE = OUT / "baseline_q6.json"
MSG_DATASET = "評価セットが基準と違うため比べられません。--update-baseline で基準を作り直してください"


def default_golds() -> list[Gold]:
    return [fridge_gold(), receipt_gold("receipt.png"), receipt_gold("receipt.pdf")]


def fingerprint(golds: Sequence[Gold] | None = None, sentences: Sequence[str] = eval_cer.SENTENCES) -> str:
    """正解データ・発話の文・画像の版をキー順の JSON にし、SHA256 の先頭12桁を取る。"""
    golds = default_golds() if golds is None else golds
    data = {
        "extraction": [{"media": g.media, "items": list(g.items), "header": g.header,
                        "media_sha12": EXPECTED_SHA12[g.media]} for g in golds],
        "sentences": list(sentences),
    }
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:12]


def judge(report: dict, baseline: dict) -> tuple[int, list[str]]:
    if report.get("dataset") != baseline.get("dataset"):
        return 2, [MSG_DATASET]
    found = find_regressions(report, baseline)
    return (1 if found else 0), found


def main() -> int:
    p = argparse.ArgumentParser(description="評価セットの指紋つきで基準と比べる")
    p.add_argument("--update-baseline", action="store_true")
    a = p.parse_args()
    s = get_settings()
    results = asyncio.run(eval_extract.run_cases(eval_extract.mock_cases()))
    clips = asyncio.run(eval_cer.synthesize_all(eval_cer.SENTENCES))
    row = eval_cer.evaluate_config(clips, s.whisper_model, s.whisper_compute_type, s.whisper_beam_size,
                                   s.whisper_cpu_threads)
    report = {**build_report(summarize(x for x, _ in results), row, None), "dataset": fingerprint()}
    if a.update_baseline:
        write_json(BASELINE, report)
        print(f"基準を保存しました：{BASELINE}（評価セット {report['dataset']}）")
        return 0
    if not BASELINE.exists():
        print("基準がありません。先に --update-baseline で作ってください")
        return 2
    code, lines = judge(report, json.loads(BASELINE.read_text(encoding="utf-8")))
    for line in lines:
        print(line)
    print({0: "回帰なし", 1: f"回帰 {len(lines)} 件", 2: "比較できません"}[code])
    return code


if __name__ == "__main__":
    raise SystemExit(main())
