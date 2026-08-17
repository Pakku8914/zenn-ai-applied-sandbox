"""取り込み時の正規化・ボイラープレート除去・重複判定。

ここでの正規化は「保存する本文」に対するもので、構造（改行・大文字小文字）を保つ。
索引を作るときの正規化（ragkit.tokenize_ja.normalize）は目的が違い、
小文字化や空白の畳み込みまで行う。2つを混同しないこと。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

# --- 検出用の文字クラス -----------------------------------------------------
# 目で見て判別できない文字は、必ずコードポイントで書く（ソースに貼ると事故る）。
ZERO_WIDTH_SPACE = chr(0x200B)  # ゼロ幅スペース
REPLACEMENT_CHAR = chr(0xFFFD)  # 置換文字（文字化けの跡）
# ゼロ幅スペース・接合子・方向制御・行区切り・BOM
_INVISIBLE = "".join(chr(c) for c in (0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x2028, 0x2029, 0xFEFF))

# 制御文字（改行 \n・タブ \t・改ページ \f は別に処理するので除く）
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f]")
# 見えない文字。画面に出ないのに検索の一致を壊す
INVISIBLE_RE = re.compile(f"[{_INVISIBLE}]")
# 置換文字（U+FFFD）＝ 文字化けの跡。これは消さずに残して人に回す
REPLACEMENT_RE = re.compile(f"[{REPLACEMENT_CHAR}]")
# 全角の英数字（Ａ-Ｚ ａ-ｚ ０-９）
FULLWIDTH_RE = re.compile(r"[Ａ-Ｚａ-ｚ０-９]")
# 丸数字・囲み文字（① ㈱ ㎡ など）
ENCLOSED_RE = re.compile(r"[①-⓿㈀-㋿㌀-㏿]")
# ルビ（抽出器が「漢字(かな)」の形で出したもの）。NFKC のあとに適用する
RUBY_RE = re.compile(r"([一-龥々ヶ]+)\(([ぁ-んー]{2,})\)")
# 3行以上の連続改行（＝空行が2行以上続く）
EXCESS_BLANK_RE = re.compile(r"\n{3,}")
# 見出し・箇条書き・表の行（前後の行とつないではいけない）
NO_JOIN_HEAD_RE = re.compile(r"^([0-9]+[.)]|[-*・#|]|第[0-9]+[条章])")

# --- ボイラープレート（本文ではない定型行）----------------------------------
# NFKC と行末トリムを済ませた「行」に対して当てる。パターンは仕様書に列挙し、
# 増やすときは必ず「消しすぎていないか」を点検してから入れる。
BOILERPLATE_PATTERNS = [
    r"^みなと商事株式会社 社外秘$",           # PDF のフッター
    r"^- \d+ -$",                             # PDF のページ番号
    r"^\d+ / \d+$",                           # PDF のページ番号（別形式）
    r"^みなと商事 社内ポータル$",             # HTML のヘッダー
    r"^ホーム > .*$",                         # パンくず
    r"^\[ホーム\].*$",                        # グローバルナビ
    r"^このページは.+が管理しています。.*$",   # HTML のフッター
    r"^\(c\) \d{4} Minato Trading Co\., Ltd\..*$",
    r"^関連リンク: .*$",
]
BOILERPLATE_RE = re.compile("|".join(BOILERPLATE_PATTERNS))


# --- 正規化の各段 -----------------------------------------------------------
def strip_invisible(text: str) -> str:
    """改行コードをそろえ、制御文字と見えない文字を落とす。

    改ページ（\\f）は改行に置き換える。置換文字（U+FFFD）は残す
    （消すと「文字化けが起きた証拠」まで消えてしまうため）。
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")
    text = CONTROL_RE.sub("", text)
    return INVISIBLE_RE.sub("", text)


def to_nfkc(text: str) -> str:
    """互換文字を正規形に寄せる（全角英数→半角、半角カナ→全角カナ など）。

    副作用として ①→1、㈱→(株)、㎡→m2、～→~ のように「見た目の意味」が消える。
    どこまで許すかは仕様書に書いて固定する。
    """
    return unicodedata.normalize("NFKC", text)


def trim_lines(text: str) -> str:
    """行末の空白を落とす（NFKC 後なので全角スペースも半角空白になっている）。"""
    return "\n".join(line.rstrip() for line in text.split("\n"))


def drop_boilerplate(text: str) -> str:
    """定型のヘッダー・フッター・ナビの行を落とす。"""
    return "\n".join(line for line in text.split("\n") if not BOILERPLATE_RE.match(line.strip()))


def strip_ruby(text: str) -> str:
    """「漢字(かな)」形式のルビを落とす。NFKC のあとに当てること。"""
    return RUBY_RE.sub(r"\1", text)


def collapse_blank_lines(text: str) -> str:
    """空行が2行以上続く箇所を1行にそろえ、前後の空白を落とす。"""
    return EXCESS_BLANK_RE.sub("\n\n", text).strip()


def clean_text(text: str) -> str:
    """取り込み時の正規化パイプライン（順序に意味がある）。

    1. 見えない文字を落とす → 2. NFKC → 3. 行末トリム
    → 4. ボイラープレート除去 → 5. ルビ除去 → 6. 空行の畳み込み

    NFKC を先に済ませると、ボイラープレートのパターンを半角の1種類だけ書けばよい。
    逆にすると全角版・半角版の2種類を書く羽目になる。
    """
    text = strip_invisible(text)
    text = to_nfkc(text)
    text = trim_lines(text)
    text = drop_boilerplate(text)
    text = strip_ruby(text)
    return collapse_blank_lines(text)


def join_wrapped_lines(text: str) -> str:
    """PDF のハードラップ（見た目の折り返し）を連結する。

    既定のパイプラインには入れていない。箇条書き・表・見出しを壊すことがあり、
    「効く文書」と「壊れる文書」がはっきり分かれるためである。
    使うときは source_format や文書の種別で対象を絞ること。
    """
    out: list[str] = []
    for line in text.split("\n"):
        joinable = (
            out
            and out[-1]
            and line
            and not NO_JOIN_HEAD_RE.match(line)
            and not NO_JOIN_HEAD_RE.match(out[-1])
            and not re.search(r"[。．：:；;]$", out[-1])
        )
        if joinable:
            out[-1] += line
        else:
            out.append(line)
    return "\n".join(out)


# --- 同定と重複判定 ---------------------------------------------------------
def content_hash(text: str) -> str:
    """本文の指紋。完全重複の検出と、差分取り込みの変更検出に使う。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def shingles(text: str, n: int = 5) -> set[str]:
    """空白を除いた文字列の n-gram 集合。近重複の判定に使う。"""
    s = re.sub(r"\s+", "", text)
    if len(s) <= n:
        return {s} if s else set()
    return {s[i : i + n] for i in range(len(s) - n + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    """2つの集合の重なりの割合（0.0〜1.0）。"""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def is_order_suspect(text: str, alt: str | None) -> bool:
    """順序崩れの疑いを判定する。

    2つの抽出器の出力を比べ、「使われている文字は同じなのに並びが違う」なら、
    どちらかがレイアウトを読み違えている。中身が違う（＝片方が欠けている）
    場合はこの判定では拾えないので、文字数の差で別に点検する。
    """
    if alt is None:
        return False
    a = re.sub(r"\s+", "", clean_text(text))
    b = re.sub(r"\s+", "", clean_text(alt))
    return a != b and sorted(a) == sorted(b)


# --- 点検用の述語 -----------------------------------------------------------
def is_effectively_empty(text: str, min_chars: int = 10) -> bool:
    return len(text.strip()) < min_chars


def has_boilerplate(text: str) -> bool:
    return any(BOILERPLATE_RE.match(line.strip()) for line in text.split("\n"))


def has_fullwidth_or_enclosed(text: str) -> bool:
    return bool(FULLWIDTH_RE.search(text) or ENCLOSED_RE.search(text))


def has_excess_blank_lines(text: str) -> bool:
    return bool(EXCESS_BLANK_RE.search(text))


def has_broken_chars(text: str) -> bool:
    """文字化けの跡（置換文字）と制御文字。取り込みで直してはいけない事故。"""
    return bool(REPLACEMENT_RE.search(text) or CONTROL_RE.search(text))
