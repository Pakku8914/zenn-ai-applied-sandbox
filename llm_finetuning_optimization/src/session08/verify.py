#!/usr/bin/env python3
"""セッション8の自己検証：選好ペアと DPO の損失を機械で確かめる。

検証する主張（本文に書いた内容と1対1で対応させる）:
  1. 同梱の選好ペアは 200 件。chosen だけが3行の定型で、rejected は口語。
     差の軸は全ペアで同じ組み合わせ（format と hedge の2つ）で、
     長さの差は常に 11 文字（＝長さは形式と完全に交絡している）
  2. 方針モデルと参照モデルが等しいとき、DPO の loss は ln2 = 0.693147 になる
  3. 対数尤度は「合計」なので、同じ確からしさでも長い系列ほど値が小さくなる。
     全マスクの系列では nan ではなく 0.0 になる（黙って壊れる側の事故）
  4. ペアは chosen 群 → rejected 群 の順に1つのバッチへ入り、
     切り捨てが起きたら例外で止まる
  5. LoRA を付けた直後は B がゼロなので、方針と参照のマージンは厳密に 0
  6. 同じペアで 8 step 更新すればマージンが正に転じ、loss は ln2 より下がる。
     参照モデル（アダプタ無効の経路）は 8 step 学習しても変わらない

モデルは1体だけ読み、8 step しか回さないので数分で終わる。
参照モデルを別体で持たないので、メモリ 5.8GB の環境でも余裕がある。

  docker compose exec app python src/session08/verify.py
"""

from __future__ import annotations

import gc
import math
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dpo_loss import (  # noqa: E402
    BETA,
    DPO_MAX_LENGTH,
    dpo_loss,
    encode_pairs,
    pair_logprobs,
    reference_logprobs,
    scored_tokens,
    sequence_logprob,
)
from ftkit.data import load_preference  # noqa: E402
from ftkit.models import FAST_MODEL, attach_lora, load_model, load_tokenizer  # noqa: E402
from ftkit.tokenize import IGNORE_INDEX  # noqa: E402
from ftkit.train import set_seed  # noqa: E402
from pair_check import axis_counts, diff_axes, is_format, length_gaps, owner_of  # noqa: E402

SEED = 20260815
LN2 = math.log(2.0)

# 軸の検査に使う固定文字列（データに依存させず、いつでも同じ判定になるようにする）
GOOD = "【区分】経費\n【担当】経理部\n【期限】支出日から10日以内"
HEDGED = GOOD + "くらいです"          # 定型は守るが「ぼかし」だけが違う（軸1つ）
SLOPPY = "総務部にたぶん聞いてください"  # 形式・ぼかし・長さ・担当がすべて違う（軸4つ）

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


# --- 1. 選好ペアの検査（モデルを読まない・数秒） ------------------------------
section("1. 選好ペアの検査（モデルを読まない）")

rows = load_preference()
check("選好ペアは 200 件", len(rows) == 200, f"{len(rows)} 件")
check("chosen はすべて3行の定型",
      all(is_format(r["chosen"]) for r in rows),
      f"{sum(is_format(r['chosen']) for r in rows)}/{len(rows)} 件")
check("rejected は1件も定型を満たさない",
      not any(is_format(r["rejected"]) for r in rows),
      f"定型だったもの {sum(is_format(r['rejected']) for r in rows)} 件")
check("chosen と rejected は必ず異なる",
      all(r["chosen"] != r["rejected"] for r in rows))

counts = axis_counts(rows)
print(f"  軸の組み合わせ: {dict(counts)}")
check("差の軸の組み合わせは1種類しかない", len(counts) == 1, f"{len(counts)} 種類")
top_axes, top_count = counts.most_common(1)[0]
check("その軸は format と hedge の2つ", top_axes == ("format", "hedge"), str(top_axes))
check("その組み合わせが 200 件すべてを占める", top_count == 200, f"{top_count} 件")

gaps = sorted(set(length_gaps(rows)))
check("長さの差は全ペアで一定（rejected − chosen = 11 文字）", gaps == [11], str(gaps))
check("担当部署は chosen と rejected で変わらない（事実は壊していない）",
      all(owner_of(r["chosen"]) == owner_of(r["rejected"]) and owner_of(r["chosen"])
          for r in rows))

check("定型を守ったまま『ぼかし』だけを違えると軸が1つになる",
      diff_axes(GOOD, HEDGED) == ["hedge"], str(diff_axes(GOOD, HEDGED)))
check("雑な rejected は軸が4つになる（何を学ぶか特定できない）",
      diff_axes(GOOD, SLOPPY) == ["format", "hedge", "length", "owner"],
      str(diff_axes(GOOD, SLOPPY)))

# --- 2. DPO の損失（モデルを読まない） ---------------------------------------
section("2. DPO の損失（モデルを読まない）")

equal = torch.full((3,), -120.0)
loss_equal, stats_equal = dpo_loss(equal.clone(), equal.clone(),
                                   equal.clone(), equal.clone())
print(f"  マージン 0 の loss = {loss_equal.item():.6f}（ln2 = {LN2:.6f}）")
check("方針と参照が等しいとき loss は ln2", abs(loss_equal.item() - LN2) < 1e-6,
      f"{loss_equal.item():.6f}")
check("そのとき pair_accuracy は 0.000（マージンが厳密に 0 なので）",
      stats_equal.pair_accuracy == 0.0, f"{stats_equal.pair_accuracy:.3f}")

ref = torch.full((3,), -120.0)
policy_chosen = torch.tensor([-116.0, -119.0, -114.0])   # 参照より上げた
policy_rejected = torch.tensor([-124.0, -121.0, -126.0])  # 参照より下げた
loss_good, stats_good = dpo_loss(policy_chosen, policy_rejected, ref, ref)
print(f"  chosen 有利の loss = {stats_good.loss:.6f}  margin={stats_good.margin:+.3f}  "
      f"acc={stats_good.pair_accuracy:.3f}")
check("chosen が有利なら loss は ln2 より小さい", stats_good.loss < LN2,
      f"{stats_good.loss:.6f} < {LN2:.6f}")
check("すべてのペアでマージンが正なら pair_accuracy は 1.000",
      stats_good.pair_accuracy == 1.0, f"{stats_good.pair_accuracy:.3f}")
check("暗黙の報酬の差は beta × マージンに一致する",
      abs((stats_good.chosen_reward - stats_good.rejected_reward)
          - BETA * stats_good.margin) < 1e-4,
      f"{stats_good.chosen_reward - stats_good.rejected_reward:.4f} vs "
      f"{BETA * stats_good.margin:.4f}")

loss_bad, stats_bad = dpo_loss(policy_rejected, policy_chosen, ref, ref)
check("chosen と rejected を入れ替えると loss は ln2 より大きい", stats_bad.loss > LN2,
      f"{stats_bad.loss:.6f} > {LN2:.6f}")
check("ラベルを逆にすると pair_accuracy は 0.000", stats_bad.pair_accuracy == 0.0,
      f"{stats_bad.pair_accuracy:.3f}")

_, stats_zero_beta = dpo_loss(policy_chosen, policy_rejected, ref, ref, beta=0.0)
check("beta=0 では情報が消えて loss が ln2 に戻る", abs(stats_zero_beta.loss - LN2) < 1e-6,
      f"{stats_zero_beta.loss:.6f}")

policy_probe = policy_chosen.clone().requires_grad_(True)
ref_probe = ref.clone().requires_grad_(True)
loss_probe, _ = dpo_loss(policy_probe, policy_rejected, ref_probe, ref)
loss_probe.backward()
check("方針側には勾配が流れる（学習対象）", policy_probe.grad is not None)
check("参照側には勾配が流れない（detach されている）", ref_probe.grad is None,
      "grad is None" if ref_probe.grad is None else f"grad={ref_probe.grad}")

# --- 3. 対数尤度は「合計」 ---------------------------------------------------
section("3. 対数尤度は「合計」なので長い系列ほど小さくなる")

vocab = 5
logits = torch.zeros(1, 4, vocab)                       # どのトークンも等確率 1/5
labels = torch.tensor([[IGNORE_INDEX, 1, 2, 3]])
logp = sequence_logprob(logits, labels)
expected = -3 * math.log(vocab)
print(f"  採点3トークンの対数尤度 = {logp.item():.4f} / 手計算 -3 log 5 = {expected:.4f}")
check("手計算と一致する", abs(logp.item() - expected) < 1e-4, f"{logp.item():.6f}")
check("採点対象のトークン数は 3", int(scored_tokens(labels)[0]) == 3,
      f"{int(scored_tokens(labels)[0])}")

long_logp = sequence_logprob(torch.zeros(1, 7, vocab),
                             torch.tensor([[IGNORE_INDEX, 1, 2, 3, 1, 2, 3]]))
print(f"  採点6トークンの対数尤度 = {long_logp.item():.4f}")
check("同じ確からしさでもトークン数が2倍なら対数尤度も2倍小さい",
      abs(long_logp.item() - 2 * logp.item()) < 1e-4,
      f"{logp.item():.4f} -> {long_logp.item():.4f}")

all_masked = sequence_logprob(logits, torch.full((1, 4), IGNORE_INDEX))
check("全マスクの系列は nan ではなく 0.0 になる（黙って壊れる）",
      float(all_masked) == 0.0, f"{float(all_masked)}")

# --- 4. ペアのエンコード（トークナイザを読む） --------------------------------
section("4. ペアのエンコード（トークナイザを読む）")

tokenizer = load_tokenizer(FAST_MODEL)
batch, n = encode_pairs(tokenizer, rows[:4], DPO_MAX_LENGTH)
print(f"  input_ids の形 = {tuple(batch['input_ids'].shape)}  n = {n}")
check("バッチの行数は 2n（chosen 群 → rejected 群）",
      batch["input_ids"].shape[0] == 2 * n, f"{batch['input_ids'].shape[0]} 行")

tokens = scored_tokens(batch["labels"])
scored = int(tokens.sum())
total = batch["labels"].shape[0] * (batch["labels"].shape[1] - 1)
chosen_tokens = float(tokens[:n].float().mean())
rejected_tokens = float(tokens[n:].float().mean())
print(f"  採点対象トークン数の平均: chosen {chosen_tokens:.1f} / "
      f"rejected {rejected_tokens:.1f}")
print(f"  loss マスク率 = {1 - scored / total:.3f}")
check("rejected の方が採点対象トークンが多い（長さの交絡）",
      chosen_tokens < rejected_tokens,
      f"chosen {chosen_tokens:.1f} < rejected {rejected_tokens:.1f}")
check("プロンプト部分は採点対象から外れている（マスク率 0.5 超）",
      1 - scored / total > 0.5, f"{1 - scored / total:.3f}")

decoded_chosen = tokenizer.decode(
    [int(x) for x in batch["labels"][0] if int(x) != IGNORE_INDEX],
    skip_special_tokens=True)
decoded_rejected = tokenizer.decode(
    [int(x) for x in batch["labels"][n] if int(x) != IGNORE_INDEX],
    skip_special_tokens=True)
check("前半の行の採点対象は3行の定型（chosen）", is_format(decoded_chosen),
      repr(decoded_chosen[:14]))
check("後半の行の採点対象は定型でない（rejected）", not is_format(decoded_rejected),
      repr(decoded_rejected[:14]))

try:
    encode_pairs(tokenizer, rows[:4], 96)
    truncation_guarded = False
except ValueError as exc:
    truncation_guarded = True
    print(f"  max_length=96: {type(exc).__name__} で停止した")
check("max_length が小さいと例外で止まる（黙って別の入力にならない）",
      truncation_guarded)

# --- 5. 学習前は方針＝参照 ---------------------------------------------------
section("5. 学習前は方針＝参照（LoRA の B がゼロ）")

set_seed(SEED)                                    # モデル構築の前に呼ぶ
model = attach_lora(load_model(FAST_MODEL), r=8, alpha=16, dropout=0.0)
model.eval()                                      # 方針と参照で計算を変えない

batch, n = encode_pairs(tokenizer, rows[:2], DPO_MAX_LENGTH)
ref_chosen0, ref_rejected0 = reference_logprobs(model, batch, n)
with torch.no_grad():
    policy_chosen0, policy_rejected0 = pair_logprobs(model, batch, n)
_, stats_init = dpo_loss(policy_chosen0, policy_rejected0, ref_chosen0, ref_rejected0)

print(f"  方針 chosen = {[round(float(x), 3) for x in policy_chosen0]}")
print(f"  参照 chosen = {[round(float(x), 3) for x in ref_chosen0]}")
print(f"  margin = {stats_init.margin:.3e}  loss = {stats_init.loss:.6f}")
check("学習前のマージンは厳密に 0", stats_init.margin == 0.0, f"{stats_init.margin:.3e}")
check("学習前の loss は ln2 = 0.693147", abs(stats_init.loss - LN2) < 1e-6,
      f"{stats_init.loss:.6f}")
check("学習前の pair_accuracy は 0.000（勝ってもいないし負けてもいない）",
      stats_init.pair_accuracy == 0.0, f"{stats_init.pair_accuracy:.3f}")

# --- 6. 同じペアで 8 step 更新する -------------------------------------------
section("6. 同じペアで 8 step 更新する（マージンが正に転じる）")

params = [p for p in model.parameters() if p.requires_grad]
optimizer = torch.optim.AdamW(params, lr=2e-4)
history = []
for step in range(1, 9):
    ref_chosen, ref_rejected = reference_logprobs(model, batch, n)
    policy_chosen, policy_rejected = pair_logprobs(model, batch, n)
    loss, stats = dpo_loss(policy_chosen, policy_rejected, ref_chosen, ref_rejected)
    loss.backward()
    torch.nn.utils.clip_grad_norm_(params, 1.0)
    optimizer.step()
    optimizer.zero_grad()
    history.append(stats)
    print(f"  step {step}  loss={stats.loss:.4f}  margin={stats.margin:+.3f}  "
          f"chosen_logp={stats.chosen_logp:.1f}  "
          f"rejected_logp={stats.rejected_logp:.1f}  acc={stats.pair_accuracy:.3f}")

first, last = history[0], history[-1]
check("1 step 目の loss は ln2（まだ参照と同じモデル）", abs(first.loss - LN2) < 1e-6,
      f"{first.loss:.6f}")
check("8 step 後の loss は ln2 より下がる", last.loss < LN2 - 1e-3, f"{last.loss:.6f}")
check("8 step 後のマージンは正", last.margin > 0.0, f"{last.margin:+.4f}")
check("暗黙の報酬の差は全 step で beta × マージンに一致する",
      all(abs((s.chosen_reward - s.rejected_reward) - BETA * s.margin) < 1e-3
          for s in history))
check("loss に nan は出ない", all(s.loss == s.loss for s in history))
print(f"  chosen_logp {first.chosen_logp:.1f} -> {last.chosen_logp:.1f} / "
      f"rejected_logp {first.rejected_logp:.1f} -> {last.rejected_logp:.1f}")
print("  → chosen が下がっていてもマージンは正になれる。これが報酬ハックの入口。")

ref_chosen2, ref_rejected2 = reference_logprobs(model, batch, n)
check("参照モデルは 8 step 学習しても変わらない（ベースの重みは動かない）",
      torch.allclose(ref_chosen2, ref_chosen0, atol=1e-4)
      and torch.allclose(ref_rejected2, ref_rejected0, atol=1e-4),
      f"chosen 最大差 {float((ref_chosen2 - ref_chosen0).abs().max()):.2e}")

del model, optimizer, params
gc.collect()

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション8の検証はすべて成功しました。")
