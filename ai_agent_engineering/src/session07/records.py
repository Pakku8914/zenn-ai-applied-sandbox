#!/usr/bin/env python3
"""記録（レコード）の正規化 — メモリに入れる単位をそろえる。

セッション4で「ツール結果のトークン量を設計する」を扱った。その続きとして、
**メモリに入れる前にツール結果を固定幅の記録に正規化する**。

  1記録 = `[種別] ` (5文字) + 本文 (28文字) = 33文字 = 近似11トークン

固定幅にする理由は3つある。

  - 圧縮の効果を「記録数」で数えられる（近似トークン数 = 記録数 × 11）
  - 何が落ちたかを記録単位で照合できる（保持率を機械判定できる）
  - 数値が決定的に再現する（本文に書いた数値がいつ実行しても一致する）

実務では可変長なので、絶対値ではなく**比率と保持率**を見ること。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentkit.memory import approx_tokens  # noqa: E402

# 種別。メモリの中で「これは何か」を機械が読める形で持つための札
KINDS = ("指示", "制約", "決定", "思考", "規程", "ログ", "一覧", "結果", "要約", "参照")

# 圧縮しても必ず残す種別（選択的保持）。制約と決定事項は落とすと結論が変わる
KEEP_KINDS = ("指示", "制約", "決定")

BODY_WIDTH = 28          # 本文の幅
PAD = "・"               # 幅をそろえるための詰め物（目で桁がそろう）
PREFIX_WIDTH = 5         # "[制約] " の長さ
RECORD_WIDTH = PREFIX_WIDTH + BODY_WIDTH   # 33
TOKENS_PER_RECORD = approx_tokens("x" * RECORD_WIDTH)   # 33 // 3 = 11


def record(kind: str, body: str) -> str:
    """1件の記録を作る。幅は必ず 33 文字になる。"""
    if kind not in KINDS:
        raise ValueError(f"未知の種別です: {kind!r}。使える種別: {', '.join(KINDS)}")
    text = body[:BODY_WIDTH].ljust(BODY_WIDTH, PAD)
    return f"[{kind}] {text}"


def kind_of(rec: str) -> str:
    """記録の種別を取り出す。"""
    return rec[1:3]


def body_of(rec: str) -> str:
    """記録の本文を取り出す（詰め物を落とす）。"""
    return rec[PREFIX_WIDTH:].rstrip(PAD)


def tokens(records: list[str]) -> int:
    """近似トークン数（比較用）。固定幅なので記録数 × 11 で決まる。"""
    return len(records) * TOKENS_PER_RECORD


def to_records(text: str) -> list[str]:
    """ツール結果の文字列を記録の並びに戻す（1行1記録）。"""
    return [line for line in text.split("\n") if line]


def group_key(rec: str) -> str:
    """同じ出典のかたまり（グループ）を見分ける鍵。

    監査ログの本文は `07-031 ...` のように「月-行番号」で始まる。この2文字を
    出典の鍵として使うと、ログ1回ぶんを1つのかたまりとして扱える。
    要約に置き換えるのはこのかたまり単位である。
    """
    body = rec[PREFIX_WIDTH:]
    if len(body) > 3 and body[2] == "-" and body[:2].isdigit():
        return body[:2]
    return ""


def constraints(records: list[str]) -> list[str]:
    """制約の記録だけを取り出す（種別タグ方式）。"""
    return [r for r in records if kind_of(r) == "制約"]


def retention(before: list[str], after: list[str]) -> dict:
    """圧縮の前後で制約が何件残ったか（保持率）。"""
    kept = [r for r in constraints(before) if r in after]
    total = constraints(before)
    lost = [r for r in total if r not in after]
    return {
        "制約の総数": len(total),
        "残った制約": len(kept),
        "保持率": round(len(kept) / len(total), 3) if total else 1.0,
        "落ちた制約": [body_of(r) for r in lost],
    }


def breakdown(records: list[str]) -> list[dict]:
    """メモリの内訳（どの要素が支配的かを見る）。"""
    buckets = {"指示・制約": ("指示", "制約", "決定"),
               "思考": ("思考",),
               "ツール結果": ("規程", "ログ", "一覧", "結果", "要約", "参照")}
    total = len(records) or 1
    rows = []
    for label, kinds in buckets.items():
        n = sum(1 for r in records if kind_of(r) in kinds)
        rows.append({"要素": label, "記録数": n, "近似トークン": n * TOKENS_PER_RECORD,
                     "割合": round(n / total * 100, 1)})
    return rows


def render_breakdown(records: list[str]) -> str:
    lines = [f"記録数={len(records)} 近似トークン={tokens(records)}",
             f"{'要素':<12}{'記録数':>7}{'近似トークン':>13}{'割合':>8}"]
    for row in breakdown(records):
        lines.append(f"{row['要素']:<12}{row['記録数']:>7}"
                     f"{row['近似トークン']:>13}{row['割合']:>7}%")
    return "\n".join(lines)


if __name__ == "__main__":
    sample = [record("指示", "2026年7月と8月の監査ログを確認する。"),
              record("制約", "5万円以上は必ず事前承認が必要。"),
              record("ログ", "07-031 必ず注記のある申請も対象に。")]
    for r in sample:
        print(f"{len(r):>3}文字 近似{TOKENS_PER_RECORD}トークン  {r}")
    print()
    print(render_breakdown(sample))
