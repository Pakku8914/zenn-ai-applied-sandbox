#!/usr/bin/env python3
"""キャッシュがテナントと権限を跨ぐ事故の再現と修正（セッション6）。

推論サーバは要らない。上流はスタブで「本来返るべき正解」を返すので、
返ってきた答えが正解と違えば、それはキャッシュが混ざった証拠になる。

    python src/session06/tenant_leak.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from infrakit.cache import ExactCache  # noqa: E402
from src.session06.cache_keys import CacheScope, ScopedCache  # noqa: E402

# 参照してよい資料の範囲。ロールから決まる
GENERAL = frozenset({"general"})
HR = frozenset({"general", "hr-confidential"})

# 1件あたりの推論時間の概算。Q8_0・並列1 の総時間 p50 = 730ms（2026-08-15 実測）を使う
COST_MS = 730.0

KIND_LABEL = {
    "unsafe": "プロンプトだけを鍵にする（ExactCache）",
    "scoped": "スコープを鍵に含める（ScopedCache）",
}


@dataclass(frozen=True)
class Ask:
    """1件の問い合わせ。誰が・どの範囲の資料を見られる立場で聞いたかを持つ。"""

    label: str
    tenant_id: str
    visibility: frozenset[str]
    prompt: str
    correct: str


# みなと商事グループの社内ヘルプデスク。本社と物流子会社を1つの基盤で相手にしている
SCENARIO: list[Ask] = [
    Ask("1. 本社の一般社員", "minato-hq", GENERAL,
        "駐車場の月額利用料はいくらですか。",
        "本社ビルの駐車場は月額 12,000 円です。"),
    Ask("2. 物流子会社の一般社員", "minato-logi", GENERAL,
        "駐車場の月額利用料はいくらですか。",
        "物流センターの駐車場は無料です。"),
    Ask("3. 本社の人事担当", "minato-hq", HR,
        "育児休業の申出はいつまでに行いますか。",
        "原則1か月前までです。人事規程 3.2（社外秘）に基づき運用します。"),
    Ask("4. 本社の一般社員", "minato-hq", GENERAL,
        "育児休業の申出はいつまでに行いますか。",
        "原則1か月前までです。詳細は人事部にお問い合わせください。"),
    Ask("5. 本社の一般社員（再質問）", "minato-hq", GENERAL,
        "駐車場の月額利用料はいくらですか。",
        "本社ビルの駐車場は月額 12,000 円です。"),
]


def generate(ask: Ask) -> str:
    """上流の推論のスタブ。その立場の人に返るべき正解を返す。"""
    return ask.correct


@dataclass
class ReplayReport:
    kind: str
    hits: int = 0
    misses: int = 0
    leaks: list[str] = field(default_factory=list)
    rows: list[tuple[str, str, str]] = field(default_factory=list)

    def summary(self) -> str:
        return (f"ヒット {self.hits} / ミス {self.misses} / "
                f"漏洩 {len(self.leaks)} 件")


def replay(kind: str, scenario: list[Ask] | None = None) -> ReplayReport:
    """同じ問い合わせ列を、鍵の作り方だけ変えて流し直す。"""
    asks = scenario if scenario is not None else SCENARIO
    report = ReplayReport(kind=KIND_LABEL[kind])
    unsafe = ExactCache(ttl_seconds=300.0)
    scoped = ScopedCache(ttl_seconds=300.0)

    for ask in asks:
        scope = CacheScope(tenant_id=ask.tenant_id, visibility=ask.visibility)
        got = unsafe.get(ask.prompt) if kind == "unsafe" else scoped.get(scope, ask.prompt)

        if got is None:
            report.misses += 1
            got = generate(ask)
            if kind == "unsafe":
                unsafe.put(ask.prompt, got, cost_ms=COST_MS)
            else:
                scoped.put(scope, ask.prompt, got, cost_ms=COST_MS)
            verdict = "ミス（推論した）"
        else:
            report.hits += 1
            verdict = "ヒット"

        if got != ask.correct:
            report.leaks.append(ask.label)
            verdict = "ヒット（別の答えが返った＝漏洩）"
        report.rows.append((ask.label, verdict, got))

    return report


def print_report(report: ReplayReport) -> None:
    print(f"--- {report.kind} ---")
    for label, verdict, text in report.rows:
        print(f"  {label} → {verdict}: {text}")
    print(f"  => {report.summary()}")


def main() -> None:
    print_report(replay("unsafe"))
    print()
    print_report(replay("scoped"))


if __name__ == "__main__":
    main()
