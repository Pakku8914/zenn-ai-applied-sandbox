"""モデルの読み込みと LoRA の付け外し（セッション5・6の参照実装）。

本書で使うモデルは2種類。用途で使い分ける。

| 名前 | パラメータ | 特徴 | 用途 |
| :--- | :--- | :--- | :--- |
| SmolLM2-135M-Instruct | 1.35億 | 速い。日本語は弱い | ループを速く回す練習 |
| Qwen2.5-0.5B-Instruct | 4.94億 | 日本語が使える。3〜4倍遅い | 実際に精度を上げる演習 |

**どちらが良いかではなく、何を確かめたいかで選ぶ**（セッション2の判断基準）。
"""

from __future__ import annotations

import torch

FAST_MODEL = "HuggingFaceTB/SmolLM2-135M-Instruct"
JA_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
MODEL_REVISION = "main"


def load_tokenizer(model_name: str = JA_MODEL):
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(model_name, revision=MODEL_REVISION)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    return tok


def load_model(model_name: str = JA_MODEL, dtype=torch.float32):
    """CPU 学習なので float32 で読む。

    bfloat16 は CPU では速くならないことが多く、勾配が不安定になる。
    量子化して読む（4bit など）のは CUDA 前提の実装が多いため本書では扱わない。
    """
    from transformers import AutoModelForCausalLM

    return AutoModelForCausalLM.from_pretrained(model_name, revision=MODEL_REVISION, dtype=dtype)


def attach_lora(model, r: int = 16, alpha: int = 32, dropout: float = 0.05,
                target_modules: tuple[str, ...] = ("q_proj", "k_proj", "v_proj", "o_proj")):
    """LoRA アダプタを付ける。学習対象のパラメータ数が劇的に減る。"""
    from peft import LoraConfig, get_peft_model

    config = LoraConfig(r=r, lora_alpha=alpha, lora_dropout=dropout, bias="none",
                        task_type="CAUSAL_LM", target_modules=list(target_modules))
    return get_peft_model(model, config)


def param_stats(model) -> dict:
    """学習対象のパラメータ数と割合。LoRA の効果を数字で示す。"""
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    return {"trainable": trainable, "total": total,
            "ratio": trainable / total if total else 0.0}
