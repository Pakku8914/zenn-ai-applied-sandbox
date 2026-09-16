#!/usr/bin/env python3
"""セッション13の自己検証：プルーニング・重み共有・低ランク分解・出力長とレイテンシ。

検証する主張（本文に書いた内容と1対1で対応させる）:
  1. 非構造プルーニング（重みを 0 にするだけ）は行列積を速くしない。
     疎化率 50% でも 90% でも、全部 0 にしても所要時間は変わらない。
     保存に必要なバイト数も1バイトも減らない
  2. 疎行列表現（to_sparse）は非ゼロ要素数（nnz）は減るが、50% 疎では
     メモリが 2.5 倍になり、密行列との積も速くならない
     （COO の損益分岐は密度 20% ＝ 疎化率 80%）
  3. 構造プルーニング（ヘッド・層の削除）で減るパラメータ数は層構成から計算できる。
     SmolLM2-135M は 134,515,008 個（S07 のフル微調整の学習対象 134.5M と一致、
     fp32 で 513.1 MiB ＝ S10 の統合済みモデルの実測と一致）で、注意機構は全体の
     19.7% しかない。ヘッドを 1/3 消しても 6.6% しか減らない
  4. 出力トークン数とレイテンシはほぼ比例する（135M で 8 / 16 / 32 トークンを実測）

1〜3 はモデルを読まないので数秒で終わる。4 は SmolLM2-135M を **1体だけ** 読み、
学習は一切せず、終わったら del と gc.collect() で解放する。

  python src/session13/verify.py
  SKIP_MODEL=1 python src/session13/verify.py   # 4 を飛ばす（モデルを一切読まない）
"""

from __future__ import annotations

import gc
import os
import statistics
import sys
import time
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

SEED = 20260815
N = 512          # 行列の一辺（512x512 の fp32 ＝ 1MiB）
REPEAT = 15      # 密行列積の繰り返し回数（中央値を取る）
SPARSE_REPEAT = 3

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def median_seconds(fn, repeat: int) -> float:
    """ウォームアップ1回のあと repeat 回測って中央値を返す。"""
    fn()
    times = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return statistics.median(times)


def zero_out(tensor: torch.Tensor, ratio: float, seed: int = SEED) -> torch.Tensor:
    """要素のうち ratio の割合をランダムに 0 にする（非構造プルーニング）。"""
    generator = torch.Generator().manual_seed(seed)
    mask = torch.rand(tensor.shape, generator=generator) >= ratio
    return tensor * mask


def storage_bytes(tensor: torch.Tensor) -> int:
    """密なテンソルを保存するのに必要なバイト数（0 も1要素として書き出される）。"""
    return tensor.numel() * tensor.element_size()


print("=== 測定条件 ===")
print(f"  torch {torch.__version__} / スレッド数 {torch.get_num_threads()} / "
      f"OMP_NUM_THREADS={os.environ.get('OMP_NUM_THREADS', '未設定')}")
print("  ※ 秒数は環境と負荷で変わります。比べるのは「同じ実行の中での比」です。")

# --- 1. 重みを 0 にしても行列積は速くならない -------------------------------
print("\n=== 1. 非構造プルーニング（重みを 0 にする）は行列積を速くしない ===")

generator = torch.Generator().manual_seed(SEED)
weight = torch.randn(N, N, generator=generator)
activation = torch.randn(N, N, generator=generator)

base_seconds = median_seconds(lambda: torch.matmul(weight, activation), REPEAT)
base_output = torch.matmul(weight, activation)
print(f"  基準（疎化率 0%）: {base_seconds * 1000:.2f} ms / "
      f"保存 {storage_bytes(weight) / 1024:.0f} KiB")
print(f"  {'疎化率':>8}{'非ゼロ要素':>12}{'所要(ms)':>12}{'基準比':>9}{'保存(KiB)':>12}")

for ratio in (0.5, 0.9, 1.0):
    pruned = zero_out(weight, ratio)
    nonzero = int((pruned != 0).sum())
    seconds = median_seconds(lambda p=pruned: torch.matmul(p, activation), REPEAT)
    rel = seconds / base_seconds
    print(f"  {ratio * 100:>7.0f}%{nonzero:>12,}{seconds * 1000:>12.2f}{rel:>8.2f}x"
          f"{storage_bytes(pruned) / 1024:>12.0f}")
    check(f"疎化率 {ratio * 100:.0f}% でも所要時間が基準の 0.7〜1.4 倍の範囲に収まる（速くならない）",
          0.7 <= rel <= 1.4, f"{rel:.2f} 倍")
    check(f"疎化率 {ratio * 100:.0f}% でも保存に必要なバイト数が1バイトも減らない",
          storage_bytes(pruned) == storage_bytes(weight),
          f"{storage_bytes(pruned):,} バイト")

half = zero_out(weight, 0.5)
half_nonzero = int((half != 0).sum())
check("疎化率 50% の指定どおり、非ゼロ要素が約半分になっている（0 にする操作自体は効いている）",
      0.48 <= half_nonzero / half.numel() <= 0.52,
      f"{half_nonzero:,}/{half.numel():,} = {half_nonzero / half.numel():.3f}")
check("出力は基準と一致しない（重みを本当に書き換えている ＝ 計算結果は変わる）",
      not torch.allclose(torch.matmul(half, activation), base_output),
      "0 にした分だけ出力が変わる")

# --- 2. 疎行列表現にしても得しない（50% 疎では損をする） --------------------
print("\n=== 2. 疎行列表現（COO）は 50% 疎では大きくなり、積も速くならない ===")

sparse = half.to_sparse().coalesce()
nnz = sparse.values().numel()
index_bytes = sparse.indices().numel() * sparse.indices().element_size()
value_bytes = sparse.values().numel() * sparse.values().element_size()
coo_bytes = index_bytes + value_bytes
dense_bytes = storage_bytes(half)

print(f"  密行列: {half.numel():,} 要素 x {half.element_size()} バイト = "
      f"{dense_bytes / 1024:.0f} KiB")
print(f"  COO   : nnz={nnz:,} / 値 {value_bytes / 1024:.0f} KiB ＋ "
      f"添字 {index_bytes / 1024:.0f} KiB = {coo_bytes / 1024:.0f} KiB "
      f"（密行列の {coo_bytes / dense_bytes:.2f} 倍）")

check("COO の非ゼロ要素数が密行列の非ゼロ数と一致する", nnz == half_nonzero,
      f"nnz={nnz:,}")
check("50% 疎の COO は密行列より大きい（添字が値より重い）",
      coo_bytes > dense_bytes, f"{coo_bytes / dense_bytes:.2f} 倍")

bytes_per_value = sparse.values().element_size()                       # fp32 なら 4
bytes_per_index = 2 * sparse.indices().element_size()                  # 2次元の添字（int64）
break_even = bytes_per_value / (bytes_per_value + bytes_per_index)
print(f"  損益分岐の密度 = {bytes_per_value} / ({bytes_per_value} + {bytes_per_index}) "
      f"= {break_even:.2f} → 疎化率 {(1 - break_even) * 100:.0f}% を超えて初めて小さくなる")
check("COO の損益分岐は密度 0.20（疎化率 80%）", abs(break_even - 0.2) < 1e-9,
      f"{break_even:.3f}")

sparse_seconds = median_seconds(lambda: torch.sparse.mm(sparse, activation), SPARSE_REPEAT)
dense_seconds = median_seconds(lambda: torch.matmul(half, activation), REPEAT)
print(f"  疎行列積 {sparse_seconds * 1000:.2f} ms  /  密行列積 {dense_seconds * 1000:.2f} ms "
      f"（{sparse_seconds / dense_seconds:.2f} 倍）")
check("50% 疎では疎行列積は密行列積より速くならない",
      sparse_seconds > dense_seconds * 0.8, f"{sparse_seconds / dense_seconds:.2f} 倍")
check("疎行列積と密行列積の結果は一致する（数学は同じ・コストだけが違う）",
      torch.allclose(torch.sparse.mm(sparse, activation), torch.matmul(half, activation),
                     atol=1e-3), "同じ答えに別の値段が付いている")

# --- 3. 構造プルーニングで実際に減るパラメータ数（層構成からの計算） --------
print("\n=== 3. 構造プルーニングで減るパラメータ数（SmolLM2-135M の層構成から計算） ===")

HIDDEN = 576        # hidden_size
LAYERS = 30         # num_hidden_layers
Q_HEADS = 9         # num_attention_heads
KV_HEADS = 3        # num_key_value_heads（GQA なので query より少ない）
HEAD_DIM = 64       # head_dim
FFN = 1536          # intermediate_size
VOCAB = 49152       # vocab_size（S04 の実測と同じ）
GROUPS = Q_HEADS // KV_HEADS     # 1つの KV ヘッドを共有する query ヘッドの数 = 3


def attention_params(q_heads: int, kv_heads: int) -> int:
    """q/k/v/o の4つの線形層。GQA では k と v だけヘッド数が少ない。"""
    q = HIDDEN * HEAD_DIM * q_heads
    kv = HIDDEN * HEAD_DIM * kv_heads * 2
    o = HEAD_DIM * q_heads * HIDDEN
    return q + kv + o


def mlp_params() -> int:
    """gate / up / down の3つ（SwiGLU なので2本の入力側がある）。"""
    return 3 * HIDDEN * FFN


def layer_params(q_heads: int = Q_HEADS, kv_heads: int = KV_HEADS) -> int:
    return attention_params(q_heads, kv_heads) + mlp_params() + 2 * HIDDEN   # 2つの RMSNorm


def total_params(q_heads: int = Q_HEADS, kv_heads: int = KV_HEADS,
                 layers: int = LAYERS, tied: bool = True) -> int:
    body = layers * layer_params(q_heads, kv_heads)
    embedding = VOCAB * HIDDEN * (1 if tied else 2)   # tie_word_embeddings=True なら1つ
    return body + embedding + HIDDEN                  # 最後の RMSNorm


BASE = total_params()
print(f"  総パラメータ = {BASE:,}")
check("計算値が 134,515,008（S07 のフル微調整の学習対象 134.5M）と一致する",
      BASE == 134_515_008, f"{BASE:,}")
fp32_mib = BASE * 4 / 1024 / 1024
check("fp32 のサイズが 513.1 MiB（S10 の統合済み 135M モデルの実測 約513MiB）と一致する",
      abs(fp32_mib - 513.1) < 0.1, f"{fp32_mib:.1f} MiB")

parts = {
    "埋め込み（入力と出力で共有）": VOCAB * HIDDEN,
    "注意機構（q/k/v/o × 30層）": LAYERS * attention_params(Q_HEADS, KV_HEADS),
    "MLP（gate/up/down × 30層）": LAYERS * mlp_params(),
    "正規化（RMSNorm）": LAYERS * 2 * HIDDEN + HIDDEN,
}
print(f"  {'内訳':<30}{'パラメータ数':>16}{'割合':>8}")
for name, count in parts.items():
    print(f"  {name:<30}{count:>16,}{count / BASE * 100:>7.1f}%")
check("内訳の合計が総パラメータと一致する（数え落ちがない）",
      sum(parts.values()) == BASE, f"{sum(parts.values()):,}")
check("埋め込みは全体の 21.0%",
      round(parts["埋め込み（入力と出力で共有）"] / BASE * 100, 1) == 21.0)
check("注意機構は全体の 19.7% しかない（ヘッドを全部消しても2割）",
      round(parts["注意機構（q/k/v/o × 30層）"] / BASE * 100, 1) == 19.7)
check("MLP が全体の 59.2% で最も重い",
      round(parts["MLP（gate/up/down × 30層）"] / BASE * 100, 1) == 59.2)

# 重み共有（tie_word_embeddings）を外したらどうなるか
untied = total_params(tied=False)
print(f"  重み共有を外すと {untied:,}（+{(untied / BASE - 1) * 100:.1f}%）")
check("入力埋め込みと出力層の共有をやめると 162,826,560（+21.0%）になる",
      untied == 162_826_560 and round((untied / BASE - 1) * 100, 1) == 21.0,
      f"{untied:,}")

# LoRA の学習対象（S06 の実測と一致するか）
lora_r = 16
lora = LAYERS * lora_r * ((HIDDEN + HEAD_DIM * Q_HEADS)          # q_proj
                          + (HIDDEN + HEAD_DIM * KV_HEADS)       # k_proj
                          + (HIDDEN + HEAD_DIM * KV_HEADS)       # v_proj
                          + (HEAD_DIM * Q_HEADS + HIDDEN))       # o_proj
print(f"  LoRA(r=16, q/k/v/o) の学習対象 = {lora:,} / 全体 {BASE + lora:,} "
      f"({lora / (BASE + lora) * 100:.2f}%)")
check("LoRA の学習対象が S06 の実測 1.843M と一致する", lora == 1_843_200, f"{lora:,}")
check("LoRA を付けた総パラメータが S06 の実測 136.4M と一致する",
      round((BASE + lora) / 1e6, 1) == 136.4, f"{(BASE + lora) / 1e6:.3f}M")
check("学習対象の割合が S06 の実測 1.35% と一致する",
      round(lora / (BASE + lora) * 100, 2) == 1.35,
      f"{lora / (BASE + lora) * 100:.2f}%")

# ヘッド単位・層単位のプルーニングで減る量
print(f"  {'プルーニングの単位':<40}{'減るパラメータ':>16}{'削減率':>9}")
plans = [
    (f"KV グループ1つ（query {GROUPS} ヘッド＋KV 1ヘッド）を全層から",
     BASE - total_params(Q_HEADS - GROUPS, KV_HEADS - 1)),
    ("注意機構を全部（q/k/v/o を全層から削除）", BASE - total_params(0, 0)),
    ("末尾の1層", layer_params()),
    ("末尾の6層（30層の20%）", 6 * layer_params()),
]
for name, reduced in plans:
    print(f"  {name:<40}{reduced:>16,}{reduced / BASE * 100:>8.1f}%")

kv_group_cut = BASE - total_params(Q_HEADS - GROUPS, KV_HEADS - 1)
check("KV グループを1つ（＝ヘッドの 1/3）消しても削減は 8,847,360（6.6%）だけ",
      kv_group_cut == 8_847_360 and round(kv_group_cut / BASE * 100, 1) == 6.6,
      f"{kv_group_cut:,}")
check("注意機構を全部消しても削減は 19.7%（残りは MLP と埋め込み）",
      round((BASE - total_params(0, 0)) / BASE * 100, 1) == 19.7)
check("1層あたり 3,540,096（2.6%）／6層で 15.8%（層数を20%削っても15.8%）",
      layer_params() == 3_540_096
      and round(6 * layer_params() / BASE * 100, 1) == 15.8,
      f"1層 {layer_params():,}")
check("ヘッド削除は GROUPS の単位でしか行えない（9 query / 3 KV ヘッド ＝ 1グループ3ヘッド）",
      GROUPS == 3 and Q_HEADS % KV_HEADS == 0, f"GROUPS={GROUPS}")

# 低ランク分解の損益分岐
print("  低ランク分解（W[m,n] を A[m,r]・B[r,n] に置き換える）の損益分岐:")
for m, n, label in ((HIDDEN, HIDDEN, "q_proj / o_proj (576x576)"),
                    (HIDDEN, FFN, "up_proj (576x1536)")):
    dense_count = m * n
    break_even_r = dense_count / (m + n)
    half_r = dense_count / 2 / (m + n)
    print(f"    {label:<26} 元 {dense_count:>9,} / 損益分岐 r={break_even_r:.1f} / "
          f"半分にする r={half_r:.1f}")
check("576x576 の損益分岐は r=288、パラメータを半分にするには r=144",
      HIDDEN * HIDDEN / (HIDDEN + HIDDEN) == 288.0
      and HIDDEN * HIDDEN / 2 / (HIDDEN + HIDDEN) == 144.0)
check("576x1536 の損益分岐は r≒418.9（大きい行列ほど分解の余地が大きい）",
      abs(HIDDEN * FFN / (HIDDEN + FFN) - 418.9) < 0.1,
      f"{HIDDEN * FFN / (HIDDEN + FFN):.1f}")

# --- 4. 出力トークン数とレイテンシはほぼ比例する ----------------------------
if os.environ.get("SKIP_MODEL") == "1":
    print("\nSKIP_MODEL=1 のため、生成を伴う検証（4）を飛ばします。")
else:
    print("\n=== 4. 出力トークン数とレイテンシ（SmolLM2-135M を1体だけ読む） ===")
    from ftkit.data import CLASSIFY_INSTRUCTION, Example, build_prompt, load  # noqa: E402
    from ftkit.models import (  # noqa: E402
        FAST_MODEL, load_model, load_tokenizer, param_stats,
    )

    @torch.no_grad()
    def timed_generate(model, tokenizer, prompt: str, n_tokens: int) -> tuple[int, float]:
        """ちょうど n_tokens だけ生成して所要時間を返す。

        min_new_tokens を付けないと EOS で早く止まり、出力長を振った比較にならない。
        """
        messages = [{"role": "user", "content": prompt}]
        text = tokenizer.apply_chat_template(messages, tokenize=False,
                                             add_generation_prompt=True)
        inputs = tokenizer(text, return_tensors="pt", add_special_tokens=False)
        model.eval()
        started = time.perf_counter()
        out = model.generate(**inputs, max_new_tokens=n_tokens, min_new_tokens=n_tokens,
                             do_sample=False, pad_token_id=tokenizer.pad_token_id)
        elapsed = time.perf_counter() - started
        return int(out[0].shape[0] - inputs["input_ids"].shape[1]), elapsed

    try:
        samples = load("test")[:2]
    except FileNotFoundError:
        samples = [Example("Q-0001", "有給休暇の申請はいつまでですか", "勤怠", "-"),
                   Example("Q-0002", "社内PCが起動しません", "PC", "-")]
        print("  data/test.jsonl が無いので、内蔵の2件で測ります"
              "（本来は tools/make_dataset.py を先に実行してください）。")
    prompts = [build_prompt(example, "classify") for example in samples]
    print(f"  指示文は {CLASSIFY_INSTRUCTION[:18]}... を使う（入力側は3条件で共通）")

    tokenizer = load_tokenizer(FAST_MODEL)
    model = load_model(FAST_MODEL)
    stats = param_stats(model)
    print(f"  総パラメータ {stats['total']:,}（第3節の計算値 {BASE:,}）")
    check("実物の総パラメータが第3節の計算値と一致する（層構成の計算が正しい）",
          stats["total"] == BASE, f"{stats['total']:,}")

    latency: dict[int, float] = {}
    print(f"  {'max_new_tokens':>16}{'中央値(秒)':>12}{'生成トークン数':>16}")
    for n_tokens in (8, 16, 32):
        measured = [timed_generate(model, tokenizer, prompt, n_tokens)
                    for prompt in prompts for _ in range(2)]
        counts = {count for count, _ in measured}
        latency[n_tokens] = statistics.median(seconds for _, seconds in measured)
        print(f"  {n_tokens:>16}{latency[n_tokens]:>12.2f}{sorted(counts)!s:>16}")
        check(f"max_new_tokens={n_tokens} でちょうど {n_tokens} トークン生成された"
              "（min_new_tokens で長さを固定している）",
              counts == {n_tokens}, str(sorted(counts)))

    marginal = (latency[32] - latency[8]) / 24
    predicted16 = latency[8] + 8 * marginal
    print(f"  1トークンあたりの周辺コスト = ({latency[32]:.2f} - {latency[8]:.2f}) / 24 "
          f"= {marginal:.3f} 秒/トークン")
    print(f"  出力長を 32 → 16 に半分にすると "
          f"{(latency[32] - latency[16]) / latency[32] * 100:.1f}% 短縮（この実行での実測）")
    print("  ※ この数値は環境依存です。本文には書かず、自分の記録表に残してください。")

    check("出力を長くすると必ず遅くなる（32 トークン > 8 トークン）",
          latency[32] > latency[8], f"{latency[8]:.2f}s -> {latency[32]:.2f}s")
    check("1トークンあたりの周辺コストが正（出力長はコストに比例して乗る）",
          marginal > 0, f"{marginal:.3f} 秒/トークン")
    check("32/8 の比が 1.3〜4.6 倍（比例するが、入力側の1回分だけ切片が乗るので4倍未満）",
          1.3 <= latency[32] / latency[8] <= 4.6, f"{latency[32] / latency[8]:.2f} 倍")
    check("16 トークンの実測が直線モデルの予測から 30% 以内（ほぼ比例している）",
          abs(latency[16] - predicted16) <= 0.30 * latency[16],
          f"実測 {latency[16]:.2f}s / 予測 {predicted16:.2f}s")

    del model
    gc.collect()
    print("  モデルを解放しました（mmap のため RSS はすぐには戻りません）。")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション13の検証はすべて成功しました。")
