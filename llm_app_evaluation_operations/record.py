"""カセット（記録済みレスポンス）を生成・更新するスクリプト。

    python record.py          # シード応答からカセットを作る（APIキー不要）
    python record.py --live   # 実際の Claude API を呼んで記録し直す（APIキー必要）

回帰テストを「毎回課金される不安定なテスト」から「毎回同じ結果が出る速いテスト」へ
変えるのが記録再生の目的。記録の更新は明示的なコマンドでしか起きないようにしておく
（テスト実行が黙って記録を書き換えると、回帰を検知できなくなる）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from app import APP_SYSTEM, build_prompt
from evalkit.client import AnthropicClient, LLMResponse, RecordedClient, make_key
from evalkit.dataset import load_dataset
from evalkit.judge import DEFAULT_RUBRIC, JUDGE_SYSTEM, JUDGE_TEMPLATE

BASE_DIR = Path(__file__).resolve().parent
DATASET = BASE_DIR / "datasets" / "faq_v1.jsonl"
SEED = BASE_DIR / "recordings" / "seed_faq_v1.json"
CASSETTE = BASE_DIR / "recordings" / "faq_v1.json"

SEED_MODEL = "claude-opus-5"


def estimate_tokens(text: str) -> int:
    """シード用のごく粗いトークン数見積り（実測値は usage から取る）。"""
    return max(1, len(text) // 3)


def seeded_response(text: str, prompt: str) -> LLMResponse:
    return LLMResponse(
        text=text,
        model=SEED_MODEL,
        input_tokens=estimate_tokens(prompt),
        output_tokens=estimate_tokens(text),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="評価用カセットの生成")
    parser.add_argument("--live", action="store_true", help="実 API を呼んで記録する")
    args = parser.parse_args()

    if args.live and not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY が未設定です。--live なしで実行するとシードから生成できます。")
        return 1

    cases = load_dataset(DATASET)
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    cassette = RecordedClient(CASSETTE, strict=False)
    live = AnthropicClient() if args.live else None

    for case in cases:
        app_prompt = build_prompt(case.input)
        if live is not None:
            answer = live.complete(app_prompt, system=APP_SYSTEM)
        else:
            entry = seed.get(case.id)
            if entry is None:
                print(f"[skip] {case.id}: シード応答がありません")
                continue
            answer = seeded_response(entry["answer"], app_prompt)
        cassette.save(make_key(app_prompt, APP_SYSTEM), answer)

        judge_prompt = JUDGE_TEMPLATE.format(
            rubric=case.rubric or DEFAULT_RUBRIC,
            question=case.input,
            answer=answer.text,
        )
        if live is not None:
            verdict = live.complete(judge_prompt, system=JUDGE_SYSTEM)
        else:
            verdict_json = json.dumps(seed[case.id]["judge"], ensure_ascii=False)
            verdict = seeded_response(verdict_json, judge_prompt)
        cassette.save(make_key(judge_prompt, JUDGE_SYSTEM), verdict)

        print(f"[ok] {case.id}: 記録しました")

    print(f"\nカセットを書き出しました: {CASSETTE.relative_to(BASE_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
