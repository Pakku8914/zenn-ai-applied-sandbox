#!/usr/bin/env python3
"""圧縮方式 — 短期メモリを上限内に収める4つのやり方（＋アンチパターン1つ）。

`agentkit.memory.ShortTermMemory` は既定で**何も圧縮しない**（わざと残した欠け）。
`truncate_oldest()` は用意されているのでそのまま使い、足りないもの
（選択的保持・要約・外部化）をこの層で足す。`agentkit` は変更しない。

    python src/session07/compress.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentkit.memory import ShortTermMemory  # noqa: E402
from records import (KEEP_KINDS, TOKENS_PER_RECORD, body_of,  # noqa: E402
                     group_key, kind_of, record)

MIN_GROUP = 8        # これ以上の大きさのかたまりを要約の対象にする
KEEP_RECENT = 6      # アンチパターン（全部要約）で手元に残す記録数

POLICIES = ("none", "truncate", "summarize", "keep", "externalize", "summarize_all")

POLICY_LABELS = {
    "none": "圧縮なし",
    "truncate": "切り捨て",
    "summarize": "要約",
    "keep": "選択的保持",
    "externalize": "外部化",
    "summarize_all": "全部要約（アンチパターン）",
}


def _clone(mem: ShortTermMemory, items: list[str]) -> ShortTermMemory:
    return ShortTermMemory(items=list(items), max_tokens=mem.max_tokens)


# ---------------------------------------------------------------------------
# 方式1: 切り捨て（agentkit の実装をそのまま使う）
# ---------------------------------------------------------------------------
def truncate(mem: ShortTermMemory) -> ShortTermMemory:
    """古い記録から捨てる。実装は最も簡単だが、最初の指示と制約が最初に消える。"""
    return mem.truncate_oldest()


# ---------------------------------------------------------------------------
# 方式2: 要約（同じ出典の大きなかたまりを、決定的な要約に置き換える）
# ---------------------------------------------------------------------------
def groups(items: list[str]) -> list[tuple[int, int, str]]:
    """同じ出典の連続したかたまりを (開始, 終了, 鍵) で返す。"""
    out: list[tuple[int, int, str]] = []
    i = 0
    while i < len(items):
        key = group_key(items[i])
        if not key:
            i += 1
            continue
        j = i
        while j < len(items) and group_key(items[j]) == key:
            j += 1
        out.append((i, j, key))
        i = j
    return out


def summarize_group(group: list[str], key: str) -> list[str]:
    """かたまりを2記録に圧縮する。**要約は決定的**（モデルに書かせない）。

    ここが情報欠落の発生点である。行数と件数は残るが、
    かたまりの中に紛れていた制約（監査方針の追記）は消える。
    """
    refs = sum(1 for r in group if "起票" in body_of(r))
    return [record("要約", f"{key} のログ {len(group)} 行を要約。"),
            record("要約", f"{key} 参照した申請は {refs} 件。")]


def summarize(mem: ShortTermMemory, min_size: int = MIN_GROUP) -> ShortTermMemory:
    """収まるまで、古いかたまりから順に要約に置き換える。"""
    items = list(mem.items)
    while _clone(mem, items).overflowing():
        target = next(((s, e, k) for s, e, k in groups(items) if e - s >= min_size), None)
        if target is None:
            break        # 要約できるかたまりが無い。これ以上は縮まない
        s, e, key = target
        items = items[:s] + summarize_group(items[s:e], key) + items[e:]
    return _clone(mem, items)


# ---------------------------------------------------------------------------
# 方式3: 選択的保持（制約と決定事項は必ず残し、残りを新しい順に詰める）
# ---------------------------------------------------------------------------
def keep(mem: ShortTermMemory) -> ShortTermMemory:
    """制約・指示・決定は落とさない。順序も保つ（因果が読めなくなるため）。"""
    items = list(mem.items)
    protected = {i for i, r in enumerate(items) if kind_of(r) in KEEP_KINDS}
    budget = mem.max_tokens - TOKENS_PER_RECORD * len(protected)
    keep_n = max(budget // TOKENS_PER_RECORD, 0)
    others = [i for i in range(len(items)) if i not in protected]
    kept = protected | (set(others[-keep_n:]) if keep_n > 0 else set())
    return _clone(mem, [items[i] for i in sorted(kept)])


# ---------------------------------------------------------------------------
# アンチパターン: 古い記録を「全部まとめて」要約する
# ---------------------------------------------------------------------------
def summarize_all(mem: ShortTermMemory, keep_recent: int = KEEP_RECENT) -> ShortTermMemory:
    """直近以外を1つの要約にまとめる。トークンは最小になるが制約が全部消える。"""
    items = list(mem.items)
    if len(items) <= keep_recent:
        return _clone(mem, items)
    old, recent = items[:-keep_recent], items[-keep_recent:]
    digest = [record("要約", f"これまでの {len(old)} 記録を要約。"),
              record("要約", "調査は順調に進んでいる。")]
    return _clone(mem, digest + recent)


# ---------------------------------------------------------------------------
def apply_policy(name: str, mem: ShortTermMemory) -> ShortTermMemory:
    """方式名から圧縮を適用する。`none` と `externalize` はここでは何もしない。

    `externalize`（外部化）は**溢れてから縮める**のではなく、
    メモリに入れる時点で外に出す方式なので、実行器の側（runner.py）で扱う。
    """
    if name not in POLICIES:
        raise ValueError(f"未知の圧縮方式です: {name!r}。使える方式: {', '.join(POLICIES)}")
    if name in ("none", "externalize"):
        return mem
    return {"truncate": truncate, "summarize": summarize,
            "keep": keep, "summarize_all": summarize_all}[name](mem)


if __name__ == "__main__":
    from bigtools import fetch_audit_log, list_expense_records, read_audit_policy
    from records import render_breakdown, retention, to_records

    base = ([record("指示", "2026年7月と8月の監査ログを確認する。"),
             record("制約", "5万円以上は必ず事前承認が必要。")]
            + to_records(read_audit_policy("経費精算"))
            + to_records(fetch_audit_log("2026-07"))
            + to_records(fetch_audit_log("2026-08"))
            + to_records(list_expense_records("all")))
    full = ShortTermMemory(items=base, max_tokens=1_980)
    print(render_breakdown(full.items))
    print()
    for name in ("truncate", "summarize", "keep", "summarize_all"):
        after = apply_policy(name, full)
        info = retention(full.items, after.items)
        print(f"{POLICY_LABELS[name]:<24} 記録={len(after.items):>4} "
              f"近似トークン={after.total_tokens():>5} "
              f"制約={info['残った制約']}/{info['制約の総数']}")
