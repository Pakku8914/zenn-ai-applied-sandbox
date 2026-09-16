#!/usr/bin/env python3
"""セッション15：出力形式のコスト測定と、生成のバッチ化（左パディング）。

**学習は右パディングでよいが、生成は左パディングでなければならない。**
生成は「系列のいちばん最後の位置」から次のトークンを予測するため、右パディングだと
短い行の最後がパディングトークンになり、生成開始位置がバッチ内でずれる。
（学習は各位置を並列に採点し、パディング位置は labels=-100 で損失から外れるので影響がない。）

単体で実行するとトークナイザだけを使う計測を表示する（モデルの重みは読まない）。

  docker compose exec app python src/session15/batch_generate.py

数値は環境とトークナイザで変わる。**出力された数字を自分の記録に残すこと。**
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ftkit.data import CATEGORIES, Example, build_prompt, load  # noqa: E402
from ftkit.evaluate import FORMAT_RE, EvalResult, extract_category  # noqa: E402

# ---------------------------------------------------------------------------
# 1. 出力形式のコスト（同じ情報を何トークンで表すか）
# ---------------------------------------------------------------------------


def answer_fields(example: Example) -> tuple[str, str, str]:
    """3行の定型から3つの値（区分・担当・期限）を取り出す。"""
    match = FORMAT_RE.match(example.answer.strip())
    if not match:
        raise ValueError(f"{example.id} の answer が3行の定型ではありません: {example.answer!r}")
    return match.group(1).strip(), match.group(2).strip(), match.group(3).strip()


def render_variants(example: Example) -> dict[str, str]:
    """同じ3つの値を5通りの出力形式で表す。学習させる「答えの形」の候補。"""
    category, owner, deadline = answer_fields(example)
    ja = {"区分": category, "担当": owner, "期限": deadline}
    en = {"category": category, "assignee": owner, "due": deadline}
    return {
        "values_only": f"{category},{owner},{deadline}",
        "three_lines": example.answer,
        "json_compact_ja": json.dumps(ja, ensure_ascii=False, separators=(",", ":")),
        "json_pretty_ja": json.dumps(ja, ensure_ascii=False, indent=2),
        "json_verbose_en": json.dumps(
            {"result": en, "confidence": 0.9, "note": "自動分類の結果です"},
            ensure_ascii=False, indent=2),
    }


VARIANT_NAMES = ("values_only", "three_lines", "json_compact_ja",
                 "json_pretty_ja", "json_verbose_en")


def n_tokens(tokenizer, text: str) -> int:
    return len(tokenizer(text, add_special_tokens=False)["input_ids"])


def format_cost(tokenizer, examples: list[Example]) -> dict[str, dict[str, float]]:
    """表現ごとの平均トークン数と、値以外（構造）に使われた分。

    overhead = その表現の合計 − 値だけを別々に符号化した合計。
    括弧・引用符・キー名・改行・インデントに払っているトークン数にあたる。
    """
    totals = {name: 0 for name in VARIANT_NAMES}
    values_total = 0
    for example in examples:
        variants = render_variants(example)
        for name in VARIANT_NAMES:
            totals[name] += n_tokens(tokenizer, variants[name])
        values_total += sum(n_tokens(tokenizer, v) for v in answer_fields(example))
    n = len(examples)
    return {
        name: {
            "tokens": totals[name] / n,
            "values": values_total / n,
            "overhead": (totals[name] - values_total) / n,
        }
        for name in VARIANT_NAMES
    }


def render_cost_table(cost: dict[str, dict[str, float]]) -> str:
    lines = ["| 出力形式 | 平均トークン | 値 | 構造 |", "| :--- | --: | --: | --: |"]
    for name, row in cost.items():
        lines.append(f"| `{name}` | {row['tokens']:.1f} | {row['values']:.1f} "
                     f"| {row['overhead']:.1f} |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 2. パディングの向き
# ---------------------------------------------------------------------------


def prompt_ids(tokenizer, prompt: str) -> list[int]:
    """推論時に渡す入力のトークン列。

    ftkit.evaluate.generate が1件ずつ組み立てているものと同じ手順
    （chat template を適用し、add_generation_prompt=True で応答の開始位置まで作る）。
    """
    text = tokenizer.apply_chat_template(
        [{"role": "user", "content": prompt}], tokenize=False, add_generation_prompt=True)
    return tokenizer(text, add_special_tokens=False)["input_ids"]


def pad_batch(rows: list[list[int]], pad_token_id: int, side: str = "left") -> dict:
    """トークン列をバッチにまとめる。**生成では side="left" を使う。**

    side="right" は本文の実演（生成開始位置がずれることの再現）用に残してある。
    """
    if side not in ("left", "right"):
        raise ValueError(f"side は left か right: {side!r}")
    max_len = max(len(row) for row in rows)
    input_ids: list[list[int]] = []
    attention_mask: list[list[int]] = []
    for row in rows:
        pad_len = max_len - len(row)
        pad = [pad_token_id] * pad_len
        zeros = [0] * pad_len
        if side == "left":
            input_ids.append(pad + row)
            attention_mask.append(zeros + [1] * len(row))
        else:
            input_ids.append(row + pad)
            attention_mask.append([1] * len(row) + zeros)
    return {"input_ids": torch.tensor(input_ids, dtype=torch.long),
            "attention_mask": torch.tensor(attention_mask, dtype=torch.long)}


# ---------------------------------------------------------------------------
# 3. バッチ生成とバッチ評価
# ---------------------------------------------------------------------------


@torch.no_grad()
def generate_batch(model, tokenizer, prompts: list[str], max_new_tokens: int = 12,
                   batch_size: int = 4, side: str = "left") -> list[str]:
    """複数のプロンプトをまとめて生成する。既定は左パディング。

    メモリはバッチサイズ × 系列長で増える。既定環境（メモリ 5.8GB）では 2〜4 に抑える。
    """
    model.eval()
    outputs: list[str] = []
    for start in range(0, len(prompts), batch_size):
        chunk = prompts[start:start + batch_size]
        rows = [prompt_ids(tokenizer, p) for p in chunk]
        batch = pad_batch(rows, tokenizer.pad_token_id, side)
        out = model.generate(**batch, max_new_tokens=max_new_tokens, do_sample=False,
                             pad_token_id=tokenizer.pad_token_id)
        generated = out[:, batch["input_ids"].shape[1]:]
        outputs.extend(tokenizer.decode(row, skip_special_tokens=True).strip()
                       for row in generated)
    return outputs


def evaluate_batched(model, tokenizer, examples: list[Example], task: str = "classify",
                     batch_size: int = 4, limit: int | None = None) -> EvalResult:
    """ftkit.evaluate.evaluate をバッチ化したもの。

    **判定（extract_category・FORMAT_RE）は1件ずつの版とまったく同じ関数を使う。**
    速くするのは生成だけで、採点の基準は変えない。
    """
    target = examples[:limit] if limit else examples
    prompts = [build_prompt(example, task) for example in target]
    outputs = generate_batch(model, tokenizer, prompts,
                             max_new_tokens=12 if task == "classify" else 48,
                             batch_size=batch_size)
    result = EvalResult()
    for example, output in zip(target, outputs):
        predicted = extract_category(output)
        result.n += 1
        result.correct += int(predicted == example.category)
        if task == "format":
            result.format_ok += int(bool(FORMAT_RE.match(output.strip())))
        else:
            result.format_ok += int(output.strip() in CATEGORIES)
        result.predictions.append((example.id, example.category, predicted))
    return result


# ---------------------------------------------------------------------------
# 4. KVキャッシュの見積り（算術のみ）
# ---------------------------------------------------------------------------


def kv_cache_bytes(layers: int, kv_heads: int, head_dim: int, seq_len: int,
                   batch_size: int = 1, bytes_per_value: int = 4) -> int:
    """KVキャッシュのバイト数。

    各層が key と value を系列長ぶん持つので係数 2 が付く。
    系列長にもバッチサイズにも**比例する**のが要点。
    """
    return 2 * layers * kv_heads * head_dim * seq_len * batch_size * bytes_per_value


def kv_cache_from_config(model_name: str, seq_len: int, batch_size: int = 1,
                         bytes_per_value: int = 4, revision: str = "main") -> dict:
    """config.json（重みではない）から実際のモデルの見積りを出す。"""
    from transformers import AutoConfig

    config = AutoConfig.from_pretrained(model_name, revision=revision)
    heads = config.num_attention_heads
    kv_heads = getattr(config, "num_key_value_heads", None) or heads
    head_dim = getattr(config, "head_dim", None) or config.hidden_size // heads
    total = kv_cache_bytes(config.num_hidden_layers, kv_heads, head_dim,
                           seq_len, batch_size, bytes_per_value)
    return {"model": model_name, "layers": config.num_hidden_layers,
            "heads": heads, "kv_heads": kv_heads, "head_dim": head_dim,
            "seq_len": seq_len, "batch_size": batch_size,
            "bytes_per_value": bytes_per_value, "bytes": total,
            "mib": total / 1024 / 1024}


# ---------------------------------------------------------------------------
# 単体実行：トークナイザだけの計測を表示する
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from ftkit.models import FAST_MODEL, JA_MODEL, load_tokenizer

    test = load("test")
    print("=== 出力形式のトークン数（test 90件の平均） ===")
    for name in (FAST_MODEL, JA_MODEL):
        tokenizer = load_tokenizer(name)
        print(f"\n{name}")
        print(render_cost_table(format_cost(tokenizer, test)))

    tokenizer = load_tokenizer(FAST_MODEL)
    print("\n=== 出力形式の実物（1件） ===")
    for key, text in render_variants(test[0]).items():
        print(f"\n[{key}] {n_tokens(tokenizer, text)} トークン")
        print(text)

    print("\n=== パディングの向き（生成開始位置） ===")
    rows = [prompt_ids(tokenizer, build_prompt(example, "classify"))
            for example in (min(test[:20], key=lambda e: len(e.question)),
                            max(test[:20], key=lambda e: len(e.question)))]
    for side in ("right", "left"):
        batch = pad_batch(rows, tokenizer.pad_token_id, side)
        print(f"\nside={side}")
        for i, ids in enumerate(batch["input_ids"].tolist()):
            tail = tokenizer.decode(ids[-3:]).replace("\n", "\\n")
            print(f"  行{i}: 元の長さ {len(rows[i]):>3} / 末尾3トークン {tail!r}")

    print("\n=== KVキャッシュの見積り（config.json だけを読む） ===")
    for name in (FAST_MODEL, JA_MODEL):
        report = kv_cache_from_config(name, seq_len=320, batch_size=4)
        print(f"  {name}: 層 {report['layers']} / KVヘッド {report['kv_heads']} / "
              f"ヘッド次元 {report['head_dim']} / 系列長 {report['seq_len']} × "
              f"バッチ {report['batch_size']} → {report['mib']:.1f} MiB (fp32)")
