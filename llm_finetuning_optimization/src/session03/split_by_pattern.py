#!/usr/bin/env python3
"""セッション3の演習：汚染（leakage）を数値化し、型単位の分割に作り直す。

  python src/session03/split_by_pattern.py

やること:
  1. いまの分割（ランダム）の汚染を数値化する
  2. 「型を照合するだけの暗記モデル」で汚染の大きさを測る
  3. 型単位に分割し直して data/{train,valid,test}_pattern.jsonl を書き出す
  4. 汚染が消えたことを検証する（1つでも失敗したら非0で終了する）

モデルの重みを読まないので数秒で終わる。素の分割（720/90/90）が前提なので、
入れ替えて遊んだあとは `python tools/make_dataset.py` で戻してから実行する。
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ftkit.data import CATEGORIES, Example, load  # noqa: E402

SEED = 20260815
DATA = Path(__file__).resolve().parents[2] / "data"

# make_dataset.py が質問に付ける接頭・接尾。これを落とすと「型」が残る。
# 本来はデータ生成側と1か所で共有すべき定義（二重管理は必ずずれる）。
PREFIXES = ("お世話になります。", "恐れ入りますが、", "初めて手続きします。",
            "急ぎで確認したいのですが、")
SUFFIXES = ("教えてください。", "よろしくお願いします。", "ご確認をお願いします。",
            "至急お願いします。")

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def core(question: str) -> str:
    """言い回しの「型」を取り出す（接頭・接尾を落とした核の部分）。

    実データではここが一番難しい。本書のデータは接頭・接尾が既知なので
    文字列置換で型が取れるが、現場では近重複の判定（文字 n-gram の類似度など）
    で近いものを束ねることになる。
    """
    for prefix in PREFIXES:
        question = question.replace(prefix, "")
    for suffix in SUFFIXES:
        question = question.replace(suffix, "")
    return question.strip()


def dist(rows: list[Example]) -> str:
    counts = Counter(e.category for e in rows)
    return " / ".join(f"{c} {counts[c]}" for c in CATEGORIES)


def leak(train: list[Example], holdout: list[Example], name: str) -> dict:
    """train と holdout の間の汚染を測る。

    - 型がいくつ重なっているか
    - holdout の何件が train に同じ型を持っているか
    - 「型 → 区分」の対応表を引くだけの暗記モデルで何点取れるか
    """
    train_cores = {core(e.question) for e in train}
    holdout_cores = {core(e.question) for e in holdout}
    hit = sum(1 for e in holdout if core(e.question) in train_cores)
    table = {core(e.question): e.category for e in train}
    correct = sum(1 for e in holdout if table.get(core(e.question)) == e.category)
    accuracy = correct / len(holdout) if holdout else 0.0
    print(f"  train の型 {len(train_cores)} / {name} の型 {len(holdout_cores)} / "
          f"重なる型 {len(train_cores & holdout_cores)}")
    print(f"  {name} {len(holdout)} 件のうち、同じ型が train にある件数: "
          f"{hit}（{hit / len(holdout) * 100:.1f}%）")
    print(f"  型を照合するだけの「暗記モデル」の正解率: {accuracy:.3f}")
    return {"shared": len(train_cores & holdout_cores), "hit": hit,
            "n": len(holdout), "accuracy": accuracy}


def write(name: str, rows: list[Example]) -> Path:
    path = DATA / f"{name}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps({"id": row.id, "question": row.question,
                                "category": row.category, "answer": row.answer},
                               ensure_ascii=False) + "\n")
    return path


train, valid, test = load("train"), load("valid"), load("test")
corpus = train + valid + test

# 型を区分ごとに集める（出現順。あとでソートしてから並べ替える）
cores_by_category: dict[str, list[str]] = {c: [] for c in CATEGORIES}
seen: set[str] = set()
for example in corpus:
    key = core(example.question)
    if key not in seen:
        seen.add(key)
        cores_by_category[example.category].append(key)

per_type = Counter(core(e.question) for e in corpus)
questions = [e.question for e in corpus]

# --- 1. コーパス全体 --------------------------------------------------------
print("=== 1. コーパス全体 ===")
print(f"件数          : {len(corpus)}"
      f"（train {len(train)} / valid {len(valid)} / test {len(test)}）")
print(f"言い回しの型  : {len(per_type)}（区分ごとに {len(per_type) // len(CATEGORIES)} 型"
      f" / 1 型あたり {min(per_type.values())} 件）")
print(f"完全一致の重複: {len(questions) - len(set(questions))} 件")
print(f"区分の分布    : {dist(corpus)}")

# --- 2. いまの分割（ランダム）の汚染 ----------------------------------------
print("\n=== 2. いまの分割（ランダム）の汚染 ===")
random_leak = leak(train, test, "test")
print(f"  区分の分布（train）: {dist(train)}")
print(f"  区分の分布（test）: {dist(test)}")

# --- 3. 型単位の分割 --------------------------------------------------------
print("\n=== 3. 型単位の分割 ===")
rng = random.Random(SEED)
assign: dict[str, str] = {}
for category in CATEGORIES:
    keys = sorted(cores_by_category[category])  # 集合・辞書の反復順序に依存させない
    rng.shuffle(keys)
    assign[keys[0]] = "valid"
    assign[keys[1]] = "test"
    for key in keys[2:]:
        assign[key] = "train"

parts: dict[str, list[Example]] = {"train": [], "valid": [], "test": []}
for example in corpus:
    parts[assign[core(example.question)]].append(example)
for name in parts:
    # 型でまとめたままだとファイルの先頭が1区分に偏る。
    # 評価で先頭 N 件だけ使うことがあるので、書き出す前にシャッフルする。
    random.Random(SEED).shuffle(parts[name])

print(f"  件数: train {len(parts['train'])} / valid {len(parts['valid'])}"
      f" / test {len(parts['test'])}")
pattern_leak = leak(parts["train"], parts["test"], "test")
print(f"  区分の分布（train）: {dist(parts['train'])}")
print(f"  区分の分布（test）: {dist(parts['test'])}")
paths = [write(f"{name}_pattern", rows) for name, rows in parts.items()]
print("  -> " + " / ".join(f"data/{p.name}" for p in paths))

# --- 4. 検証 ----------------------------------------------------------------
print("\n=== 4. 検証 ===")
ok_source = (len(train), len(valid), len(test)) == (720, 90, 90)
check("素のランダム分割が読めている（720/90/90）", ok_source,
      f"{len(train)}/{len(valid)}/{len(test)}" if ok_source
      else f"{len(train)}/{len(valid)}/{len(test)}"
           "（python tools/make_dataset.py で素の分割に戻してください）")
check("言い回しの型が 36（区分ごとに 6）",
      len(per_type) == 36 and all(len(v) == 6 for v in cores_by_category.values()),
      f"{len(per_type)} 型")
check("どの型も同じ件数（25 件）",
      min(per_type.values()) == max(per_type.values()) == 25,
      f"最少 {min(per_type.values())} / 最多 {max(per_type.values())}")
check("完全一致の重複がない", len(questions) == len(set(questions)),
      f"{len(questions) - len(set(questions))} 件")
check("【ランダム分割】test の全件が train に同じ型を持つ",
      random_leak["hit"] == random_leak["n"],
      f"{random_leak['hit']}/{random_leak['n']}")
check("【ランダム分割】型の照合だけで満点が取れる",
      random_leak["accuracy"] == 1.0, f"正解率 {random_leak['accuracy']:.3f}")
check("【型単位分割】件数が 600/150/150",
      (len(parts["train"]), len(parts["valid"]), len(parts["test"])) == (600, 150, 150),
      f"{len(parts['train'])}/{len(parts['valid'])}/{len(parts['test'])}")
check("【型単位分割】train と test で型が重ならない", pattern_leak["shared"] == 0,
      f"重なる型 {pattern_leak['shared']}")
valid_shared = len({core(e.question) for e in parts["train"]}
                   & {core(e.question) for e in parts["valid"]})
check("【型単位分割】train と valid で型が重ならない", valid_shared == 0,
      f"重なる型 {valid_shared}")
check("【型単位分割】型の照合では1件も当たらない", pattern_leak["accuracy"] == 0.0,
      f"正解率 {pattern_leak['accuracy']:.3f}")
check("【型単位分割】どの分割にも6区分すべてが含まれる",
      all({e.category for e in rows} == set(CATEGORIES) for rows in parts.values()))
merged = parts["train"] + parts["valid"] + parts["test"]
check("【型単位分割】件数の合計が 900 で id が重複しない",
      len(merged) == 900 and len({e.id for e in merged}) == 900,
      f"{len(merged)} 件 / id {len({e.id for e in merged})} 種")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\n型単位の分割を data/*_pattern.jsonl に書き出しました。汚染は 0 です。")
