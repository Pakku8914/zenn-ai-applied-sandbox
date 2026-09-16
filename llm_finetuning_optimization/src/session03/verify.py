#!/usr/bin/env python3
"""セッション3・4の自己検証：データセットとトークナイザの前提。

モデルの重みを読まないので数秒で終わる（トークナイザだけを使う）。
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ftkit.data import CATEGORIES, load, load_preference  # noqa: E402
from ftkit.models import FAST_MODEL, JA_MODEL, load_tokenizer  # noqa: E402
from ftkit.tokenize import token_report  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


train, valid, test = load("train"), load("valid"), load("test")
pref = load_preference()

# --- 分割の健全性 -----------------------------------------------------------
check("件数の合計が 900", len(train) + len(valid) + len(test) == 900,
      f"{len(train)}+{len(valid)}+{len(test)}")
check("id が重複していない",
      len({e.id for e in train + valid + test}) == 900)
check("すべての区分が train に含まれる",
      {e.category for e in train} == set(CATEGORIES))
counts = Counter(e.category for e in train)
check("区分の偏りが小さい", max(counts.values()) - min(counts.values()) <= 20,
      f"最多 {max(counts.values())} / 最少 {min(counts.values())}")

# --- 汚染（leakage）の検出：ランダム分割の弱点 -------------------------------
# 質問の「型」（言い回しの核）が train と test にまたがっていないかを見る。
# 素朴なランダム分割では必ずまたがる。これに気づくのがセッション3の主眼。
def core(question: str) -> str:
    """接頭・接尾を落とした核の部分を取り出す（簡易）。"""
    for prefix in ("お世話になります。", "恐れ入りますが、", "初めて手続きします。",
                   "急ぎで確認したいのですが、"):
        question = question.replace(prefix, "")
    for suffix in ("教えてください。", "よろしくお願いします。", "ご確認をお願いします。",
                   "至急お願いします。"):
        question = question.replace(suffix, "")
    return question


train_cores = {core(e.question) for e in train}
test_cores = {core(e.question) for e in test}
overlap = train_cores & test_cores
check("【意図的な欠陥】言い回しの型が train と test にまたがっている",
      len(overlap) > 0,
      f"重複した型 {len(overlap)} / test の型 {len(test_cores)}"
      "（セッション3でこの汚染に気づき、型単位の分割に直す）")

# --- 選好データ -------------------------------------------------------------
check("選好データが 200 件", len(pref) == 200, f"{len(pref)} 件")
check("chosen と rejected が異なる", all(p["chosen"] != p["rejected"] for p in pref))
check("chosen は3行の定型", all(p["chosen"].count("\n") == 2 for p in pref))
check("rejected は定型でない", all(p["rejected"].count("\n") == 0 for p in pref))

# --- トークナイザの比較（日本語のトークン膨張）-------------------------------
reports = {}
for name in (FAST_MODEL, JA_MODEL):
    tokenizer = load_tokenizer(name)
    rows = [token_report(tokenizer, e, "format") for e in train[:50]]
    reports[name] = {
        "prompt": sum(r["prompt_tokens"] for r in rows) / len(rows),
        "answer": sum(r["answer_tokens"] for r in rows) / len(rows),
        "cpt": sum(r["chars_per_token"] for r in rows) / len(rows),
        "vocab": len(tokenizer),
    }
    print(f"   {name}: 指示+質問 {reports[name]['prompt']:.1f} トークン / "
          f"{reports[name]['cpt']:.2f} 文字per トークン / 語彙 {reports[name]['vocab']:,}")

fast, ja = reports[FAST_MODEL], reports[JA_MODEL]
check("英語中心のトークナイザは日本語でトークン数が膨らむ",
      fast["prompt"] > ja["prompt"] * 1.5,
      f"{fast['prompt']:.1f} vs {ja['prompt']:.1f}（{fast['prompt'] / ja['prompt']:.2f}倍）")
check("多言語トークナイザの方が語彙が大きい", ja["vocab"] > fast["vocab"] * 2,
      f"{ja['vocab']:,} vs {fast['vocab']:,}")
check("多言語トークナイザの方が1トークンあたりの文字数が多い",
      ja["cpt"] > fast["cpt"] * 1.5, f"{ja['cpt']:.2f} vs {fast['cpt']:.2f}")

# --- max_length の設計 ------------------------------------------------------
tokenizer = load_tokenizer(FAST_MODEL)
worst = max(token_report(tokenizer, e, "format")["prompt_tokens"]
            + token_report(tokenizer, e, "format")["answer_tokens"] for e in train[:100])
check("既定の max_length=320 が最長の入力を収容できる", worst <= 320,
      f"最長 {worst} トークン")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション3・4の検証はすべて成功しました。")
