#!/usr/bin/env python3
"""DPO（Direct Preference Optimization）の最小実装（セッション8の参照実装）。

trl の DPOTrainer は使わない。本書は素の PyTorch で通す方針（学習ループを自分で
書いた方が、参照モデルの扱いとマージンの動き方が見えるため）。

覚えることは3つだけ。

  1. 系列ごとの対数尤度を **合計** で出す（`sequence_logprob`）
  2. 方針モデルと参照モデルの差を取り、chosen と rejected で引き算する（`dpo_loss`）
  3. 参照モデルは別体を読まない。**LoRA を無効化した経路がそのまま参照になる**
     （`reference_logprobs`）。メモリ 5.8GB の環境ではこれが効く

使い方:

    from dpo_loss import dpo_loss, encode_pairs, pair_logprobs, reference_logprobs

    batch, n = encode_pairs(tokenizer, rows, DPO_MAX_LENGTH)
    ref_c, ref_r = reference_logprobs(model, batch, n)   # 勾配なし・LoRA 無効
    pol_c, pol_r = pair_logprobs(model, batch, n)        # 勾配あり・LoRA 有効
    loss, stats = dpo_loss(pol_c, pol_r, ref_c, ref_r)
"""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import torch
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ftkit.data import CATEGORIES, Example  # noqa: E402
from ftkit.tokenize import IGNORE_INDEX, collate, encode_example  # noqa: E402

# 参照モデルからどれだけ離れることを許すか。大きいほど参照に強く縛られる
BETA = 0.1

# chosen と rejected で回答の長さが違うため、切り捨てが起きない値を取る。
# 切り捨てが起きると片側だけプロンプトが削られ、「同じ質問を見せているつもりで
# 別の入力になる」という気づきにくい事故になる（セッション4の切り捨ての向きの応用）。
DPO_MAX_LENGTH = 384


# --- 選好の1行を SFT と同じ形に直す -----------------------------------------

def to_pair_examples(row: dict) -> tuple[Example, Example]:
    """選好データの1行を、SFT と同じ `Example` 2件（chosen 側 / rejected 側）に変換する。

    **`preference.jsonl` の "prompt" は素の質問文**で、指示文が付いていない。
    ここで `Example` に詰め直しておけば、あとは `build_prompt(ex, "format")` が
    SFT と同じ `FORMAT_INSTRUCTION` を被せてくれる。これを省くと、学習時の入力と
    評価時の入力が別物になる。
    """
    category = row["chosen"].splitlines()[0].removeprefix("【区分】").strip()
    if category not in CATEGORIES:
        raise ValueError(
            f"chosen の1行目から区分を取り出せません: {row['chosen']!r}。"
            "chosen が【区分】から始まる3行の定型になっているか確認してください。"
        )
    chosen = Example(id=row["id"], question=row["prompt"],
                     category=category, answer=row["chosen"])
    rejected = Example(id=row["id"], question=row["prompt"],
                       category=category, answer=row["rejected"])
    return chosen, rejected


def encode_pairs(tokenizer, rows: list[dict], max_length: int = DPO_MAX_LENGTH) -> tuple[dict, int]:
    """chosen 群 → rejected 群 の順に1つのバッチへ詰める。

    同じ forward に流すことで、パディングの当たり方による非対称を作らない。
    戻り値の `n` は行数で、`logp[:n]` が chosen、`logp[n:]` が rejected に対応する。
    """
    chosen_encoded, rejected_encoded = [], []
    for row in rows:
        chosen, rejected = to_pair_examples(row)
        enc_c = encode_example(tokenizer, chosen, "format", max_length)
        enc_r = encode_example(tokenizer, rejected, "format", max_length)
        if enc_c["truncated_prompt_tokens"] or enc_r["truncated_prompt_tokens"]:
            raise ValueError(
                f"{row['id']}: プロンプトが切り捨てられました（max_length={max_length}）。"
                "chosen と rejected で回答の長さが違うため切り捨て量も変わり、"
                "同じ質問を見せているつもりで別の入力になります。max_length を増やしてください。"
            )
        chosen_encoded.append(enc_c)
        rejected_encoded.append(enc_r)
    batch = collate(chosen_encoded + rejected_encoded, tokenizer.pad_token_id)
    return batch, len(rows)


# --- 対数尤度 ---------------------------------------------------------------

def sequence_logprob(logits: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
    """系列ごとの対数尤度の **合計** を返す（形は [B]）。

    `labels` が `IGNORE_INDEX` の位置は数えない（loss マスクと同じ扱い）。
    平均ではなく合計なので、**長い系列は構造的に値が小さくなる**。この性質が
    「短い方を好む」という偏りの原因になる（本文の長さの交絡）。
    """
    logits = logits[:, :-1, :]                       # 最後の位置は次のトークンが無い
    target = labels[:, 1:]                           # 1つずらして「次のトークン」に合わせる
    mask = target != IGNORE_INDEX
    target = target.masked_fill(~mask, 0)            # gather を通すための穴埋め（値は使わない）
    logp = torch.log_softmax(logits.float(), dim=-1)
    token_logp = logp.gather(-1, target.unsqueeze(-1)).squeeze(-1)
    return (token_logp * mask.to(token_logp.dtype)).sum(dim=-1)


def scored_tokens(labels: torch.Tensor) -> torch.Tensor:
    """対数尤度に数えたトークン数（形は [B]）。長さで割りたいときに使う。"""
    return (labels[:, 1:] != IGNORE_INDEX).sum(dim=-1)


def pair_logprobs(model, batch: dict, n: int) -> tuple[torch.Tensor, torch.Tensor]:
    """方針モデル（学習する側）の対数尤度。勾配を流すのでここは no_grad にしない。"""
    out = model(input_ids=batch["input_ids"], attention_mask=batch["attention_mask"])
    logp = sequence_logprob(out.logits, batch["labels"])
    return logp[:n], logp[n:]


@torch.no_grad()
def reference_logprobs(model, batch: dict, n: int) -> tuple[torch.Tensor, torch.Tensor]:
    """参照モデルの対数尤度。**LoRA を無効化した経路**が参照モデルそのものになる。

    学習しているのは LoRA だけで、ベースの重みは1バイトも動かない。だから
    アダプタを切れば「学習前のモデル」がいつでも復元できる。別体を読まないので
    メモリが2倍にならず、参照が学習でずれる事故も起きない。

    呼ぶ前に `model.eval()` にしておくこと（dropout が入ると、方針と参照で
    同じ入力に対する計算が変わってしまう）。
    """
    with model.disable_adapter():
        out = model(input_ids=batch["input_ids"], attention_mask=batch["attention_mask"])
        logp = sequence_logprob(out.logits, batch["labels"])
    return logp[:n].detach(), logp[n:].detach()


# --- DPO の損失 -------------------------------------------------------------

@dataclass
class DPOStats:
    """1 step ぶんの記録。loss だけを見ないために、内訳を全部残す。"""

    loss: float
    margin: float             # β をかける前のマージンの平均
    chosen_reward: float      # β×(方針 − 参照) の平均（chosen 側の暗黙の報酬）
    rejected_reward: float
    chosen_logp: float        # 方針モデルの対数尤度そのもの（下がっていないかを見る）
    rejected_logp: float
    pair_accuracy: float      # マージンが正のペアの割合

    def as_dict(self) -> dict:
        return asdict(self)


def dpo_loss(policy_chosen: torch.Tensor, policy_rejected: torch.Tensor,
             ref_chosen: torch.Tensor, ref_rejected: torch.Tensor,
             beta: float = BETA) -> tuple[torch.Tensor, DPOStats]:
    """DPO の損失。

        loss = -log σ( β × [ (方針_chosen − 参照_chosen) − (方針_rejected − 参照_rejected) ] )

    `-log σ(x)` は `softplus(-x)` と同じ式で、こちらの方が数値的に安定する。
    参照側は必ず `detach()` する（参照は学習対象ではない）。
    """
    ref_chosen = ref_chosen.detach()
    ref_rejected = ref_rejected.detach()
    chosen_rel = policy_chosen - ref_chosen
    rejected_rel = policy_rejected - ref_rejected
    margin = chosen_rel - rejected_rel
    loss = F.softplus(-beta * margin).mean()
    stats = DPOStats(
        loss=float(loss.item()),
        margin=float(margin.mean().item()),
        chosen_reward=float((beta * chosen_rel).mean().item()),
        rejected_reward=float((beta * rejected_rel).mean().item()),
        chosen_logp=float(policy_chosen.mean().item()),
        rejected_logp=float(policy_rejected.mean().item()),
        pair_accuracy=float((margin > 0).float().mean().item()),
    )
    return loss, stats
