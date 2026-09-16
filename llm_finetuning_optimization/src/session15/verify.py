#!/usr/bin/env python3
"""セッション15の自己検証：出力設計・系列長・バッチを「動かす側」から確かめる。

検証する主張（本文に書いた内容と1対1で対応させる）:
  1. 同じ情報でも出力形式でトークン数が変わる。JSON は括弧・引用符・キー名・
     インデントにトークンを払う（構造に使われた分を数で出す）
  2. `ftkit.tokenize.collate` は右パディングである。学習はそれでよいが、
     **生成のバッチ化には左パディングが必要**（右だと生成開始位置がずれる）
  3. 学習時と推論時でテンプレートがずれると入力トークン列が変わる
  4. KVキャッシュは系列長とバッチサイズに比例する（算術）
  5. 左パディングでバッチ生成すると、1件ずつ生成した結果と一致する（135M で実測）
  6. 出力トークン数とレイテンシはほぼ比例する。入力を1トークン増やす方がずっと安い

1〜4はモデルの重みを読まないので数秒で終わる（4 は config.json だけを読む）。
5・6 は SmolLM2-135M を**1体だけ**読み、終わったら del と gc.collect() で解放する。
**学習は一切しない。**

  python src/session15/verify.py
  SKIP_MODEL=1 python src/session15/verify.py   # 生成を伴う検証（5・6）を飛ばす
"""

from __future__ import annotations

import gc
import json
import os
import sys
import time
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from batch_generate import (  # noqa: E402
    VARIANT_NAMES, answer_fields, format_cost, generate_batch, kv_cache_bytes,
    kv_cache_from_config, n_tokens, pad_batch, prompt_ids, render_cost_table,
    render_variants,
)

from ftkit.data import CLASSIFY_INSTRUCTION, build_prompt, load  # noqa: E402
from ftkit.evaluate import FORMAT_RE  # noqa: E402
from ftkit.models import FAST_MODEL, JA_MODEL, load_tokenizer  # noqa: E402
from ftkit.tokenize import IGNORE_INDEX, collate, encode_example  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def section(title: str) -> None:
    print(f"\n--- {title} ---")


tok_fast = load_tokenizer(FAST_MODEL)
tok_ja = load_tokenizer(JA_MODEL)
test = load("test")

# --- 1. 出力形式のトークン数 -------------------------------------------------
section("1. 同じ情報を別の形で出すとトークン数が変わる（test 90件の平均）")

for model_name, tokenizer in ((FAST_MODEL, tok_fast), (JA_MODEL, tok_ja)):
    cost = format_cost(tokenizer, test)
    print(f"\n{model_name}")
    print(render_cost_table(cost))

    tokens = {name: cost[name]["tokens"] for name in VARIANT_NAMES}
    overhead = {name: cost[name]["overhead"] for name in VARIANT_NAMES}
    label = model_name.split("/")[-1]

    check(f"[{label}] 値だけを並べた表現がいちばん少ない",
          tokens["values_only"] == min(tokens.values()),
          f"{tokens['values_only']:.1f} トークン")
    check(f"[{label}] 値だけの表現でも構造（区切り）に払う分は 0 を下回らない",
          overhead["values_only"] >= 0, f"{overhead['values_only']:.1f} トークン")
    check(f"[{label}] 3行の定型は【】と改行に3トークン以上払っている",
          overhead["three_lines"] >= 3, f"{overhead['three_lines']:.1f} トークン")
    check(f"[{label}] 1行 JSON は括弧・引用符・キー名に5トークン以上払っている",
          overhead["json_compact_ja"] >= 5, f"{overhead['json_compact_ja']:.1f} トークン")
    check(f"[{label}] 整形（改行とインデント）を入れるとさらに増える",
          tokens["json_pretty_ja"] > tokens["json_compact_ja"],
          f"{tokens['json_pretty_ja']:.1f} > {tokens['json_compact_ja']:.1f}")
    check(f"[{label}] キーを増やし説明文を足した JSON がいちばん多い",
          tokens["json_verbose_en"] == max(tokens.values()),
          f"{tokens['json_verbose_en']:.1f} トークン（値だけの "
          f"{tokens['json_verbose_en'] / tokens['values_only']:.1f}倍）")

# 出力形式を変えると評価コードも作り替えになる
variants = render_variants(test[0])
print("\n1件を5通りで表したときのトークン数（SmolLM2-135M のトークナイザ）:")
for name, text in variants.items():
    print(f"  {name:<16} {n_tokens(tok_fast, text):>3} トークン")

check("現行の FORMAT_RE は3行の定型だけを通す", bool(FORMAT_RE.match(variants["three_lines"])))
check("同じ情報の JSON は FORMAT_RE を通らない（判定器を作り替える必要がある）",
      not FORMAT_RE.match(variants["json_compact_ja"])
      and not FORMAT_RE.match(variants["json_pretty_ja"]))
check("JSON は json.loads でパースできる（値の取り出しは機械的）",
      json.loads(variants["json_compact_ja"])["区分"] == answer_fields(test[0])[0])
try:
    json.loads(variants["three_lines"])
    parsed = True
except json.JSONDecodeError:
    parsed = False
check("3行の定型は json.loads では読めない（正規表現でパースする）", not parsed)

# --- 2. パディングの向き ----------------------------------------------------
section("2. 学習は右パディング／生成は左パディング")

# 長さが違う入力を選ぶ（同じ長さだとパディングが起きず、何も確かめられない）
enc_by_length: dict[int, dict] = {}
prompt_by_length: dict[int, object] = {}
for candidate in test[:20]:
    encoded_one = encode_example(tok_fast, candidate, "classify", max_length=320)
    enc_by_length.setdefault(len(encoded_one["input_ids"]), encoded_one)
    prompt_by_length.setdefault(
        len(prompt_ids(tok_fast, build_prompt(candidate, "classify"))), candidate)
enc_distinct = sorted(enc_by_length)
prompt_distinct = sorted(prompt_by_length)
check("学習用の入力長が2種類以上ある（パディングが起きる）", len(enc_distinct) >= 2,
      f"{len(enc_distinct)} 種類")
check("推論用の入力長が3種類以上ある（バッチ生成の検証に使う）", len(prompt_distinct) >= 3,
      f"{len(prompt_distinct)} 種類")

encoded = [enc_by_length[enc_distinct[0]], enc_by_length[enc_distinct[-1]]]
lengths = [len(row["input_ids"]) for row in encoded]
padded = collate(encoded, tok_fast.pad_token_id)
max_len = max(lengths)
ids_short = padded["input_ids"][0].tolist()

check("学習用の collate はバッチ内の最長に揃える", padded["input_ids"].shape[1] == max_len,
      f"長さ {lengths} → {max_len}")
check("collate は右パディング：短い行の末尾がパディングになる",
      ids_short[-1] == tok_fast.pad_token_id
      and ids_short[:lengths[0]] == encoded[0]["input_ids"],
      f"末尾 {max_len - lengths[0]} トークンが pad")
check("学習ではそれで困らない：パディング位置は labels=-100 で損失から外れている",
      all(x == IGNORE_INDEX for x in padded["labels"][0].tolist()[lengths[0]:]))
check("学習ではそれで困らない：attention_mask もパディング位置だけ 0",
      padded["attention_mask"][0].tolist()[lengths[0]:] == [0] * (max_len - lengths[0]))

# 生成に渡すのはプロンプトだけ（回答はまだ無い）
pairs = [prompt_by_length[prompt_distinct[0]], prompt_by_length[prompt_distinct[-1]]]
rows = [prompt_ids(tok_fast, build_prompt(example, "classify")) for example in pairs]
right = pad_batch(rows, tok_fast.pad_token_id, "right")
left = pad_batch(rows, tok_fast.pad_token_id, "left")
pad_len = len(rows[1]) - len(rows[0])

check("生成に渡す入力の末尾は応答の開始位置になっている（add_generation_prompt=True）",
      "assistant" in tok_fast.decode(rows[0][-4:]),
      repr(tok_fast.decode(rows[0][-4:])))
check("右パディング：短い行の最後の位置がパディングになる（生成がパッドの続きから始まる）",
      right["input_ids"][0][-1].item() == tok_fast.pad_token_id
      and right["input_ids"][1][-1].item() == rows[1][-1],
      f"長さ {[len(r) for r in rows]} / {pad_len} トークンぶんずれる")
check("右パディング：最後の実トークンの位置が行ごとに違う（生成開始位置が揃わない）",
      [int(mask.sum()) - 1 for mask in right["attention_mask"]]
      == [len(rows[0]) - 1, len(rows[1]) - 1],
      f"位置 {[int(m.sum()) - 1 for m in right['attention_mask']]}")
check("左パディング：全行の最後の位置が本来の最後のトークンになる（生成開始位置が揃う）",
      all(left["input_ids"][i][-1].item() == rows[i][-1] for i in range(2)))
check("左パディング：トークンの順序は変わらない（パディングを外すと元の列に戻る）",
      left["input_ids"][0].tolist()[pad_len:] == rows[0])
check("左パディング：attention_mask はパディングした先頭だけ 0",
      left["attention_mask"][0].tolist() == [0] * pad_len + [1] * len(rows[0]))

# 実務のレシピ：tokenizer.padding_side="left" が手書きと同じ結果になること
texts = [tok_fast.apply_chat_template(
    [{"role": "user", "content": build_prompt(example, "classify")}],
    tokenize=False, add_generation_prompt=True) for example in pairs]
saved_side = tok_fast.padding_side
tok_fast.padding_side = "left"
recipe = tok_fast(texts, padding=True, add_special_tokens=False, return_tensors="pt")
tok_fast.padding_side = saved_side
check("tokenizer.padding_side='left' のレシピが手書きの左パディングと一致する",
      recipe["input_ids"].tolist() == left["input_ids"].tolist()
      and recipe["attention_mask"].tolist() == left["attention_mask"].tolist(),
      f"形 {tuple(recipe['input_ids'].shape)}")

# --- 3. テンプレートのずれ --------------------------------------------------
section("3. 学習時と推論時でテンプレートがずれると入力が変わる")

example = test[0]
correct = prompt_ids(tok_fast, build_prompt(example, "classify"))
train_input = encode_example(tok_fast, example, "classify", max_length=320)["input_ids"]
check("学習時の入力の前半が、推論時に渡す入力と1トークンも違わない（ftkit は共有している）",
      train_input[:len(correct)] == correct, f"{len(correct)} トークンが一致")


def encode_plain(text: str) -> list[int]:
    return tok_fast(text, add_special_tokens=False)["input_ids"]


def drifted(name: str, ids: list[int]) -> None:
    common = 0
    for a, b in zip(correct, ids):
        if a != b:
            break
        common += 1
    tail = tok_fast.decode(ids[-4:]).replace("\n", "\\n")
    check(f"ずれ: {name}", ids != correct,
          f"長さ {len(correct)}→{len(ids)} / 一致する先頭 {common} トークン / 末尾 {tail!r}")


drifted("推論時に add_generation_prompt=False にした（応答の開始位置が無い）",
        encode_plain(tok_fast.apply_chat_template(
            [{"role": "user", "content": build_prompt(example, "classify")}],
            tokenize=False, add_generation_prompt=False)))
drifted("推論時に chat template を使わず素のプロンプトを渡した",
        encode_plain(build_prompt(example, "classify")))
drifted("推論スクリプトで指示文を書き直した（意味は同じ・文字は違う）",
        prompt_ids(tok_fast, "次の問い合わせを6つの区分のどれかに分類してください。\n\n"
                             f"問い合わせ: {example.question}"))
try:
    with_system = encode_plain(tok_fast.apply_chat_template(
        [{"role": "system", "content": "あなたは社内ヘルプデスクです。"},
         {"role": "user", "content": build_prompt(example, "classify")}],
        tokenize=False, add_generation_prompt=True))
except Exception as exc:  # テンプレートが system を受け付けない場合もずれの一種
    check("ずれ: 推論時だけ system メッセージを足した（テンプレートが受け付けない）",
          True, f"{type(exc).__name__}: {str(exc)[:60]}")
else:
    drifted("推論時だけ system メッセージを足した", with_system)
drifted("別モデルの chat template で組み立てた文字列を渡した",
        encode_plain(tok_ja.apply_chat_template(
            [{"role": "user", "content": build_prompt(example, "classify")}],
            tokenize=False, add_generation_prompt=True)))

check("指示文は文字列リテラルではなく ftkit.data から来ている（1か所で直せる）",
      CLASSIFY_INSTRUCTION in build_prompt(example, "classify"))
check("chat template はモデルに付属する（2つのモデルで文字列が違う）",
      tok_fast.apply_chat_template([{"role": "user", "content": "x"}], tokenize=False,
                                   add_generation_prompt=True)
      != tok_ja.apply_chat_template([{"role": "user", "content": "x"}], tokenize=False,
                                    add_generation_prompt=True))

# --- 4. KVキャッシュの見積り ------------------------------------------------
section("4. KVキャッシュは系列長とバッチサイズに比例する（算術）")

base = kv_cache_bytes(layers=24, kv_heads=4, head_dim=64, seq_len=320,
                      batch_size=1, bytes_per_value=4)
print(f"  架空のモデル（層 24 / KVヘッド 4 / ヘッド次元 64 / fp32）"
      f"・系列長 320・バッチ 1 → {base / 1024 / 1024:.1f} MiB")
check("式どおりの値になる（2 × 層 × KVヘッド × ヘッド次元 × 系列長 × バッチ × バイト数）",
      base == 2 * 24 * 4 * 64 * 320 * 1 * 4, f"{base:,} バイト")
check("系列長を2倍にすると2倍になる", kv_cache_bytes(24, 4, 64, 640, 1, 4) == 2 * base)
check("バッチを4倍にすると4倍になる", kv_cache_bytes(24, 4, 64, 320, 4, 4) == 4 * base)
check("bf16（2バイト）にすると半分になる",
      kv_cache_bytes(24, 4, 64, 320, 1, 2) == base // 2)
check("入力を 320→192 に短くすると 0.6 倍になる",
      kv_cache_bytes(24, 4, 64, 192, 1, 4) == int(base * 192 / 320))

for model_name in (FAST_MODEL, JA_MODEL):
    report = kv_cache_from_config(model_name, seq_len=320, batch_size=4)
    print(f"  {model_name}: 層 {report['layers']} / ヘッド {report['heads']} / "
          f"KVヘッド {report['kv_heads']} / ヘッド次元 {report['head_dim']} → "
          f"系列長 320 × バッチ 4 で {report['mib']:.1f} MiB (fp32)")
    check(f"[{model_name.split('/')[-1]}] config.json だけで見積りが出せる",
          report["bytes"] > 0 and report["kv_heads"] <= report["heads"],
          f"{report['mib']:.1f} MiB")

# --- 5・6. モデルを1体だけ読む検証 -------------------------------------------
if os.environ.get("SKIP_MODEL") == "1":
    print("\nSKIP_MODEL=1 のため、生成を伴う検証（5・6）を飛ばします。")
else:
    from ftkit.evaluate import generate  # noqa: E402
    from ftkit.models import load_model  # noqa: E402

    section("5. 左パディングのバッチ生成は1件ずつと一致する（SmolLM2-135M を1体だけ読む）")

    picked = [prompt_by_length[prompt_distinct[0]],
              prompt_by_length[prompt_distinct[len(prompt_distinct) // 2]],
              prompt_by_length[prompt_distinct[-1]]]
    prompts = [build_prompt(ex, "classify") for ex in picked]
    batch_rows = [prompt_ids(tok_fast, p) for p in prompts]
    print(f"  選んだ3件の入力長: {[len(r) for r in batch_rows]}"
          "（最長の行にはパディングが入らない）")

    model = load_model(FAST_MODEL)
    pad_id = tok_fast.pad_token_id

    def last_logits(batch: dict) -> torch.Tensor:
        """バッチの最後の位置のロジット（＝次に出すトークンの点数）。"""
        with torch.no_grad():
            return model(**batch).logits[:, -1, :]

    singles = torch.cat([last_logits(pad_batch([row], pad_id, "left"))
                         for row in batch_rows])
    left_batch = last_logits(pad_batch(batch_rows, pad_id, "left"))
    right_batch = last_logits(pad_batch(batch_rows, pad_id, "right"))

    gaps = [float(torch.topk(singles[i], 2).values.diff().abs()) for i in range(3)]
    left_diff = [float((left_batch[i] - singles[i]).abs().max()) for i in range(3)]
    right_diff = [float((right_batch[i] - singles[i]).abs().max()) for i in range(3)]
    print(f"  1位と2位のロジット差: {[f'{g:.2f}' for g in gaps]}")
    print(f"  左パディングとの差:   {[f'{d:.2e}' for d in left_diff]}")
    print(f"  右パディングとの差:   {[f'{d:.2e}' for d in right_diff]}")

    check("左パディング：次に出すトークンの予測が1件ずつと全行一致する",
          [int(left_batch[i].argmax()) for i in range(3)]
          == [int(singles[i].argmax()) for i in range(3)])
    check("左パディング：ロジットの差が無視できる（計算としては同じもの）",
          max(left_diff) < 0.05, f"最大 {max(left_diff):.2e}")
    check("右パディング：パディングが入らない最長の行だけは一致する",
          right_diff[2] < 0.05, f"{right_diff[2]:.2e}")
    check("右パディング：パディングが入った行は別の文脈になっている（差が大きい）",
          min(right_diff[0], right_diff[1]) > 0.5,
          f"{right_diff[0]:.2f} / {right_diff[1]:.2f}")

    one_by_one = [generate(model, tok_fast, p, max_new_tokens=6) for p in prompts]
    batched = generate_batch(model, tok_fast, prompts, max_new_tokens=6, batch_size=3)
    wrong_side = generate_batch(model, tok_fast, prompts, max_new_tokens=6,
                                batch_size=3, side="right")
    for i in range(3):
        print(f"  行{i}: 1件ずつ {one_by_one[i]!r} / 左 {batched[i]!r} / 右 {wrong_side[i]!r}")
    check("生成テキストも1件ずつと完全一致する（左パディング・3件）",
          batched == one_by_one,
          f"{sum(1 for a, b in zip(batched, one_by_one) if a == b)}/3 件一致")
    check("最長の行は右パディングでも一致する（パディングの有無が効いている）",
          wrong_side[2] == one_by_one[2])

    section("6. 出力トークン数とレイテンシはほぼ比例する")

    base_prompt = prompts[-1]

    def timed(max_new: int, prompt_text: str, repeats: int = 2) -> float:
        """max_new トークンを必ず生成させ、最短の所要時間を返す。

        min_new_tokens を付けないと EOS で早く止まり、長さと時間の関係が見えない。
        """
        batch = pad_batch([prompt_ids(tok_fast, prompt_text)], pad_id, "left")
        best = float("inf")
        for _ in range(repeats):
            started = time.perf_counter()
            with torch.no_grad():
                model.generate(**batch, max_new_tokens=max_new, min_new_tokens=max_new,
                               do_sample=False, pad_token_id=pad_id)
            best = min(best, time.perf_counter() - started)
        return best

    timed(4, base_prompt, repeats=1)  # ウォームアップ（最初の1回は遅いので捨てる）

    lengths_to_try = (8, 16, 32, 64)
    seconds = {n: timed(n, base_prompt) for n in lengths_to_try}
    print("  | 出力トークン | 所要（最短・秒） | 1トークンあたり |")
    print("  | --: | --: | --: |")
    for n in lengths_to_try:
        print(f"  | {n} | {seconds[n]:.2f} | {seconds[n] / n:.3f} |")

    check("出力を長くするほど時間が増える（単調）",
          seconds[8] < seconds[16] < seconds[32] < seconds[64],
          " < ".join(f"{seconds[n]:.2f}" for n in lengths_to_try))
    check("出力を8倍にすると所要も大きく増える（1.5倍以上）",
          seconds[64] > seconds[8] * 1.5, f"{seconds[64]:.2f} 対 {seconds[8]:.2f}")
    inc_low = (seconds[32] - seconds[16]) / 16
    inc_high = (seconds[64] - seconds[32]) / 32
    check("1トークンあたりの増分がほぼ一定（＝出力長にほぼ比例する）",
          0.4 <= inc_high / inc_low <= 2.5,
          f"16→32 で {inc_low:.3f} 秒/トークン、32→64 で {inc_high:.3f} 秒/トークン")

    long_prompt = "（参考情報）" + "社内規程の抜粋です。" * 20 + "\n\n" + base_prompt
    added = len(prompt_ids(tok_fast, long_prompt)) - len(prompt_ids(tok_fast, base_prompt))
    check("入力を十分に長くできた（50トークン以上）", added >= 50, f"+{added} トークン")
    long_seconds = timed(8, long_prompt)
    per_input = (long_seconds - seconds[8]) / added
    per_output = (seconds[64] - seconds[8]) / 56
    print(f"  入力 +{added} トークン（出力は 8 のまま）: {long_seconds:.2f} 秒 → "
          f"入力 {per_input:.4f} 秒/トークン 対 出力 {per_output:.4f} 秒/トークン")
    check("入力を1トークン増やす費用は、出力を1トークン増やす費用よりずっと安い",
          per_output > per_input * 2,
          f"出力が入力の {per_output / per_input:.1f}倍" if per_input > 0
          else "入力側の増分はほぼ 0")

    del model
    gc.collect()

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション15の検証はすべて成功しました。")
