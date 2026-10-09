"""前半・練習問題3の解答：カセット（JSONL）を読み、呼び出しごとの中身を要約する。"""

from __future__ import annotations

from pathlib import Path

from ..cassette import event_from_json, load_cassette
from ..providers import Done, ProviderError, TextDelta


def summarize_cassette(path: Path) -> list[dict]:
    """1行（上流への呼び出し1回）ごとに、種類・発言・イベントの並び・本文の文字数・usage を返す。"""
    out: list[dict] = []
    for entry in load_cassette(path):
        items = [event_from_json(d) for d in entry["events"]]
        runs: list[list] = []
        for item in items:
            name = f"ProviderError({item.kind})" if isinstance(item, ProviderError) else type(item).__name__
            if runs and runs[-1][0] == name:
                runs[-1][1] += 1
            else:
                runs.append([name, 1])
        done = next((item for item in items if isinstance(item, Done)), None)
        out.append({
            "call": entry["call"],
            "prompt": entry["request"]["messages"][-1]["content"],
            "shape": " → ".join(n if c == 1 else f"{n}×{c}" for n, c in runs),
            "chars": sum(len(item.text) for item in items if isinstance(item, TextDelta)),
            "usage": None if done is None else (done.usage.input_tokens, done.usage.output_tokens),
        })
    return out
