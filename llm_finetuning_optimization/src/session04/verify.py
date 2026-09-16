#!/usr/bin/env python3
"""セッション4の自己検証：chat template・loss マスク・切り捨ての向き・パディング・トークン膨張。

モデルの重みは読み込まない（トークナイザだけを使う）ので数秒で終わる。
1つでも検証に失敗したら非0で終了する。

  docker compose exec app python src/session04/verify.py

このスクリプトの中心は「素朴な切り捨て」と「回答を残す切り捨て」を両方走らせて、
前者ではマスク率が 1.000（＝学習対象が1トークンも残らない）になることを示す部分。
"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ftkit.data import build_prompt, build_target, load  # noqa: E402
from ftkit.models import FAST_MODEL, JA_MODEL, load_tokenizer  # noqa: E402
from ftkit.tokenize import (  # noqa: E402
    IGNORE_INDEX,
    collate,
    encode_example,
    masked_ratio,
    token_report,
)

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def section(title: str) -> None:
    print(f"\n--- {title} ---")


def prompt_text_of(tokenizer, example, task: str) -> str:
    """学習時・推論時の両方で使うプロンプト（chat template 適用後）。"""
    return tokenizer.apply_chat_template(
        [{"role": "user", "content": build_prompt(example, task)}],
        tokenize=False, add_generation_prompt=True)


def prompt_ids_of(tokenizer, example, task: str) -> list[int]:
    return tokenizer(prompt_text_of(tokenizer, example, task),
                     add_special_tokens=False)["input_ids"]


def answer_ids_of(tokenizer, example, task: str) -> list[int]:
    text = build_target(example, task) + (tokenizer.eos_token or "")
    return tokenizer(text, add_special_tokens=False)["input_ids"]


def encode_naive(tokenizer, example, task: str, max_length: int) -> dict:
    """素朴な切り捨て（アンチパターン）。

    連結してから前から max_length 個取る。プロンプトが長いと回答が丸ごと消え、
    labels が全部 IGNORE_INDEX になる（＝損失が計算できない）。
    """
    prompt_ids = prompt_ids_of(tokenizer, example, task)
    answer_ids = answer_ids_of(tokenizer, example, task)
    input_ids = (prompt_ids + answer_ids)[:max_length]
    labels = ([IGNORE_INDEX] * len(prompt_ids) + answer_ids)[:max_length]
    return {"input_ids": input_ids, "labels": labels,
            "attention_mask": [1] * len(input_ids)}


tok_fast = load_tokenizer(FAST_MODEL)
tok_ja = load_tokenizer(JA_MODEL)
train = load("train")
ex = train[0]
print(f"検証に使う1件: {ex.id} / 区分 {ex.category}")

# --- 1. chat template ------------------------------------------------------
section("chat template（学習時と推論時で同じ形にする）")

messages = [{"role": "user", "content": build_prompt(ex, "classify")}]
with_gen = tok_fast.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
without_gen = tok_fast.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
diff = with_gen[len(without_gen):] if with_gen.startswith(without_gen) else "(前半が一致しない)"

check("トークナイザが chat template を持っている", tok_fast.chat_template is not None)
check("add_generation_prompt=True の方が長い", len(with_gen) > len(without_gen),
      f"追加された部分 {diff!r}")
check("add_generation_prompt=True の末尾が応答の開始位置になっている",
      with_gen.rstrip().endswith("assistant"))

# 学習時の入力の前半は、推論時に渡すプロンプトと1トークンも違ってはいけない
enc_format = encode_example(tok_fast, ex, "format", max_length=320)
infer_ids = prompt_ids_of(tok_fast, ex, "format")
check("学習時の入力の前半が推論時のプロンプトと完全に一致する",
      enc_format["input_ids"][:len(infer_ids)] == infer_ids,
      f"{len(infer_ids)} トークンが一致")

# --- 2. loss マスク ---------------------------------------------------------
section("loss マスク（プロンプトを損失から外す）")

enc = encode_example(tok_fast, ex, "classify", max_length=320)
ans_cls = answer_ids_of(tok_fast, ex, "classify")
n = len(enc["input_ids"])
ratio = masked_ratio(enc)

check("input_ids・labels・attention_mask の長さが揃っている",
      len(enc["labels"]) == n and len(enc["attention_mask"]) == n, f"{n} トークン")
check("labels の末尾が回答トークンと完全に一致する",
      enc["labels"][-len(ans_cls):] == ans_cls)
check("labels の前半はすべて IGNORE_INDEX(-100)",
      set(enc["labels"][:n - len(ans_cls)]) == {IGNORE_INDEX})
check("学習対象が残っている（マスク率が 1.000 未満）", ratio < 1.0,
      f"マスク率 {ratio:.3f}")
check("分類タスクのマスク率は 0.9 を超える（学習対象は回答だけ）", ratio > 0.9,
      f"{n} トークン中 {n - len(ans_cls)} をマスク")

# --- 3. 切り捨ての向き（この章の中心）--------------------------------------
section("切り捨ての向き（回答を残す／回答が消える）")

ans_fmt = answer_ids_of(tok_fast, ex, "format")
prompt_fmt = prompt_ids_of(tok_fast, ex, "format")
budget = 32                      # プロンプトに残す予算
tight = len(ans_fmt) + budget    # 回答は入るがプロンプトは入りきらない長さ

good = encode_example(tok_fast, ex, "format", max_length=tight)
check("正しい切り捨て：長さが max_length にぴったり収まる",
      len(good["input_ids"]) == tight, f"max_length={tight}")
check("正しい切り捨て：回答トークンが1つも欠けていない",
      good["labels"][-len(ans_fmt):] == ans_fmt)
check("正しい切り捨て：削られたのはプロンプトの左側",
      good["input_ids"][:budget] == prompt_fmt[-budget:])
check("正しい切り捨て：切り捨てた量が記録される",
      good["truncated_prompt_tokens"] == len(prompt_fmt) - budget,
      f"{good['truncated_prompt_tokens']} トークンを左から削った")
check("正しい切り捨て：マスク率は 1.000 にならない", masked_ratio(good) < 1.0,
      f"マスク率 {masked_ratio(good):.3f}")

naive = encode_naive(tok_fast, ex, "format", max_length=tight)
naive_ratio = masked_ratio(naive)
check("素朴な切り捨て：回答が丸ごと消えてマスク率が 1.000 になる",
      naive_ratio == 1.0, f"マスク率 {naive_ratio:.3f}")
check("素朴な切り捨て：学習対象のトークンが1つも残らない",
      all(x == IGNORE_INDEX for x in naive["labels"]),
      "loss は nan になり、勾配はすべて 0 になる")

try:
    encode_example(tok_fast, ex, "format", max_length=len(ans_fmt))
    raised = False
except ValueError:
    raised = True
check("回答だけで使い切る max_length は ValueError で止まる", raised,
      f"max_length={len(ans_fmt)} を渡した")

# --- 4. パディングと attention_mask ----------------------------------------
section("パディングと attention_mask の整合")

batch = [encode_example(tok_fast, e, "format", max_length=320) for e in train[:4]]
lengths = [len(row["input_ids"]) for row in batch]
padded = collate(batch, tok_fast.pad_token_id)
max_len = max(lengths)

check("pad_token_id が設定されている", tok_fast.pad_token_id is not None,
      f"pad_token={tok_fast.pad_token!r}")
check("3つのテンソルが同じ形になる",
      padded["input_ids"].shape == padded["labels"].shape == padded["attention_mask"].shape,
      f"形 {tuple(padded['input_ids'].shape)} / 元の長さ {lengths}")
check("パディング後の長さはバッチ内の最長に揃う",
      padded["input_ids"].shape[1] == max_len, f"最長 {max_len} トークン")
check("attention_mask はパディング位置だけ 0 になっている",
      all(row[:length] == [1] * length and row[length:] == [0] * (max_len - length)
          for row, length in zip(padded["attention_mask"].tolist(), lengths)))
check("パディング位置の labels は IGNORE_INDEX で埋まっている",
      all(label == IGNORE_INDEX
          for labels, length in zip(padded["labels"].tolist(), lengths)
          for label in labels[length:]))
check("attention_mask=0 の位置はすべて損失から外れている",
      all(label == IGNORE_INDEX
          for mask_row, label_row in zip(padded["attention_mask"].tolist(),
                                         padded["labels"].tolist())
          for mask, label in zip(mask_row, label_row) if mask == 0))

# --- 5. 日本語のトークン膨張 ------------------------------------------------
section("トークナイザの比較（同じ日本語が何トークンになるか）")

sample = "有給休暇の申請はいつまでですか"
pieces_count: dict[str, int] = {}
for name, tokenizer in ((FAST_MODEL, tok_fast), (JA_MODEL, tok_ja)):
    ids = tokenizer(sample, add_special_tokens=False)["input_ids"]
    pieces_count[name] = len(ids)
    print(f"   {name}")
    print(f"     {len(ids)} トークン: {' | '.join(tokenizer.decode([i]) for i in ids)}")

check("英語中心のトークナイザは同じ日本語を2倍以上のトークンに割る",
      pieces_count[FAST_MODEL] >= pieces_count[JA_MODEL] * 2,
      f"{pieces_count[FAST_MODEL]} 対 {pieces_count[JA_MODEL]} トークン"
      f"（{len(sample)} 文字）")

totals: dict[str, float] = {}
for name, tokenizer in ((FAST_MODEL, tok_fast), (JA_MODEL, tok_ja)):
    reports = [token_report(tokenizer, e, "format") for e in train[:100]]
    prompt = statistics.mean(r["prompt_tokens"] for r in reports)
    answer = statistics.mean(r["answer_tokens"] for r in reports)
    cpt = statistics.mean(r["chars_per_token"] for r in reports)
    totals[name] = prompt + answer
    print(f"   {name}: 指示+質問 {prompt:.1f} / 回答 {answer:.1f} / "
          f"合計 {prompt + answer:.1f} トークン / {cpt:.2f} 文字perトークン / 語彙 {len(tokenizer):,}")

check("同じデータの合計トークン数が2倍以上違う",
      totals[FAST_MODEL] >= totals[JA_MODEL] * 2,
      f"{totals[FAST_MODEL]:.1f} 対 {totals[JA_MODEL]:.1f} トークン"
      f"（{totals[FAST_MODEL] / totals[JA_MODEL]:.2f}倍）")

worst = max(len(prompt_ids_of(tok_fast, e, "format")) + len(answer_ids_of(tok_fast, e, "format"))
            for e in train[:100])
check("既定の max_length=320 が最長の入力を収容できる", worst <= 320,
      f"最長 {worst} トークン")
check("既定の max_length=192 では膨張するトークナイザで切り捨てが起きる", worst > 192,
      f"最長 {worst} トークン > 192（回答を残す切り捨てが必要になる）")

# 「max_length を小さくすると全件で回答が消える」は、プロンプト長の**最小値**が
# その max_length を超えていて初めて言い切れる。平均や最長からは言えない。
print("\n--- max_length を絞ったときに素朴な切り捨てが回答を消す件数 ---")
for task in ("classify", "format"):
    plens = [len(prompt_ids_of(tok_fast, e, task)) for e in train]
    print(f"  {task}: プロンプト長 最小 {min(plens)} / 平均 {sum(plens)/len(plens):.1f} / "
          f"最大 {max(plens)}（n={len(plens)}）")
    for cap in (128, 96):
        over = sum(1 for x in plens if x >= cap)
        check(f"{task} で max_length={cap} だとプロンプトだけで枠を使い切る件数を数えられる",
              0 <= over <= len(plens), f"{over}/{len(plens)} 件")
plens_classify = [len(prompt_ids_of(tok_fast, e, "classify")) for e in train]
check("classify では max_length=128 のとき全件でプロンプトが枠を超える（最小値で言い切れる）",
      min(plens_classify) >= 128,
      f"プロンプト長の最小 {min(plens_classify)} >= 128 なので 720/720 件")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション4の検証はすべて成功しました。")
