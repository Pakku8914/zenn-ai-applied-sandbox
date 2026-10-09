"""問題6の解答：ログの監査。出力済みの JSON 行に、伏せ忘れた PII・キーが残っていないかを調べる（CI で落とす用）。

使い方：python -m src.session14.q6_audit ログファイル…   → 見つかれば1行ずつ表示して終了コード 1
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from .mask import EMAIL, KD_KEY, PHONE, REDACTED, SECRET_KEYS, SK_KEY

# 伏せた後の形（[REDACTED]・kd_ + 5文字…）には反応しない
BEARER_LEFT = re.compile(r"(?i)(?<![A-Za-z])bearer\s+(?!\[REDACTED\])\S+")
DETECTORS: dict[str, re.Pattern[str]] = {
    "email": EMAIL, "phone": PHONE, "kd_key": KD_KEY, "sk_key": SK_KEY, "bearer": BEARER_LEFT}
SKIP_PATHS = frozenset({"ts", "request_id", "job_id", "upstream_request_id"})  # 自分で作った値


@dataclass(frozen=True)
class Finding:
    line: int  # 1 始まり
    path: str  # 例：headers.authorization・note[0]
    kind: str  # email / phone / kd_key / sk_key / bearer / secret_key / not_json


def _walk(value: object, path: str) -> Iterator[tuple[str, object]]:
    """(項目の場所, 値) を葉までたどる。辞書の項目そのもの（名前で伏せる判定用）も返す。"""
    if isinstance(value, dict):
        for k, v in value.items():
            child = f"{path}.{k}" if path else str(k)
            yield child, v
            if isinstance(v, (dict, list)):
                yield from _walk(v, child)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            child = f"{path}[{i}]"
            yield child, v
            if isinstance(v, (dict, list)):
                yield from _walk(v, child)


def audit(lines: Iterable[str]) -> list[Finding]:
    findings: list[Finding] = []
    for no, line in enumerate(lines, 1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            findings.append(Finding(no, "", "not_json"))  # JSON でない行は、伏せ字の仕組みを通っていない
            continue
        for path, value in _walk(record, ""):
            if path in SKIP_PATHS:
                continue
            name = path.rsplit(".", 1)[-1].lower()
            if name in SECRET_KEYS and value != REDACTED:
                findings.append(Finding(no, path, "secret_key"))
            if isinstance(value, str):
                findings.extend(Finding(no, path, kind) for kind, p in DETECTORS.items() if p.search(value))
    return findings


def main(paths: list[str]) -> int:
    found = 0
    for path in paths:
        with open(path, encoding="utf-8") as f:
            for item in audit(f.read().splitlines()):
                print(f"{path}:{item.line}: {item.kind} at {item.path or '(行全体)'}")
                found += 1
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
