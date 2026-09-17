"""評価データセット（JSONL）の読み込み。

1 行 = 1 ケース。ケースには「入力」だけでなく「何が満たされていれば合格か」
を機械可読な形で書いておく。これが後のルールベース検査と judge の土台になる。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class EvalCase:
    """評価データセットの 1 ケース。"""

    id: str
    input: str
    expected: str | None = None
    tags: tuple[str, ...] = ()
    checks: dict = field(default_factory=dict)
    # judge に渡す採点基準。省略時はデータセット共通のルーブリックを使う
    rubric: str | None = None

    @classmethod
    def from_dict(cls, raw: dict) -> "EvalCase":
        missing = [k for k in ("id", "input") if k not in raw]
        if missing:
            raise ValueError(f"必須フィールドがありません: {missing} in {raw!r}")
        return cls(
            id=str(raw["id"]),
            input=str(raw["input"]),
            expected=raw.get("expected"),
            tags=tuple(raw.get("tags", ())),
            checks=dict(raw.get("checks", {})),
            rubric=raw.get("rubric"),
        )


def load_dataset(path: str | Path) -> list[EvalCase]:
    """JSONL を読み込んで EvalCase のリストを返す。

    空行と `#` で始まるコメント行は無視する。ID の重複は事故の原因になる
    ため、その場でエラーにする。
    """
    path = Path(path)
    cases: list[EvalCase] = []
    seen: set[str] = set()

    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno} JSON として読めません: {exc}") from exc
        case = EvalCase.from_dict(raw)
        if case.id in seen:
            raise ValueError(f"{path}:{lineno} ケースIDが重複しています: {case.id}")
        seen.add(case.id)
        cases.append(case)

    if not cases:
        raise ValueError(f"{path} に有効なケースが 1 件もありません")
    return cases


def filter_by_tag(cases: list[EvalCase], tag: str) -> list[EvalCase]:
    """特定タグのケースだけを取り出す（層別の合格率を見るときに使う）。"""
    return [case for case in cases if tag in case.tags]
