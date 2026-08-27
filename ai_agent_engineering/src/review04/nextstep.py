#!/usr/bin/env python3
"""復習04：週次の数字から「次の一手」を1つだけ決める（問題8）。

    python src/review04/nextstep.py

運用の会議が長引く原因はだいたい同じで、**同時に複数の問題が見えている**ことである。
禁止ツールも呼ばれているし、予算も超えている。両方直したいので両方に手を付け、
どちらも終わらないまま次の週が来る。

そこで優先順位を規則にする。

    安全（禁止ツール）> 正しさ（期待整合率・成果物）> 遅さ（SLO）> コスト（予算）

順に見て、最初に引っかかったところで止める。**一手だけ返す**のが要点である。
規則にしておけば、深夜に叩き起こされた人でも同じ答えを出せる。
"""

from __future__ import annotations

from dataclasses import dataclass

from _paths import setup

ROOT = setup()

from signals import yen  # noqa: E402

# 次の一手の語彙。**増やさない**（増えると週ごとに違う言葉で報告されて蓄積できない）
ACTIONS: dict[str, tuple[str, str]] = {
    "止めて戻す": ("回す", "段階リリースを止め、旧構成に戻す。進行中のジョブは runbook に従う"),
    "原因を1件に絞る": ("追う", "記録から1件を再生し、原因のステップを特定してから直す"),
    "内容検査を足す": ("測る", "成果物の中身の検査を受け入れ基準に足し、回帰テストに入れる"),
    "容量を決め直す": ("回す", "多重度・レート上限・非同期＋通知の3択から選ぶ"),
    "コストの打ち手を選ぶ": ("支払う", "失うものが小さい順に打ち手を足し、収まったら止める"),
    "何もしない": ("—", "どの基準も割っていない。測り続ける"),
}

MIN_DECLARED_RATE = 1.0     # 期待整合率はここを下回ったら回帰を疑う（S13）


@dataclass(frozen=True)
class Snapshot:
    """1週間ぶんの数字。4系統から1つずつ取ってくる。"""

    week: str
    forbidden: int          # 回す：カナリアで検出した禁止ツールの呼び出し
    declared_rate: float    # 測る：期待整合率
    missing_artifacts: int  # 測る：成果物の中身が欠けた件数
    makespan: int           # 回す：完了（仮想秒）
    slo: int                # 回す：目標
    cost_rin: int           # 支払う：月次の費用（厘）
    budget_rin: int         # 支払う：予算（厘）


WEEKS: tuple[Snapshot, ...] = (
    Snapshot("W1", 1, 1.000, 0, 12, 15, 29_494_800, 25_000_000),
    Snapshot("W2", 0, 0.833, 0, 12, 15, 24_545_700, 25_000_000),
    Snapshot("W3", 0, 1.000, 2, 12, 15, 24_545_700, 25_000_000),
    Snapshot("W4", 0, 1.000, 0, 24, 15, 24_545_700, 25_000_000),
    Snapshot("W5", 0, 1.000, 0, 12, 15, 29_494_800, 25_000_000),
    Snapshot("W6", 0, 1.000, 0, 12, 15, 24_545_700, 25_000_000),
)


def decide(s: Snapshot) -> dict:
    """次の一手を1つ返す。順に見て、最初に引っかかったところで止める。"""
    if s.forbidden > 0:
        action, why = "止めて戻す", f"禁止ツールの呼び出しが {s.forbidden} 件"
    elif s.declared_rate < MIN_DECLARED_RATE:
        action, why = ("原因を1件に絞る",
                       f"期待整合率 {s.declared_rate:.3f} が基準 "
                       f"{MIN_DECLARED_RATE:.3f} を下回った")
    elif s.missing_artifacts > 0:
        action, why = "内容検査を足す", f"成果物の中身が {s.missing_artifacts} 件欠けている"
    elif s.makespan > s.slo:
        action, why = "容量を決め直す", f"完了 {s.makespan} 秒 > SLO {s.slo} 秒"
    elif s.cost_rin > s.budget_rin:
        action, why = ("コストの打ち手を選ぶ",
                       f"費用 {yen(s.cost_rin)} 円 > 予算 {yen(s.budget_rin)} 円")
    else:
        action, why = "何もしない", "どの基準も割っていない"
    family, detail = ACTIONS[action]
    return {"週": s.week, "次の一手": action, "見た系統": family,
            "理由": why, "やること": detail}


def also_triggered(s: Snapshot) -> list[str]:
    """引っかかっているが、今週は手を付けない基準。報告には残す。"""
    chosen = decide(s)["次の一手"]
    hits = []
    if s.forbidden > 0:
        hits.append("止めて戻す")
    if s.declared_rate < MIN_DECLARED_RATE:
        hits.append("原因を1件に絞る")
    if s.missing_artifacts > 0:
        hits.append("内容検査を足す")
    if s.makespan > s.slo:
        hits.append("容量を決め直す")
    if s.cost_rin > s.budget_rin:
        hits.append("コストの打ち手を選ぶ")
    return [h for h in hits if h != chosen]


def render_mermaid() -> str:
    """測定結果から次の一手までの分岐図。12行になる。"""
    return "\n".join([
        "flowchart TD",
        '    S["週次の測定（測る・追う・回す・支払う）"] --> A{"禁止ツールの呼び出しがあるか"}',
        '    A -->|ある| R1["止めて戻す（回す）"]',
        '    A -->|ない| B{"期待整合率が 1.000 未満か"}',
        '    B -->|未満| R2["原因を1件に絞る（追う）"]',
        '    B -->|以上| C{"成果物の不足があるか"}',
        '    C -->|ある| R3["内容検査を足す（測る）"]',
        '    C -->|ない| D{"完了が SLO を超えたか"}',
        '    D -->|超えた| R4["容量を決め直す（回す）"]',
        '    D -->|以内| E{"費用が予算を超えたか"}',
        '    E -->|超えた| R5["コストの打ち手を選ぶ（支払う）"]',
        '    E -->|以内| R6["何もしない（測り続ける）"]',
    ])


def main() -> None:
    print("=== 週次スナップショットから次の一手を1つだけ決める ===")
    print("週 | 禁止 | 期待整合率 | 成果物の不足 | 完了/SLO | 費用/予算(円) | "
          "次の一手 | 見た系統")
    for s in WEEKS:
        d = decide(s)
        print(" | ".join([
            s.week, str(s.forbidden), f"{s.declared_rate:.3f}",
            str(s.missing_artifacts), f"{s.makespan}/{s.slo}",
            f"{yen(s.cost_rin)}/{yen(s.budget_rin)}",
            d["次の一手"], d["見た系統"],
        ]))

    print("\n=== 手を付けないが、報告には残すもの ===")
    print("週 | 今週やること | 見送るもの")
    for s in WEEKS:
        skipped = also_triggered(s)
        print(f"{s.week} | {decide(s)['次の一手']} | {'／'.join(skipped) or 'なし'}")
    print("→ W1 は費用も予算を超えているが、選ぶ一手は1つだけである"
          "（安全 > 正しさ > 遅さ > コスト）。")

    print("\n=== 次の一手の語彙（増やさない）===")
    print("次の一手 | 見た系統 | やること")
    for action, (family, detail) in ACTIONS.items():
        print(f"{action} | {family} | {detail}")

    print("\n=== 分岐図 ===")
    print(render_mermaid())


if __name__ == "__main__":
    main()
