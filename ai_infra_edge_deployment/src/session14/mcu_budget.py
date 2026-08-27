#!/usr/bin/env python3
"""数百KBの端末に載るかを見積もる道具（セッション14）。

セッション11の `edge_budget.py` と同じ規律で数値を3種類に分ける。**混ぜてはいけない。**

  ① 実測値       : reports/ とモデルの実ファイルサイズ（測定条件つきで引用する）
  ② 決定的な計算 : 定義から一意に決まるもの（バイト数・要素数・逆算）
  ③ 前提値       : 読者が自分の端末とモデルの値を入れるもの

セッション11との違いは**池が2つある**ことだけである。マイコン級の端末では
重みは Flash（不揮発メモリ）に置き、中間テンソルは RAM に置く。
両者は別の池なので、**足し合わせて判定してはいけない。**

:::注意:::
**このファイルにマイコンの実行時間・消費電力は入っていない。** 本書はマイコンの
実機を持っていないので、時間の話を実測として書かない。ここで扱うのは
「載るか載らないか」を決める算術だけである。

    python src/session14/mcu_budget.py
"""

from __future__ import annotations

from dataclasses import dataclass

KB = 1024
MB = 1024 ** 2

# ① 引用してよい実測値（2026-08-15 実測 / aarch64 / CPU 2コア / メモリ 5.8GB /
#    Python 3.12.13 / onnxruntime 1.28.0）。ここでは比較の相手として使うだけ。
ONNX_FP32_MB = 70.13        # models/onnx/classifier_fp32.onnx の実サイズ
ONNX_INT8_MB = 17.56        # 同 int8（動的量子化）
GGUF_Q4_K_M_MB = 379.4      # models/gguf/qwen05b-q4_k_m.gguf の実サイズ

# ① セッション3の式から出る決定的な値（1トークンあたりの KVキャッシュ）
KV_PER_TOKEN_KB_05B = 12.00     # 0.5B級（層24・KVヘッド2・ヘッド次元64・f16）
KV_PER_TOKEN_KB_8B = 128.00     # 8B級（層32・KVヘッド8・ヘッド次元128・f16）
SEQ_LEN = 2048                  # ③ 前提値（セッション11 と同じ想定系列長）

# ② セッション12のモデルのパラメータ数（tools/make_edge_model.py の数え方。バイアスを除く）
C12_PARAMS = 384 * 4096 + 4096 * 4096 + 4096 * 6      # = 18,374,656

# ③ 前提値：逐次更新の統計量で異常検知する場合に端末が持つ状態
#    件数(int32) + 平均(float32) + 二乗和(float32) = 12 バイト
WELFORD_STATE_BYTES = 12


@dataclass(frozen=True)
class MCUBudget:
    """③ 前提値。マイコン級の端末の資源を2つの池に分けて持つ。

    RAM   : スタック・アプリのバッファを引いた残りがテンソルアリーナに使える
    Flash : ファームウェア本体・推論ランタイムを引いた残りが重みに使える
    """

    ram_kb: float
    flash_kb: float
    stack_kb: float
    app_ram_kb: float
    firmware_flash_kb: float
    runtime_flash_kb: float
    headroom: float = 0.2      # 余白（断片化・将来のモデル更新のため。S11 と同じ規律）

    @property
    def ram_available_kb(self) -> float:
        return max(self.ram_kb - self.stack_kb - self.app_ram_kb, 0.0)

    @property
    def arena_limit_kb(self) -> float:
        """テンソルアリーナに使ってよい上限。ここに収めるのが設計目標になる。"""
        return self.ram_available_kb * (1.0 - self.headroom)

    @property
    def flash_available_kb(self) -> float:
        return max(self.flash_kb - self.firmware_flash_kb - self.runtime_flash_kb, 0.0)

    @property
    def weights_limit_kb(self) -> float:
        """重みに使ってよい上限。"""
        return self.flash_available_kb * (1.0 - self.headroom)


# ③ 前提値：本章の共通端末。セッション11 の端末A〜D にマイコン級を1つ足したもの。
DEVICE_E = MCUBudget(ram_kb=256, flash_kb=1024, stack_kb=16, app_ram_kb=32,
                     firmware_flash_kb=256, runtime_flash_kb=64)


@dataclass(frozen=True)
class LayerModel:
    """③ 前提値の設計。パラメータ数と、入力から出力までの各テンソルの要素数。

    tensors は「入力 → 各ノードの出力」を順に並べたもの。中間テンソルのピークは
    この並びから決まるので、**層の並びを書かないとアリーナは見積もれない。**
    """

    name: str
    params: int
    tensors: tuple[int, ...]

    def weights_kb(self, bytes_per_param: float = 1.0) -> float:
        return self.params * bytes_per_param / KB

    def arena_naive_kb(self, act_bytes: int = 1) -> float:
        """素朴に全部足す。**同時に生きていないテンソルまで数える過大見積もり。**"""
        return sum(self.tensors) * act_bytes / KB

    def arena_peak_kb(self, act_bytes: int = 1) -> float:
        """ピークで数える。各ノードは「入力 + 出力」が同時に生きている。"""
        if len(self.tensors) < 2:
            return sum(self.tensors) * act_bytes / KB
        return max(a + b for a, b in zip(self.tensors, self.tensors[1:])) * act_bytes / KB


@dataclass(frozen=True)
class Verdict:
    weights_kb: float
    arena_kb: float
    flash_ok: bool
    ram_ok: bool
    flash_use: float
    ram_use: float

    @property
    def ok(self) -> bool:
        return self.flash_ok and self.ram_ok

    def text(self) -> str:
        head = "載る" if self.ok else "載らない"
        return f"{head}（Flash {self.flash_use:.1%} / RAM {self.ram_use:.1%}）"


def fits(budget: MCUBudget, model: LayerModel, bytes_per_param: float = 1.0,
         act_bytes: int = 1, naive: bool = False) -> Verdict:
    """2つの池を別々に判定する。**片方でも溢れたら載らない。**"""
    w = model.weights_kb(bytes_per_param)
    a = model.arena_naive_kb(act_bytes) if naive else model.arena_peak_kb(act_bytes)
    return Verdict(w, a, w <= budget.weights_limit_kb, a <= budget.arena_limit_kb,
                   w / budget.weights_limit_kb, a / budget.arena_limit_kb)


def fits_raw(budget: MCUBudget, weights_kb: float, arena_kb: float) -> Verdict:
    """実ファイルサイズなど、パラメータ数を経由しない数字で判定する。"""
    return Verdict(weights_kb, arena_kb,
                   weights_kb <= budget.weights_limit_kb,
                   arena_kb <= budget.arena_limit_kb,
                   weights_kb / budget.weights_limit_kb,
                   arena_kb / budget.arena_limit_kb)


def max_params(limit_kb: float, bytes_per_param: float) -> int:
    """逆算：この枠に載るパラメータ数。**量子化の強さを決めるのはこの式。**"""
    return int(limit_kb * KB / bytes_per_param)


def bytes_per_param_needed(limit_kb: float, params: int) -> float:
    """逆算：この規模を載せるには1パラメータ何バイトまで使えるか。

    0.125 バイト（＝1bit）を下回ったら、**どんな量子化をしても載らない。**
    """
    return limit_kb * KB / params


def kv_tokens(limit_kb: float, per_token_kb: float) -> int:
    """この枠に KVキャッシュを何トークン分置けるか（セッション3の式の裏返し）。"""
    return int(limit_kb / per_token_kb)


# ③ 前提値の設計。実在の学習済みモデルではなく、**層の並びだけを決めた見本**である。
MODEL_K = LayerModel("K キーワード検出（特徴量 49x40 → 5 区分）", 68_005,
                     (1_960, 15_680, 4_000, 8_000, 2_080, 32, 5))
MODEL_V = LayerModel("V 在/不在の判定（96x96）", 27_906,
                     (9_216, 36_864, 18_432, 9_216, 2_304, 2))
MODEL_W = LayerModel("W 在/不在の判定（160x160）", 27_906,
                     (25_600, 102_400, 51_200, 25_600, 6_400, 2))
MODEL_C12 = LayerModel("C12 セッション12の分類器（隠れ層 4096）", C12_PARAMS,
                       (384, 4_096, 4_096, 4_096, 4_096, 4_096, 4_096, 6, 6, 6))

MODELS = (MODEL_K, MODEL_V, MODEL_W, MODEL_C12)


# --- 表示 -------------------------------------------------------------------
def print_budget(b: MCUBudget = DEVICE_E, name: str = "端末E") -> None:
    print(f"=== {name}（マイコン級・③前提値。実測ではない）===")
    print("| 項目 | 値 |")
    print("| :--- | --: |")
    print(f"| RAM 合計 | {b.ram_kb:.2f} KB |")
    print(f"| ├ スタック | {b.stack_kb:.2f} KB |")
    print(f"| ├ アプリの変数・通信バッファ | {b.app_ram_kb:.2f} KB |")
    print(f"| └ テンソルアリーナに使える | {b.ram_available_kb:.2f} KB |")
    print(f"| テンソルアリーナの上限（余白 {b.headroom:.0%}） | {b.arena_limit_kb:.2f} KB |")
    print(f"| Flash 合計 | {b.flash_kb:.2f} KB |")
    print(f"| ├ ファームウェア本体 | {b.firmware_flash_kb:.2f} KB |")
    print(f"| ├ 推論ランタイム | {b.runtime_flash_kb:.2f} KB |")
    print(f"| └ 重みに使える | {b.flash_available_kb:.2f} KB |")
    print(f"| 重みの上限（余白 {b.headroom:.0%}） | {b.weights_limit_kb:.2f} KB |")


def print_reverse(b: MCUBudget = DEVICE_E) -> None:
    limit = b.weights_limit_kb
    base = max_params(limit, 4.0)
    print(f"\n=== 逆算：重みの上限 {limit:.2f} KB に載るパラメータ数（②決定的）===")
    print("| 1パラメータのバイト数 | 載るパラメータ数 | fp32 比 |")
    print("| :--- | --: | --: |")
    for bpp, label in ((4.0, "fp32"), (2.0, "f16"), (1.0, "int8"), (0.5, "4bit 相当")):
        n = max_params(limit, bpp)
        print(f"| {bpp}（{label}） | {n:,} | {n / base:.1f} 倍 |")
    over = C12_PARAMS / max_params(limit, 1.0)
    print(f"-> int8 にすると、同じ Flash 枠に載せられるパラメータ数が fp32 の "
          f"{max_params(limit, 1.0) / base:.1f} 倍になる。")
    print(f"-> セッション12の分類器は {C12_PARAMS:,} パラメータ（バイアスを除く）。")
    print(f"   int8 にしても、まだ {over:.1f} 倍だけ大きい。"
          "**量子化は必要条件だが十分条件ではない。**")


def print_models(b: MCUBudget = DEVICE_E) -> None:
    print("\n=== モデル候補（③前提値の設計。重み int8・中間テンソル int8）===")
    print("| モデル | パラメータ | 重み | アリーナ（ピーク） | アリーナ（素朴に合計） | 判定 |")
    print("| :--- | --: | --: | --: | --: | :--- |")
    for m in MODELS:
        v = fits(b, m)
        print(f"| {m.name} | {m.params:,} | {v.weights_kb:.2f} KB | "
              f"{v.arena_kb:.2f} KB | {m.arena_naive_kb():.2f} KB | {v.text()} |")
    w_naive = MODEL_W.arena_naive_kb()
    w_peak = MODEL_W.arena_peak_kb()
    print(f"-> W はピークで数えれば {w_peak:.2f} KB で載るが、素朴に全部足すと "
          f"{w_naive:.2f} KB になり上限 {b.arena_limit_kb:.2f} KB を超える。")
    print("   **同じモデルでも数え方で判定が変わる。**")
    print(f"-> W の余白は {b.arena_limit_kb - w_peak:.2f} KB しかない。入力を 96x96（V）に"
          f"下げると RAM の使用率は {fits(b, MODEL_V).ram_use:.1%} に落ちる。")
    print("   **入力の大きさが RAM を決める。**")
    c12 = fits(b, MODEL_C12)
    print(f"-> C12 は RAM は {c12.ram_use:.1%} で余裕があるのに、Flash が "
          f"{c12.flash_use:.1%} で溢れる。**先に溢れる池はモデルの形で変わる。**")
    print(f"-> C12 の実ファイルは {ONNX_INT8_MB} MB（{ONNX_INT8_MB * KB:,.2f} KB・①実測）で、"
          f"パラメータ数からの計算 {MODEL_C12.weights_kb():,.2f} KB より大きい。")
    print("   グラフの構造・バイアス・量子化のスケールもファイルに入るため。"
          "**最後は実ファイルサイズで上書きする。**")


def print_quant_reason(b: MCUBudget = DEVICE_E) -> None:
    print("\n=== 量子化が必須になるのは RAM 側から（モデルV）===")
    print("| 中間テンソルの型 | 重み | アリーナ（ピーク） | Flash | RAM |")
    print("| :--- | --: | --: | :--- | :--- |")
    for label, bpp, act in (("fp32", 4.0, 4), ("int8", 1.0, 1)):
        v = fits(b, MODEL_V, bytes_per_param=bpp, act_bytes=act)
        f_txt = f"{'載る' if v.flash_ok else '載らない'}（{v.flash_use:.1%}）"
        r_txt = f"{'載る' if v.ram_ok else '載らない'}（上限の {v.ram_use:.1%}）"
        print(f"| {label} | {v.weights_kb:.2f} KB | {v.arena_kb:.2f} KB | {f_txt} | {r_txt} |")
    v8 = fits(b, MODEL_V)
    print("-> 重みだけを見れば fp32 でも Flash に収まる。落ちるのは RAM 側である。")
    print(f"-> 中間テンソルのピークは重みの {v8.arena_kb / v8.weights_kb:.2f} 倍（int8）。"
          "**重みだけで見積もると必ず外す。**")


def print_llm(b: MCUBudget = DEVICE_E) -> None:
    w_kb = GGUF_Q4_K_M_MB * KB
    kv_kb = KV_PER_TOKEN_KB_05B * SEQ_LEN
    bpp = bytes_per_param_needed(b.weights_limit_kb, 500_000_000)
    print("\n=== 0.5B の言語モデルは載るか（①実測サイズ＋セッション3の式）===")
    print("| 経路 | 必要量 | 端末E の枠 | 何倍 |")
    print("| :--- | --: | --: | --: |")
    print(f"| 重み（Q4_K_M・{GGUF_Q4_K_M_MB} MB） | {w_kb:,.2f} KB | "
          f"{b.weights_limit_kb:.2f} KB | {w_kb / b.weights_limit_kb:.1f} 倍 |")
    print(f"| KVキャッシュ（系列長 {SEQ_LEN:,}） | {kv_kb:,.2f} KB | "
          f"{b.arena_limit_kb:.2f} KB | {kv_kb / b.arena_limit_kb:.1f} 倍 |")
    print(f"-> 重みの上限から逆算すると、1パラメータに使えるのは {bpp:.6f} バイト"
          f"（{bpp * 8:.4f} ビット）。")
    print(f"   1bit 量子化（0.125 バイト）でも {0.125 / bpp:.1f} 倍足りない。"
          "**量子化では解決しない。**")
    print(f"-> KVキャッシュだけを見ても、上限 {b.arena_limit_kb:.2f} KB に入るのは "
          f"{kv_tokens(b.arena_limit_kb, KV_PER_TOKEN_KB_05B)} トークン分。")
    print(f"-> 8B 級なら {kv_tokens(b.arena_limit_kb, KV_PER_TOKEN_KB_8B)} トークン分"
          f"（1トークン {KV_PER_TOKEN_KB_8B:.2f} KB）。")


def print_alternatives(b: MCUBudget = DEVICE_E) -> None:
    limit = b.arena_limit_kb
    feat_kb = MODEL_K.tensors[0] / KB
    print("\n=== LLM の代わりの選択肢（③前提値の設計）===")
    print("| 手段 | 端末に置くもの | RAM | 上限比 |")
    print("| :--- | :--- | --: | --: |")
    print(f"| 異常検知（逐次更新の統計量） | 件数・平均・二乗和の3つ | "
          f"{WELFORD_STATE_BYTES} バイト | "
          f"{WELFORD_STATE_BYTES / KB / limit:.4%} |")
    print(f"| キーワード検出（モデルK・int8） | 重み {MODEL_K.params:,} 個 | "
          f"{MODEL_K.arena_peak_kb():.2f} KB | {MODEL_K.arena_peak_kb() / limit:.1%} |")
    print(f"| 特徴量だけ作ってクラウドへ | 特徴量 49x40（int8） | "
          f"{feat_kb:.2f} KB | {feat_kb / limit:.1%} |")
    print("-> 「載らない」の答えは、必ずしも「小さいモデルを探す」ではない。"
          "**統計手法に戻すのが最も確実に載る。**")


def main() -> None:
    print_budget()
    print_reverse()
    print_models()
    print_quant_reason()
    print_llm()
    print_alternatives()


if __name__ == "__main__":
    main()
