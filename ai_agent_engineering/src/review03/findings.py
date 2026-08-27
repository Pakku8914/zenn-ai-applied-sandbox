#!/usr/bin/env python3
"""復習03：仕様の穴のカタログと、監査の規則。

レビューの結論を「気をつけます」で終わらせないために、次の3つを分けて持つ。

  1. 穴のカタログ（`CATALOG`）… 名前・領域・根拠・確かめ方。**名前を勝手に増やさない**
  2. 監査の規則（`audit_spec`）… 仕様データから穴を検出する純粋関数
  3. 塞ぐ層の選び方（`pick_layer`）… 候補が複数あるとき、**測れる層を先に選ぶ**

    python src/review03/findings.py

`agentkit` は1行も変更しない。
"""

from __future__ import annotations

from _paths import setup

ROOT = setup()

from spec import (MAX_EXEC_TIMEOUT, POLICY_THRESHOLD, SOUND_INSPECTORS,  # noqa: E402
                  TASK_NEEDS, UNTRUSTED_SOURCES, AS_IS, Spec, TO_BE)

# ---------------------------------------------------------------------------
# 1. 穴のカタログ
# ---------------------------------------------------------------------------
AREAS = ("隔離", "承認", "信頼性", "権限・注入")

CATALOG: dict[str, dict] = {
    "F1": {
        "症状": "隔離コンテナに read_only が無い",
        "領域": "隔離", "出典": "S09",
        "根拠": "network_mode: none だけでは /etc/passwd に書けてしまう（検証ハーネスが実際に検出した）",
        "確かめ方": "rootfs への書き込みプローブが DENIED を返すこと",
    },
    "F2": {
        "症状": "コード実行の上限と予算が無い",
        "領域": "隔離", "出典": "S09",
        "根拠": f"timeout 60 秒は入口の上限 {MAX_EXEC_TIMEOUT} 秒を超えており、実行回数の予算も無い",
        "確かめ方": "上限を超える依頼を実行前に断ること／回数の予算に達したら断ること",
    },
    "F3": {
        "症状": "タスクに要らないツールを渡している",
        "領域": "権限・注入", "出典": "S12",
        "根拠": f"月次締めに必要なのは {len(TASK_NEEDS)} 本。渡した9本のうち5本は要らない",
        "確かめ方": "許可リストを絞った構成で、禁止された結果が減ること",
    },
    "F4": {
        "症状": "信頼できない入口が残っている",
        "領域": "権限・注入", "出典": "S12",
        "根拠": "read_file は前の実行や他人が書いた本文を返す（注入の入口は文書検索だけではない）",
        "確かめ方": "許可リストから外れ、宣言した信頼できない出所と食い違わないこと",
    },
    "F5": {
        "症状": "承認の判定がツール単位",
        "領域": "承認", "出典": "S10",
        "根拠": "3,200 円の申請でも止まり、分類表に無い run_python は素通しする",
        "確かめ方": "12 件の呼び出しで、止め損ないと余計な停止がどちらも 0 件になること",
    },
    "F6": {
        "症状": "承認の金額基準が規程と食い違う",
        "領域": "承認", "出典": "S10",
        "根拠": f"規程「経費精算」は1件 {POLICY_THRESHOLD:,} 円以上。仕様は 100,000 円",
        "確かめ方": "68,000 円の申請が事前承認になること",
    },
    "F7": {
        "症状": "失敗を無条件に再試行する",
        "領域": "信頼性", "出典": "S11",
        "根拠": "冪等でない submit_expense を再送すると二重申請になる",
        "確かめ方": "expenses の増分が1行に収まること",
    },
    "F8": {
        "症状": "モデルの申告で完了と判定する",
        "領域": "信頼性", "出典": "S11",
        "根拠": "実行されたか分からない操作が残っていても done になる",
        "確かめ方": "部分的失敗が残っているとき done にせず引き継ぎ書を返すこと",
    },
    "F9": {
        "症状": "出力検査が宛先の前方一致",
        "領域": "権限・注入", "出典": "S12",
        "根拠": "EMP-001.export@external.example.com のような似せた宛先を通す",
        "確かめ方": "似せた宛先を止め、正当な宛先と正当な書き込みは止めないこと",
    },
    "F10": {
        "症状": "監査ログが末尾の切り落としを検出できない",
        "領域": "承認", "出典": "S10",
        "根拠": "ハッシュ鎖は途中の改ざん・削除・挿入を検出するが、末尾を捨てても鎖は健全に見える",
        "確かめ方": "3行のログを2行に切り落としたとき、検査が失敗すること",
    },
}

# 穴に見えるが穴ではないもの（レビューで「これは指摘しない」と言えるようにする）
NOT_HOLES: dict[str, dict] = {
    "N1": {"症状": "network_mode: none になっている",
           "理由": "正しい指定。外へ出る経路が存在しないという保証そのもの"},
    "N2": {"症状": "mem_limit が 256m になっている",
           "理由": "コンテナ全体の上限として妥当。1回の実行に許す量は exec_limits 側で決める"},
    "N3": {"症状": "再試行の上限が2回になっている",
           "理由": "回数そのものは穴ではない。穴は「判断せずに再送すること」（F7）"},
}

REVIEW_ITEMS = (*CATALOG, *NOT_HOLES)   # 問題1で判断する13項目

# ---------------------------------------------------------------------------
# 2. 監査の規則（問題2でここを自分で書く）
# ---------------------------------------------------------------------------
def audit_spec(spec: Spec) -> list[str]:
    """仕様データから穴を検出する。戻り値は `CATALOG` の ID を宣言順に並べたもの。

    人が目で見て探すのをやめ、規則にするのが要点である。規則にしておけば、
    次のバージョンの仕様も、他のエージェントの仕様も、同じ基準でレビューできる。
    """
    found: list[str] = []
    if not spec.runner.get("read_only"):
        found.append("F1")
    if spec.exec_limits.get("max_calls") is None \
            or spec.exec_limits.get("timeout", 0.0) > MAX_EXEC_TIMEOUT:
        found.append("F2")
    if set(spec.tools) - set(TASK_NEEDS):
        found.append("F3")
    if [t for t in UNTRUSTED_SOURCES if t in spec.tools and t not in spec.untrusted]:
        found.append("F4")
    if spec.approval.get("granularity") != "operation":
        found.append("F5")
    if spec.approval.get("threshold_yen") != POLICY_THRESHOLD:
        found.append("F6")
    if spec.retry.get("judge") != "kind_and_idempotency":
        found.append("F7")
    if spec.completion != "effect_check":
        found.append("F8")
    if spec.inspector not in SOUND_INSPECTORS:
        found.append("F9")
    if not spec.approval.get("audit_count"):
        found.append("F10")
    return found


def extra_tools(spec: Spec) -> list[str]:
    """タスクに要らないのに渡しているツール（F3 の中身）。"""
    return [t for t in spec.tools if t not in TASK_NEEDS]


# ---------------------------------------------------------------------------
# 3. 塞ぐ層の選び方（問題4でここを自分で書く）
# ---------------------------------------------------------------------------
# 上にあるほど先に選ぶ。並び順の根拠は「測れるか」と「何に依存するか」である。
PRIORITY = (
    "権限制限",       # 渡さなければ呼べない。存在しないものは破れない
    "隔離の境界",     # compose の指定。破れていないことをプローブで示せる
    "出力検査",       # 実行の直前にコードで止める
    "記録との照合",   # 外部の記録と突き合わせる。嘘と欠落を見抜く
    "再試行の判断",   # 失敗の種類と冪等性で決める。副作用を増やさない
    "人間承認",       # 決定的に止まるが、承認者の注意力に依存する
    "入力検査",       # 気づけるが止まらない
    "構造分離",       # 囲めるが、従うかどうかは保証できない
    "プロンプト",     # 測れない。**最後まで選ばない**
)

LAYER_TRAITS: dict[str, tuple[str, str, str]] = {
    "権限制限": ("測れる", "止まる", "許可リストの設計"),
    "隔離の境界": ("測れる", "止まる", "compose の指定"),
    "出力検査": ("測れる", "止まる", "出口の列挙"),
    "記録との照合": ("測れる", "嘘を見抜く", "外部の記録"),
    "再試行の判断": ("測れる", "増やさない", "失敗の分類と冪等性"),
    "人間承認": ("測れる", "止まる", "承認者の注意力"),
    "入力検査": ("測れる", "止まらない", "既知の言い回し"),
    "構造分離": ("測れる", "従うかは不明", "モデルの素直さ"),
    "プロンプト": ("測れない", "測れない", "モデルの素直さ"),
}

# 各穴を塞げる層の候補。**候補が複数ある穴が5件ある**のがこの章の主題
CANDIDATES: dict[str, tuple[str, ...]] = {
    "F1": ("隔離の境界", "入力検査"),
    "F2": ("隔離の境界", "人間承認"),
    "F3": ("権限制限", "出力検査", "人間承認", "プロンプト"),
    "F4": ("権限制限", "入力検査", "構造分離"),
    "F5": ("人間承認", "プロンプト"),
    "F6": ("人間承認",),
    "F7": ("再試行の判断", "人間承認"),
    "F8": ("記録との照合", "人間承認"),
    "F9": ("出力検査", "人間承認", "プロンプト"),
    "F10": ("記録との照合", "人間承認"),
}


def pick_layer(candidates: tuple[str, ...]) -> str:
    """候補の中から、優先順位がいちばん高い層を返す。"""
    unknown = [c for c in candidates if c not in PRIORITY]
    if unknown:
        raise ValueError(f"知らない層が指定されています: {unknown}")
    if not candidates:
        raise ValueError("候補が空です。塞げないなら残余リスクとして扱ってください。")
    return min(candidates, key=PRIORITY.index)


def plan() -> dict[str, str]:
    """穴 → 塞ぐ層の割り当て。レビュー報告書の本体になる。"""
    return {fid: pick_layer(CANDIDATES[fid]) for fid in CATALOG}


# ---------------------------------------------------------------------------
# 4. 残余リスク（塞げないもの）
# ---------------------------------------------------------------------------
RESIDUAL: dict[str, dict] = {
    "R1": {"リスク": "承認者が中身を読まずに押す",
           "塞ぐ層": None,
           "検知": "承認から実行までの時間と、却下率を月次で見る（0% は読んでいない兆候）"},
    "R2": {"リスク": "知らない出口（隔離実行の生成ファイル）から出る",
           "塞ぐ層": None,
           "検知": "出口の一覧をツール追加のたびに更新し、検査していない出口の数を数える"},
    "R3": {"リスク": "言い換えた注入が入力検査を抜ける",
           "塞ぐ層": None,
           "検知": "入力検査の検出数と、権限制限・出力検査が止めた件数を別々に数える"},
    "R4": {"リスク": "社外アドレスへ送信される",
           "塞ぐ層": "出力検査",
           "検知": "—"},
    "R5": {"リスク": "冪等でない申請が二重に登録される",
           "塞ぐ層": "再試行の判断",
           "検知": "—"},
}


def residual_ids() -> list[str]:
    """本当に残るリスク（塞ぐ層が無いもの）だけを返す。"""
    return sorted(rid for rid, row in RESIDUAL.items() if row["塞ぐ層"] is None)


# ---------------------------------------------------------------------------
# 表示
# ---------------------------------------------------------------------------
def render_audit(spec: Spec) -> str:
    found = audit_spec(spec)
    lines = [f"=== 仕様監査: {spec.name}（{len(found)} 件）===",
             "ID | 症状 | 領域 | 出典 | 塞ぐ層"]
    for fid in found:
        row = CATALOG[fid]
        lines.append(f"{fid} | {row['症状']} | {row['領域']} | {row['出典']} | "
                     f"{pick_layer(CANDIDATES[fid])}")
    if not found:
        lines.append("（穴は検出されませんでした）")
    return "\n".join(lines)


def render_priority() -> str:
    lines = ["=== 層の優先順位（測れる層を先に選ぶ）===",
             "順 | 層 | 測れるか | 止まるか | 何に依存するか"]
    for index, layer in enumerate(PRIORITY, start=1):
        measurable, stops, depends = LAYER_TRAITS[layer]
        lines.append(f"{index} | {layer} | {measurable} | {stops} | {depends}")
    return "\n".join(lines)


def render_choices() -> str:
    lines = ["=== 候補が複数あるとき、どれを選ぶか ===",
             "ID | 候補 | 選ぶ層 | 選ばなかった層が依存するもの"]
    for fid, candidates in CANDIDATES.items():
        chosen = pick_layer(candidates)
        rest = [c for c in candidates if c != chosen]
        why = "候補が1つ" if not rest else "／".join(
            f"{c}={LAYER_TRAITS[c][2]}" for c in rest)
        lines.append(f"{fid} | {'・'.join(candidates)} | {chosen} | {why}")
    return "\n".join(lines)


def render_residual() -> str:
    lines = ["=== 残余リスク（塞げないもの）===", "ID | リスク | 検知の方法"]
    for rid in residual_ids():
        row = RESIDUAL[rid]
        lines.append(f"{rid} | {row['リスク']} | {row['検知']}")
    closed = [f"{rid}={RESIDUAL[rid]['塞ぐ層']}"
              for rid in RESIDUAL if rid not in residual_ids()]
    lines.append(f"（塞げるので残余リスクに入れないもの: {', '.join(closed)}）")
    return "\n".join(lines)


def main() -> None:
    print(render_audit(AS_IS))
    print()
    print(render_audit(TO_BE))
    print()
    print(render_priority())
    print()
    print(render_choices())
    print()
    print(render_residual())


if __name__ == "__main__":
    main()
