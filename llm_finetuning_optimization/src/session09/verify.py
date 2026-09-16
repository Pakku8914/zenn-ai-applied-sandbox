#!/usr/bin/env python3
"""セッション9の自己検証：学習後の評価に使う道具が正しく動くこと。

検証する主張（本文に書いた内容と1対1で対応させる）:
  1. EvalResult.confusion() が正しい混同表を作る（合成した予測列で検算する）
  2. extract_category と FORMAT_RE の挙動（定型を外れても区分を拾える／形式判定は厳密）
  3. generate が do_sample=False で決定的（同じ入力を2回呼んで一致する）
  4. 忘却プローブが「学習していない別タスク」を含む構造になっている
  5. 30件で正解率 0.200 のときの幅（算術で示す）

1・2・4の構造検証・5は**モデルを読まないので数秒で終わる**。3と4の生成だけ
SmolLM2-135M を**1体だけ**読み、終わったら del と gc.collect() で解放する。
**学習は一切しない**ので、空きメモリが 2GB 程度の環境でも完走する。

  python src/session09/verify.py
  SKIP_MODEL=1 python src/session09/verify.py   # 生成を伴う検証を飛ばす（数秒）
"""

from __future__ import annotations

import gc
import json
import math
import os
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from confusion_report import (  # noqa: E402
    QWEN_AFTER_FORMAT_OK, QWEN_AFTER_SPEC, SMOL_AFTER_FORMAT_OK, SMOL_AFTER_SPEC,
    build_result, collapse_ratio, column_totals, macro_accuracy, render_markdown, row_totals,
    summarize,
)
from forgetting import PROBES, auto_metrics, save_report  # noqa: E402

from ftkit.data import CATEGORIES, CLASSIFY_INSTRUCTION, FORMAT_INSTRUCTION  # noqa: E402
from ftkit.evaluate import FORMAT_RE, EvalResult, extract_category  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


# --- 1. 混同表の検算（モデルを読まない） ------------------------------------
print("=== 1. 混同表が正しく作られる（合成した予測列で検算） ===")

qwen = build_result(QWEN_AFTER_SPEC, QWEN_AFTER_FORMAT_OK)
qwen_table = qwen.confusion()
print(render_markdown(qwen_table))
print(summarize(qwen))

check("列の見出しが CATEGORIES の順＋「その他」",
      list(next(iter(qwen_table.values())).keys()) == CATEGORIES + ["その他"])
check("行の見出しが CATEGORIES の順",
      list(qwen_table.keys()) == CATEGORIES)
check("行合計が各区分の件数と一致する（先頭30件は 経費6・勤怠3・PC5・アカウント3・オフィス7・セキュリティ6）",
      row_totals(qwen_table) == {"経費": 6, "勤怠": 3, "PC": 5, "アカウント": 3,
                                 "オフィス": 7, "セキュリティ": 6},
      str(row_totals(qwen_table)))
check("対角の合計が正解数と一致する",
      sum(qwen_table[c][c] for c in CATEGORIES) == qwen.correct == 25,
      f"対角={sum(qwen_table[c][c] for c in CATEGORIES)} correct={qwen.correct}")
check("表の総和が n と一致する（取りこぼしがない）",
      sum(sum(row.values()) for row in qwen_table.values()) == qwen.n == 30)
check("正解率が実測の 0.833 を再現する", round(qwen.accuracy, 3) == 0.833,
      f"{qwen.accuracy:.3f}")
check("形式遵守率が実測の 1.000 を再現する", round(qwen.format_rate, 3) == 1.000,
      f"{qwen.format_rate:.3f}")
check("6区分の外の予測は「その他」列に入る（形式は守っても区分名でなければ不正解）",
      qwen_table["セキュリティ"]["その他"] == 1)
check("macro（クラス平均）は micro（全体）より低い ― 件数の少ない区分が弱いため",
      round(macro_accuracy(qwen_table), 3) == 0.822 < round(qwen.accuracy, 3),
      f"macro={macro_accuracy(qwen_table):.3f} micro={qwen.accuracy:.3f}")
check("要約行が本文の記載と一致する",
      summarize(qwen) == ("n=30 micro=0.833 macro=0.822 最大予測クラス=オフィス(7) "
                          "崩壊率=0.233 形式遵守率=1.000"), summarize(qwen))

print()
smol = build_result(SMOL_AFTER_SPEC, SMOL_AFTER_FORMAT_OK)
smol_table = smol.confusion()
print(render_markdown(smol_table))
print(summarize(smol))

check("SmolLM2 側も同じ区分の件数になっている（同じ test の先頭30件だから）",
      row_totals(smol_table) == row_totals(qwen_table))
check("正解率が実測の 0.200 を再現する", round(smol.accuracy, 3) == 0.200,
      f"{smol.accuracy:.3f}")
check("形式遵守率が実測の 0.933 を再現する", round(smol.format_rate, 3) == 0.933,
      f"{smol.format_rate:.3f}")
top, count, ratio = collapse_ratio(smol_table)
check("予測が「アカウント」に 21 件集中している（1クラスへの崩壊）",
      (top, count) == ("アカウント", 21), f"{top}({count})")
check("崩壊率が 0.700（実測の 21/30）", round(ratio, 3) == 0.700, f"{ratio:.3f}")
check("崩壊した表では対角以外に件数が偏る（列合計の分布で分かる）",
      column_totals(smol_table)["勤怠"] == 0 and column_totals(smol_table)["オフィス"] == 0,
      str(column_totals(smol_table)))
check("要約行が本文の記載と一致する",
      summarize(smol) == ("n=30 micro=0.200 macro=0.256 最大予測クラス=アカウント(21) "
                          "崩壊率=0.700 形式遵守率=0.933"), summarize(smol))

odd = EvalResult(n=2, correct=0, format_ok=0,
                 predictions=[("X-1", "対象外", "経費"), ("X-2", "経費", "不明")])
odd_table = odd.confusion()
check("正解ラベルが6区分の外にある行は表に現れない（表の総和が n に届かない）",
      sum(sum(row.values()) for row in odd_table.values()) == 1 and odd.n == 2,
      f"表の総和={sum(sum(row.values()) for row in odd_table.values())} n={odd.n}")

# --- 2. extract_category と FORMAT_RE（モデルを読まない） --------------------
print("\n=== 2. 出力から区分を取り出す／形式を判定する ===")

cases = [
    ("経費", "経費", "区分名だけの出力"),
    ("  アカウント  ", "アカウント", "前後の空白は無視される"),
    ("【区分】PC\n【担当】情報システム部\n【期限】1営業日", "PC", "定型の1行目から取る"),
    ("【区分】 経費 \n【担当】経理部\n【期限】5営業日", "経費", "定型の中の空白は落とす"),
    ("区分はセキュリティです", "セキュリティ", "定型を外れても含まれていれば拾える"),
    ("【区分】不明\n【担当】-\n【期限】-", "不明", "6区分の外はそのまま返る（→その他）"),
    ("", "", "空文字は空文字"),
    ("改行を含む\n2行目", "改行を含む", "1行目だけを見る"),
    ("社内の担当部署に確認してから折り返しご連絡いたします", "社内の担当部署に確認して",
     "区分が見つからなければ1行目の先頭12文字"),
]
for text, expected, note in cases:
    actual = extract_category(text)
    check(f"extract_category: {note}", actual == expected, f"{text!r} -> {actual!r}")

check("複数の区分名が含まれると CATEGORIES の順で先にある方を返す（出現順ではない）",
      extract_category("セキュリティ研修の経費を精算したい") == "経費",
      extract_category("セキュリティ研修の経費を精算したい"))
check("分類タスクの形式遵守は「区分名だけ」の完全一致で、含み判定ではない",
      extract_category("区分はPCです") == "PC" and "区分はPCです" not in CATEGORIES)

format_cases = [
    ("【区分】経費\n【担当】経理部\n【期限】5営業日", True, "3行の定型"),
    ("【区分】経費\n【担当】経理部\n【期限】5営業日\n", True, "末尾の改行1つは許容される"),
    ("【区分】経費\n【担当】経理部\n【期限】5営業日\n【備考】なし", False, "4行目があると不合格"),
    ("【区分】経費\n【担当】経理部", False, "2行では不合格"),
    ("\n【区分】経費\n【担当】経理部\n【期限】5営業日", False, "先頭の空行があると不合格"),
    ("【担当】経理部\n【区分】経費\n【期限】5営業日", False, "順序が違うと不合格"),
    ("【区分】\n【担当】経理部\n【期限】5営業日", False, "区分が空だと不合格"),
    ("区分: 経費\n担当: 経理部\n期限: 5営業日", False, "括弧が違うと不合格"),
]
for text, expected, note in format_cases:
    actual = bool(FORMAT_RE.match(text))
    check(f"FORMAT_RE: {note}", actual == expected, f"判定={actual}")

tricky = "【区分】　\n【担当】経理部\n【期限】5営業日"
check("形式は合格でも区分が空になりうる（形式遵守率と正解率は独立に動く）",
      bool(FORMAT_RE.match(tricky)) and extract_category(tricky) == "",
      f"形式={bool(FORMAT_RE.match(tricky))} 区分={extract_category(tricky)!r}")

eval_src = (Path(__file__).resolve().parents[2] / "ftkit" / "evaluate.py").read_text(
    encoding="utf-8")
check("generate は do_sample=False で呼んでいる（評価は決定的）",
      "do_sample=False" in eval_src and "do_sample=True" not in eval_src)

# --- 4a. 忘却プローブの構造（モデルを読まない） -----------------------------
print("\n=== 4a. 忘却プローブの構造 ===")

ids = [p.id for p in PROBES]
held_out = [p for p in PROBES if p.kind == "held_out"]
trained = [p for p in PROBES if p.kind == "trained"]
check("プローブの id が一意", len(set(ids)) == len(ids), str(ids))
check("kind は held_out / trained の2値",
      {p.kind for p in PROBES} <= {"held_out", "trained"}, str({p.kind for p in PROBES}))
check("学習していない別タスクが2件以上ある（忘却はここでしか見えない）",
      len(held_out) >= 2, f"{len(held_out)} 件")
check("学習したタスクの基準プローブがある（学習が効いたかを同じレポートで見る）",
      len(trained) >= 1, f"{len(trained)} 件")
check("held_out のプローブに学習時の指示文が入っていない",
      all(CLASSIFY_INSTRUCTION not in p.prompt and FORMAT_INSTRUCTION not in p.prompt
          for p in held_out))
check("trained のプローブは学習時の指示文をそのまま使う",
      all(CLASSIFY_INSTRUCTION in p.prompt or FORMAT_INSTRUCTION in p.prompt
          for p in trained))
check("すべてのプローブに「何を見るか」が書かれている",
      all(p.watch.strip() for p in PROBES))

metrics = auto_metrics("【区分】経費\n【担当】経理部\n【期限】5営業日")
check("auto_metrics が定型と区分語を拾う",
      metrics["looks_format"] and metrics["category_words"] == 1 and metrics["lines"] == 3,
      str(metrics))
metrics_free = auto_metrics("3, 6, 9, 12, 15")
check("自由文では looks_format が False・区分語が 0",
      not metrics_free["looks_format"] and metrics_free["category_words"] == 0,
      str(metrics_free))

fake = [{"id": "P-99", "kind": "held_out", "prompt": "x", "output": "y", **auto_metrics("y")}]
path = save_report(fake, "verify", {"model": "dummy"})
loaded = json.loads(path.read_text(encoding="utf-8"))
check("忘却レポートが JSON として保存・読み戻しできる",
      loaded["tag"] == "verify" and len(loaded["records"]) == 1
      and loaded["records"][0]["id"] == "P-99", str(path))

# --- 5. サンプル数と結論の強さ（モデルを読まない） --------------------------
print("\n=== 5. サンプル数と結論の強さ（算術） ===")


def wald(correct: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """正解率の 95% の目安（Wald 近似）。p が 0 や 1 に近いと粗くなる。"""
    p = correct / n
    se = math.sqrt(p * (1 - p) / n)
    return p, max(0.0, p - z * se), min(1.0, p + z * se)


def diff_ci(c1: int, n1: int, c2: int, n2: int, z: float = 1.96) -> tuple[float, float, float]:
    """2つの正解率の差の 95% の目安。0 を含むなら「差があるとは言えない」。"""
    p1, p2 = c1 / n1, c2 / n2
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    return p2 - p1, (p2 - p1) - z * se, (p2 - p1) + z * se

for correct, n in ((6, 30), (18, 90), (30, 150)):
    p, lo, hi = wald(correct, n)
    print(f"  正解率 {p:.3f}（{correct}/{n}）-> 95%の目安 {lo:.3f}〜{hi:.3f}（幅 ±{(hi - lo) / 2:.3f}）")

p30, lo30, hi30 = wald(6, 30)
check("30件・正解率 0.200 の幅は ±0.143（0.057〜0.343）",
      (round(lo30, 3), round(hi30, 3)) == (0.057, 0.343),
      f"{p30:.3f} -> {lo30:.3f}〜{hi30:.3f}")
_, lo90, hi90 = wald(18, 90)
check("同じ 0.200 でも 90件なら幅が ±0.083 に狭まる",
      round((hi90 - lo90) / 2, 3) == 0.083, f"±{(hi90 - lo90) / 2:.3f}")
_, lo150, hi150 = wald(30, 150)
check("150件なら幅が ±0.064 になる（件数を4倍にして幅は半分）",
      round((hi150 - lo150) / 2, 3) == 0.064, f"±{(hi150 - lo150) / 2:.3f}")
check("件数を増やすほど幅は単調に狭くなる", (hi30 - lo30) > (hi90 - lo90) > (hi150 - lo150))

_, lo_q, hi_q = wald(25, 30)
check("0.200（6/30）と 0.833（25/30）の区間は重ならない ― 30件でも4倍の差なら言える",
      hi30 < lo_q, f"{hi30:.3f} < {lo_q:.3f}")
d, dlo, dhi = diff_ci(6, 30, 8, 30)
check("0.200 と 0.267（2件差）の差の区間は 0 をまたぐ ― 30件では言えない",
      dlo < 0 < dhi, f"差 {d:+.3f}（{dlo:+.3f}〜{dhi:+.3f}）")
d2, dlo2, dhi2 = diff_ci(6, 30, 25, 30)
check("0.200 と 0.833 の差の区間は 0 を含まない", dlo2 > 0,
      f"差 {d2:+.3f}（{dlo2:+.3f}〜{dhi2:+.3f}）")
check("30件で刻める最小の差は 1/30 = 0.033", round(1 / 30, 3) == 0.033)
_, lo_zero, hi_zero = wald(0, 30)
check("Wald 近似は 0/30 で幅が 0 になる（0 や 1 に近いと使えない）",
      (lo_zero, hi_zero) == (0.0, 0.0),
      "0/30 の上限は経験的な近似（3/n）で 0.100 程度と考える")

# --- 3・4b. 生成の決定性とプローブの実行（モデルを1体だけ読む） --------------
if os.environ.get("SKIP_MODEL") == "1":
    print("\nSKIP_MODEL=1 のため、生成を伴う検証（3・4b）を飛ばします。")
else:
    print("\n=== 3. 生成の決定性（SmolLM2-135M を1体だけ読む） ===")
    from ftkit.data import build_prompt, load  # noqa: E402
    from ftkit.evaluate import evaluate, generate  # noqa: E402
    from ftkit.models import FAST_MODEL, load_model, load_tokenizer  # noqa: E402

    def sample_generate(model, tokenizer, prompt: str, seed: int,
                        max_new_tokens: int = 12) -> str:
        """評価にサンプリングを使う「Bad」の実演。同じ入力でも出力が変わる。"""
        messages = [{"role": "user", "content": prompt}]
        text = tokenizer.apply_chat_template(messages, tokenize=False,
                                             add_generation_prompt=True)
        inputs = tokenizer(text, return_tensors="pt", add_special_tokens=False)
        torch.manual_seed(seed)
        model.eval()
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=True,
                                 temperature=2.0, top_k=0,
                                 pad_token_id=tokenizer.pad_token_id)
        return tokenizer.decode(out[0][inputs["input_ids"].shape[1]:],
                                skip_special_tokens=True).strip()

    tokenizer = load_tokenizer(FAST_MODEL)
    model = load_model(FAST_MODEL)
    samples = load("test")[:2]
    prompts = [build_prompt(ex, "classify") for ex in samples]

    first = [generate(model, tokenizer, p, max_new_tokens=8) for p in prompts]
    second = [generate(model, tokenizer, p, max_new_tokens=8) for p in prompts]
    for prompt_text, out in zip(prompts, first):
        print(f"  {prompt_text[-20:]!r} -> {out!r}")
    check("同じ入力を2回生成して完全一致する（do_sample=False）", first == second,
          f"{sum(1 for a, b in zip(first, second) if a == b)}/{len(first)} 件一致")

    sampled = [sample_generate(model, tokenizer, prompts[0], seed=s) for s in (1, 2, 3)]
    print(f"  サンプリング（temperature=2.0）の3回: {[s[:12] for s in sampled]}")
    check("サンプリングにすると同じ入力でも出力が揺れる（評価に使えない）",
          len(set(sampled)) > 1, f"{len(set(sampled))} 種類")

    r1 = evaluate(model, tokenizer, samples, "classify")
    r2 = evaluate(model, tokenizer, samples, "classify")
    check("evaluate を2回呼んで予測列が完全一致する", r1.predictions == r2.predictions,
          f"{len(r1.predictions)} 件の予測が一致")

    print("\n=== 4b. 忘却プローブが実行できる（2件だけ・学習はしない） ===")
    from forgetting import probe_report  # noqa: E402

    records = probe_report(model, tokenizer, PROBES[:2], max_new_tokens=16)
    for record in records:
        print(f"  [{record['id']}/{record['kind']}] -> {record['output']!r}")
    check("プローブのレコードに必要なキーがそろっている",
          all({"id", "kind", "prompt", "output", "chars", "lines",
               "category_words", "looks_format"} <= set(r) for r in records))
    check("プローブを2回通しても同じ出力になる（決定的）",
          [r["output"] for r in probe_report(model, tokenizer, PROBES[:2], max_new_tokens=16)]
          == [r["output"] for r in records])

    del model
    gc.collect()

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション9の検証はすべて成功しました。")
