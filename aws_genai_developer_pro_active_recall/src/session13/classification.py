#!/usr/bin/env python3
"""セッション13: 情報の格付けで「生成AIに入れてよいか」を先に決める。

匿名化は**二番目の網**です。一番目の網は「入れないこと」。
社内規程（`fixtures/kb_corpus.json` の sec-001「情報の格付けと取り扱い」と
sec-003「生成AI利用ガイドライン」）を、判定できるコードに落とします。

    sec-001: 公開・社内限定・機密・極秘の4段階。機密以上は社外の生成AIへ入力しない
    sec-003: 入力してよいのは公開・社内限定まで。顧客の個人情報は匿名化してから入力

判定の材料は **データの出どころ（種別）** です。本文をスキャンして
「個人情報が入っていそうか」で決めません。検出は漏れるからです。
"""

from __future__ import annotations

from dataclasses import dataclass

# 低い順。この並びがそのまま「厳しさ」の順序になる
LEVELS: tuple[str, ...] = ("公開", "社内限定", "機密", "極秘")

# 生成AIへの入力が許される上限（sec-001）
MAX_LEVEL_FOR_GENAI = "社内限定"

# 格付けが分からないときの既定。**厳しい側に倒す**（フェイルクローズ）
DEFAULT_LEVEL = "機密"

# 格付けの表示は文書の先頭行に書く決まり（sec-001）
MARKING_PREFIX = "格付け:"

# 判定の結果として取り得る3つの経路
SEND = "send"
ANONYMIZE_THEN_SEND = "anonymize_then_send"
BLOCK = "block"


class UnknownLevelError(ValueError):
    """格付け表に無い区分。黙って通さず落とす。"""


def rank(level: str) -> int:
    """格付けを数値にする。大きいほど厳しい。"""
    try:
        return LEVELS.index(level)
    except ValueError as error:  # 表に無い語を「たぶん低い」と扱わない
        raise UnknownLevelError(f"未知の格付けです: {level!r}") from error


# データ種別 → 格付け（社内の格付け表。ここが唯一の真実）
CATALOG: dict[str, str] = {
    "公開済みプレスリリース": "公開",
    "社内FAQ": "社内限定",
    "問い合わせ本文": "社内限定",
    "顧客マスタの抜粋": "機密",
    "人事評価シート": "極秘",
}

# 個人情報を含むと **申告されている** 種別。検出結果ではなく登録内容で決める
PERSONAL_DATA_KINDS = frozenset({"問い合わせ本文", "顧客マスタの抜粋"})


@dataclass(frozen=True)
class Verdict:
    """判定結果。`rule` に根拠の社内規程を必ず持たせる（説明できない拒否を作らない）。"""

    action: str
    level: str
    reason: str
    rule: str

    @property
    def allowed(self) -> bool:
        return self.action != BLOCK

    def describe(self) -> str:
        return f"{self.level}/{self.action}({self.rule})"


def level_of(kind: str) -> str:
    """データ種別から格付けを引く。表に無ければ既定（機密）へ倒す。"""
    return CATALOG.get(kind, DEFAULT_LEVEL)


def parse_marking(text: str) -> str:
    """先頭行の格付け表示を読む。無ければ既定（機密）。

    「書いていないから公開扱い」にすると、表示を忘れた極秘文書が通ります。
    **表示が無いことは、安全である証拠にはなりません。**
    """
    stripped = text.strip()
    first_line = stripped.splitlines()[0].strip() if stripped else ""
    if not first_line.startswith(MARKING_PREFIX):
        return DEFAULT_LEVEL
    value = first_line[len(MARKING_PREFIX) :].strip()
    return value if value in LEVELS else DEFAULT_LEVEL


def judge(level: str, *, personal_data: bool) -> Verdict:
    """この格付けの情報を生成AIに入れてよいか。"""
    if rank(level) > rank(MAX_LEVEL_FOR_GENAI):
        return Verdict(
            BLOCK, level, f"{level}は生成AIへの入力が禁止されています", "sec-001"
        )
    if personal_data:
        return Verdict(
            ANONYMIZE_THEN_SEND, level, "個人情報は匿名化してから入力します", "sec-003"
        )
    return Verdict(SEND, level, f"{level}は入力してよい範囲です", "sec-003")


def judge_kind(kind: str) -> Verdict:
    """データ種別から一気に判定する。格付け表と規程を突き合わせる唯一の窓口。"""
    return judge(level_of(kind), personal_data=kind in PERSONAL_DATA_KINDS)


# 期待表。ポリシーを1文字直したときに、意図しない種別が通り始めたことに気づける
EXPECTED_JUDGEMENTS: tuple[tuple[str, str], ...] = (
    ("公開済みプレスリリース", SEND),
    ("社内FAQ", SEND),
    ("問い合わせ本文", ANONYMIZE_THEN_SEND),
    ("顧客マスタの抜粋", BLOCK),
    ("人事評価シート", BLOCK),
    # 表に無い種別は既定の「機密」になるため拒否される
    ("未登録の新しい帳票", BLOCK),
)


def gate() -> list[str]:
    """期待表と判定を突き合わせるゲート。失敗の一覧を返す（空なら合格）。"""
    failures: list[str] = []
    for kind, expected in EXPECTED_JUDGEMENTS:
        actual = judge_kind(kind).action
        if actual != expected:
            failures.append(f"{kind}: 期待 {expected} / 実際 {actual}")
    return failures


def main() -> None:
    print("=== 格付け表と社内規程の突き合わせ ===")
    for kind, _ in EXPECTED_JUDGEMENTS:
        verdict = judge_kind(kind)
        print(f"{kind} | {verdict.level} | {verdict.action} | {verdict.rule}")
    print()
    print(f"ゲートの失敗: {gate() or 'なし'}")


if __name__ == "__main__":
    main()
