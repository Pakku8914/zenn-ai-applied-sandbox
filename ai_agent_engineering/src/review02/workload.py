#!/usr/bin/env python3
"""復習02：6件の業務要求に対する「構造の選択」を規則にする（LLM を1回も呼ばない）。

    docker compose exec app python src/review02/workload.py

同じ業務要求に対して、決めることは4つある。

  ① 状態の持ち方   … 履歴のみ / 構造体＋履歴 / 状態機械            （S06）
  ② 圧縮           … 不要 / 選択的保持 / 状態へ移す＋切り捨て      （S07）
  ③ 体制           … 単体 / オーケストレータ / ハンドオフ          （S08）
  ④ チェックポイントの粒度 … 不要 / ステップ単位 / サブゴール単位   （S06）

大事なのは「どれを選んだか」ではなく **どの属性を見て選んだか** である。
規則にしておけば、次に似た要求が来たときに同じ答えが出る（人によって、日によって
答えが変わる判断は設計ではない）。
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from _paths import setup

ROOT = setup()


@dataclass(frozen=True)
class Request:
    """業務要求。属性はすべて「設計前に人が答えられること」だけで構成する。

    hands           : 正常に終わるときの手数（＝LLM 呼び出し回数）の見積り
    branches        : 途中で道が分かれるか（条件によってやることが変わる）
    irreversible    : 取り返しのつかない操作を含むか（予約・送信・申請）
    must_resume     : 途中で落ちたら「続きから」やり直したいか
    big_results     : ツール結果が大きいか（一覧・文書の全文など）
    parallel_parts  : 独立に数手かかる仕事が複数あるか
                      （1ステップで並列に取れる読み取り2本は**これに当たらない**）
    one_way         : 前段の結論だけで次に進めるか（戻って見直す必要がないか）
    mixed_authority : 権限の違う仕事が混ざるか（読むだけの仕事と外部へ出す仕事）
    """

    name: str
    hands: int
    branches: bool = False
    irreversible: bool = False
    must_resume: bool = False
    big_results: bool = False
    parallel_parts: bool = False
    one_way: bool = False
    mixed_authority: bool = False


REQUESTS = (
    Request("請求書1件の区分を判定する", hands=1),
    Request("今月の経費レポートを作る", hands=4, big_results=True),
    Request("四半期の棚卸し（洗い出し→レポート→報告会の予約）", hands=9,
            branches=True, irreversible=True, must_resume=True, big_results=True),
    Request("全部門の四半期監査（4部門ぶんの部門別レポート）", hands=14,
            must_resume=True, big_results=True, parallel_parts=True),
    Request("社外への謝罪文（調査→起案→所属長確認→送信）", hands=6,
            branches=True, irreversible=True, must_resume=True,
            one_way=True, mixed_authority=True),
    Request("手順書を最新の規程から書き直す", hands=7,
            big_results=True, one_way=True),
)


# ---------------------------------------------------------------------------
# ① 状態の持ち方（S06）
# ---------------------------------------------------------------------------
def choose_state(req: Request) -> str:
    """副作用があるなら状態機械。順序違反を**実行の前に**止められるのはこれだけ。

    構造体＋履歴は「状態が読める」だけで、段階を飛ばした操作は止まらない
    （S06 の `struct_only()` が実演したとおり、state を done に書き換えても誰も
    止めなかった）。
    """
    if req.irreversible:
        return "状態機械"
    if req.must_resume or req.branches:
        return "構造体＋履歴"
    return "履歴のみ"


# ---------------------------------------------------------------------------
# ② 圧縮（S07）
# ---------------------------------------------------------------------------
def choose_compression(req: Request) -> str:
    """溢れないなら圧縮しない。溢れるなら「捨てる前に状態へ移す」かどうかで分かれる。

    再開したいなら、捨てる判断材料を先に状態へ移しておかないと、
    再開したときに同じ結論を出せない（復習02 の resume.py で実測する）。
    """
    if not req.big_results:
        return "不要"
    if req.must_resume:
        return "状態へ移す＋切り捨て"
    return "選択的保持"


# ---------------------------------------------------------------------------
# ③ 体制（S08）
# ---------------------------------------------------------------------------
def choose_team(req: Request) -> str:
    """分けるのは「権限が違う」か「独立に数手かかる仕事が複数ある」ときだけ。

    一方向に流れる長い仕事はハンドオフにできるが、渡すものを構造化しないと
    文脈が落ちる（復習02 の split.py で実測する）。
    """
    if req.mixed_authority or req.parallel_parts:
        return "オーケストレータ"
    if req.one_way and req.big_results:
        return "ハンドオフ"
    return "単体"


# ---------------------------------------------------------------------------
# ④ チェックポイントの粒度（S06）
# ---------------------------------------------------------------------------
def choose_checkpoint(req: Request) -> str:
    """再開しないなら保存しない。副作用があるならやり直しを0手にする。

    S06 の実測：ステップ単位は完走で9回保存してやり直し0手、サブゴール単位は
    5回保存してやり直し1手。副作用のある1手をやり直すのが最も危ない。
    """
    if not req.must_resume:
        return "不要"
    if req.irreversible:
        return "ステップ単位"
    return "サブゴール単位"


DECISIONS = (
    ("状態の持ち方", choose_state),
    ("圧縮", choose_compression),
    ("体制", choose_team),
    ("チェックポイントの粒度", choose_checkpoint),
)


def decide(req: Request) -> dict:
    """4つの決定をまとめて返す。"""
    return {label: fn(req) for label, fn in DECISIONS}


def truth() -> dict:
    """6件ぶんの答え（要求名 → 4つの決定）。"""
    return {req.name: decide(req) for req in REQUESTS}


def flip_effect(req: Request, attr: str) -> dict:
    """属性を1つだけ True にすると、どの決定が動くかを見る。

    「1つ違うだけで答えが変わる」ことが分かると、属性を埋める作業が
    設計そのものだと分かる。
    """
    changed = replace(req, **{attr: True})
    before, after = decide(req), decide(changed)
    return {"要求": req.name, "変えた属性": attr, "変更前": before, "変更後": after,
            "動いた決定": [k for k in before if before[k] != after[k]]}


def by_name(name: str) -> Request:
    return next(r for r in REQUESTS if r.name == name)


def main() -> None:
    print("=== 6件の業務要求に対する構造の選択（LLM 呼び出し 0 回）===")
    print("要求 | 手数 | 状態の持ち方 | 圧縮 | 体制 | チェックポイントの粒度")
    for req in REQUESTS:
        d = decide(req)
        print(f"{req.name} | {req.hands} | {d['状態の持ち方']} | {d['圧縮']} | "
              f"{d['体制']} | {d['チェックポイントの粒度']}")

    print()
    print("=== 属性を1つ変えると、いくつの決定が動くか ===")
    base = by_name("今月の経費レポートを作る")
    for attr in ("irreversible", "must_resume", "parallel_parts"):
        effect = flip_effect(base, attr)
        print(f"{attr} を True にする → 動いた決定 {effect['動いた決定']}")


if __name__ == "__main__":
    main()
