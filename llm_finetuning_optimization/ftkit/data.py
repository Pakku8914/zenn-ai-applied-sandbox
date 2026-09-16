"""データセットの読み込みと入力の組み立て（セッション3・4の参照実装）。

章をまたいで変えない（requirements.md の「API契約」）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

CATEGORIES = ["経費", "勤怠", "PC", "アカウント", "オフィス", "セキュリティ"]

# 分類タスクの指示文。学習時と評価時で必ず同じものを使う
CLASSIFY_INSTRUCTION = (
    "次の社内問い合わせを、経費・勤怠・PC・アカウント・オフィス・セキュリティのいずれか"
    "1つに分類してください。区分名だけを答えてください。"
)
# 整形タスクの指示文
FORMAT_INSTRUCTION = (
    "次の社内問い合わせに、【区分】【担当】【期限】の3行で回答してください。"
)


@dataclass(frozen=True)
class Example:
    id: str
    question: str
    category: str
    answer: str


def load(split: str) -> list[Example]:
    path = DATA / f"{split}.jsonl"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} がありません。先に `python tools/make_dataset.py` を実行してください。"
        )
    return [Example(**json.loads(line)) for line in path.open(encoding="utf-8") if line.strip()]


def load_preference() -> list[dict]:
    path = DATA / "preference.jsonl"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} がありません。先に `python tools/make_dataset.py` を実行してください。"
        )
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def build_prompt(example: Example, task: str = "classify") -> str:
    """モデルに渡すプロンプト（chat template を適用する前の素の本文）。"""
    instruction = CLASSIFY_INSTRUCTION if task == "classify" else FORMAT_INSTRUCTION
    return f"{instruction}\n\n問い合わせ: {example.question}"


def build_target(example: Example, task: str = "classify") -> str:
    """学習させたい出力。分類なら区分名だけ、整形なら3行の定型。"""
    return example.category if task == "classify" else example.answer


def to_messages(example: Example, task: str = "classify") -> list[dict]:
    """chat template に渡す形。テンプレートの適用は tokenize.py が行う。"""
    return [
        {"role": "user", "content": build_prompt(example, task)},
        {"role": "assistant", "content": build_target(example, task)},
    ]
