#!/usr/bin/env python3
"""運用と判断の鎖（復習4）。

    python src/review04/ops_chain.py
    python src/review04/ops_chain.py --device E --model 0.5b
    python src/review04/ops_chain.py --device A --monthly-requests 100000 --memo

4段を一本につなぐ。**新しい式は1つも書かない。** 既存の章の関数を呼ぶだけである。

  ① 端末に載るか            -> S11（池が1つ）/ S14（池が2つ）
  ② 載らないなら何を諦めるか -> S14 の4択（詰まっている池で順序が変わる）
  ③ 配れるか                -> S15（②物理計算）
  ④ 自前で持つべきか         -> S16（①実測の動作点 × ③前提値の件数）

数値の3分類（S11 からの規律。**混ぜてはいけない**）。

  ① 実測値   : 本書の測定結果（測定条件つきで引用する）
  ② 決定的な計算: 定義・物理定数から一意に決まる値
  ③ 前提値   : 読者が自分の案件の値を入れるもの

レイテンシの絶対値はこのファイルに1つも入っていない（実行ごとに 2 倍程度ぶれるため）。
扱うのは「載るか」「配れるか」「どちらが安いか」を決める算術だけである。
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path

SANDBOX = Path(__file__).resolve().parents[2]
if str(SANDBOX) not in sys.path:
    sys.path.insert(0, str(SANDBOX))

from src.session09.scaling import MEASURED_CONDITIONS  # noqa: E402
from src.session11.edge_budget import (  # noqa: E402
    Footprint, MemoryBudget, fits as fits_mb,
)
from src.session14.mcu_budget import (  # noqa: E402
    DEVICE_E, GGUF_Q4_K_M_MB, KB, KV_PER_TOKEN_KB_05B, MODEL_C12, ONNX_INT8_MB,
    SEQ_LEN, bytes_per_param_needed, fits_raw, kv_tokens,
)
from src.session15.fleet import (  # noqa: E402
    CLIENT_TIMEOUT_S, DEVICE_COUNT, LINE_MBPS, OBSERVE_HOURS,
    max_parallel_for_timeout, per_device_seconds, plan_elapsed_hours, stage_plan,
    total_gb, transfer_seconds, waves,
)
from src.session16.decision import (  # noqa: E402
    MODE_AUTO, MODE_FIXED, POINT, SECONDS_PER_MONTH, Inputs, api_cost_per_1k,
    self_cost_per_1k, self_is_cheaper,
)

# --- ③ 前提値：S11 の共通端末（数値を変えると章をまたいだ比較が壊れる）--------
DEVICES: dict[str, MemoryBudget] = {
    "A": MemoryBudget(total_mb=4096, os_reserved_mb=1024, other_apps_mb=1536),
    "B": MemoryBudget(total_mb=2048, os_reserved_mb=768, other_apps_mb=512),
    "C": MemoryBudget(total_mb=8192, os_reserved_mb=1024, other_apps_mb=1024),
    "D": MemoryBudget(total_mb=1024, os_reserved_mb=256, other_apps_mb=128),
}

RUNTIME_CLASSIFIER_MB = 50.0    # ③ 前提値（S11）
RUNTIME_LLM_MB = 150.0          # ③ 前提値（S11）
KV_05B_MB = KV_PER_TOKEN_KB_05B * SEQ_LEN / KB      # ② 24.0 MB（S03 の式）

FOOTPRINTS: dict[str, Footprint] = {
    "classifier": Footprint(weights_mb=ONNX_INT8_MB, kv_mb=0.0,
                            runtime_mb=RUNTIME_CLASSIFIER_MB),
    "0.5b": Footprint(weights_mb=GGUF_Q4_K_M_MB, kv_mb=KV_05B_MB,
                      runtime_mb=RUNTIME_LLM_MB),
}
MODEL_LABELS = {"classifier": "分類器 int8", "0.5b": "0.5B Q4_K_M"}

# 端末E（マイコン級）で RAM 側に置くもの。分類器は中間テンソルのピーク、
# 言語モデルは KVキャッシュ（系列長 2,048 分）である。
ARENA_KB: dict[str, float] = {
    "classifier": MODEL_C12.arena_peak_kb(),
    "0.5b": KV_PER_TOKEN_KB_05B * SEQ_LEN,
}

FLASH = "Flash（重み）"
RAM = "RAM（アリーナ）"
SINGLE = "メモリ（1つの池）"

# 載らないときに取れる手。**詰まっている池で並び順が変わる**のが要点である。
OPTIONS_BY_POOL: dict[str, tuple[str, ...]] = {
    FLASH: (
        "① もっと強く量子化する（先に逆算して、そもそも届くかを確かめる）",
        "② パラメータ数の少ないモデルに替える（タスクの難易度を下げる）",
        "③ 端末のクラスを上げる（Flash の大きい品種にする＝調達の話になる）",
        "④ タスクを分ける（端末では特徴量だけ作り、判定はクラウドで行う）",
    ),
    RAM: (
        "① 入力を小さくする（**RAM を決めるのは重みではなく入力**）",
        "② 中間テンソルの型を下げる（活性化も int8 にする）",
        "③ 端末のクラスを上げる（RAM の大きい品種にする）",
        "④ 統計手法に戻す（逐次更新の統計量なら数十バイトで済む）",
    ),
    SINGLE: (
        "① 量子化を強める（重みが支配的なので効きが大きい）",
        "② 系列長を短くする（KVキャッシュは系列長に比例する）",
        "③ 端末のクラスを上げる（余白 20% を確保できる品種にする）",
        "④ タスクを分ける（一次判定だけ端末・生成はクラウド）",
    ),
}


# ---------------------------------------------------------------------------
# 1. 端末に載るか（S11 / S14）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Fit:
    """判定の結果。**池が1つの端末と2つの端末で、同じ形にそろえる。**

    形をそろえないと、呼ぶ側に `if device == "E"` が生える。端末を1つ増やす
    たびに分岐が増える設計は、半年で読めなくなる。
    """

    device: str
    model: str
    pools: int          # 1（OS のある端末）/ 2（マイコン級）
    ok: bool
    tight_pool: str     # いちばん詰まっている池
    over: float         # その池の上限に対する比（1.0 を超えたら載らない）
    slack: str          # 余白（単位が池ごとに違うので文字列で持つ）
    detail: str         # 人が読む1行


def fit_of(device: str, model: str = "classifier") -> Fit:
    """端末に載るかを判定する。**端末E だけは池が2つある。**"""
    if model not in FOOTPRINTS:
        raise ValueError(f"model は {sorted(FOOTPRINTS)} のいずれかです: {model!r}")

    if device == "E":
        weights_kb = FOOTPRINTS[model].weights_mb * KB
        arena_kb = ARENA_KB[model]
        verdict = fits_raw(DEVICE_E, weights_kb, arena_kb)   # S14：別々に判定
        tight = FLASH if verdict.flash_use >= verdict.ram_use else RAM
        slack = (f"Flash {DEVICE_E.weights_limit_kb - weights_kb:+,.2f} KB / "
                 f"RAM {DEVICE_E.arena_limit_kb - arena_kb:+,.2f} KB")
        detail = (f"Flash {weights_kb:,.2f} / {DEVICE_E.weights_limit_kb:,.2f} KB"
                  f"（{verdict.flash_use:,.2f} 倍）、"
                  f"RAM {arena_kb:,.2f} / {DEVICE_E.arena_limit_kb:,.2f} KB"
                  f"（{verdict.ram_use:,.2f} 倍）")
        return Fit("端末E", MODEL_LABELS[model], 2, verdict.ok, tight,
                   max(verdict.flash_use, verdict.ram_use), slack, detail)

    if device not in DEVICES:
        raise ValueError("device は "
                         f"{sorted(DEVICES) + ['E']} のいずれかです: {device!r}")
    budget, fp = DEVICES[device], FOOTPRINTS[model]
    ok, margin = fits_mb(budget, fp)                          # S11：1つの池
    over = fp.total_mb / budget.limit_mb
    detail = (f"重み {fp.weights_mb:,.2f} ＋ KVキャッシュ {fp.kv_mb:,.2f} ＋ "
              f"実行時 {fp.runtime_mb:,.2f} = {fp.total_mb:,.2f} MB / 上限 "
              f"{budget.limit_mb:,.2f} MB（{over:.1%}）")
    return Fit(f"端末{device}", MODEL_LABELS[model], 1, ok, SINGLE, over,
               f"{margin:+,.2f} MB", detail)


def options_when_unfit(fit: Fit) -> list[str]:
    """載らないときに取れる手を、詰まっている池に応じた順序で返す。"""
    if fit.ok:
        return [f"載るので選択肢は不要（余白 {fit.slack}）。"
                "ただし余白が小さい構成は他アプリが増えた時点で壊れる"]
    return list(OPTIONS_BY_POOL[fit.tight_pool])


def quantization_note(params: int = 500_000_000) -> str:
    """逆算：端末E の枠にこの規模を載せるには1パラメータ何バイトまで使えるか。"""
    limit = DEVICE_E.weights_limit_kb
    bpp = bytes_per_param_needed(limit, params)
    return (f"端末E の重みの枠 {limit:.2f} KB に {params:,} パラメータを載せるには "
            f"1パラメータ {bpp:.6f} バイト（{bpp * 8:.4f} ビット）まで。"
            f"1bit 量子化（0.125 バイト）でも {0.125 / bpp:.1f} 倍足りない")


def kv_note() -> str:
    """端末E のアリーナ上限に KVキャッシュを何トークン置けるか（S03 の式の裏返し）。"""
    limit = DEVICE_E.arena_limit_kb
    return (f"端末E のアリーナ上限 {limit:.2f} KB に置ける KVキャッシュは "
            f"0.5B で {kv_tokens(limit, KV_PER_TOKEN_KB_05B)} トークン分、"
            f"8B級で {kv_tokens(limit, 128.00)} トークン分")


# ---------------------------------------------------------------------------
# 2. 配れるか（S15・②物理計算）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Distribution:
    """配布の見積り。ここに①実測は入らない（入力のサイズだけが①）。"""

    size_mb: float
    devices: int
    mbps: float
    timeout_s: float
    total_gb: float
    seconds: float
    max_parallel: int
    waves_at_max: int
    seconds_per_device_at_max: float
    stage_added: tuple[int, ...]
    stage_seconds: tuple[float, ...]
    elapsed_hours: float


def distribution(size_mb: float, devices: int = DEVICE_COUNT,
                 mbps: float = LINE_MBPS, timeout_s: float = CLIENT_TIMEOUT_S,
                 observe_hours: float = OBSERVE_HOURS) -> Distribution:
    """配るのは**重みのファイルだけ**である（実行時メモリは回線に流れない）。"""
    if devices < 1:
        raise ValueError("devices は 1 以上にしてください")
    if timeout_s <= 0:
        raise ValueError("timeout_s は正の値にしてください")
    seconds = transfer_seconds(size_mb, devices, mbps)   # size_mb / mbps もここで検査
    limit = max_parallel_for_timeout(size_mb, timeout_s, mbps)
    if limit < 1:
        raise ValueError("このサイズと回線ではタイムアウトを守れる同時台数が 0 です"
                         "（差分配信にするか、タイムアウトを見直してください）")
    stages = stage_plan(total=devices, size_mb=size_mb, mbps=mbps,
                        observe_hours=observe_hours)
    return Distribution(
        size_mb=size_mb, devices=devices, mbps=mbps, timeout_s=timeout_s,
        total_gb=total_gb(size_mb, devices), seconds=seconds,
        max_parallel=limit, waves_at_max=waves(devices, limit),
        seconds_per_device_at_max=per_device_seconds(size_mb, limit, mbps),
        stage_added=tuple(stage.added for stage in stages),
        stage_seconds=tuple(stage.seconds for stage in stages),
        elapsed_hours=plan_elapsed_hours(stages))


# ---------------------------------------------------------------------------
# 3. 自前で持つべきか（S16・①実測 × ③前提値）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Economics:
    """単価と、**整数の段差**。感度分析を走査しなくても段差は閉じた式で出る。"""

    monthly_requests: float
    avg_rps: float
    per_instance_rps: float
    instances_auto: int
    instances_fixed: int
    utilization_auto: float
    utilization_fixed: float
    cost_auto: float
    cost_fixed: float
    api_cost: float
    cheaper: bool
    step_up_monthly: float      # 台数が1本増える月間件数
    step_down_rps: float        # 1本あたりの動作点がここまで落ちると台数が1本増える
    step_down_pct: float        # いまの 1本の rps からの変化率（%）
    floor_binding: bool         # 台数が需要ではなく下限で決まっているか


def economics(monthly_requests: float = 10_000_000.0) -> Economics:
    """月間件数から台数・利用率・単価・段差を出す。式はすべて S16 のものを使う。"""
    inp = Inputs(monthly_requests)          # 0 以下・不正な前提はここで例外になる
    n_auto = inp.instances(MODE_AUTO)
    step_down = inp.avg_rps / n_auto
    return Economics(
        monthly_requests=monthly_requests,
        avg_rps=inp.avg_rps,
        per_instance_rps=inp.per_instance_rps,
        instances_auto=n_auto,
        instances_fixed=inp.instances(MODE_FIXED),
        utilization_auto=inp.utilization(MODE_AUTO),
        utilization_fixed=inp.utilization(MODE_FIXED),
        cost_auto=self_cost_per_1k(inp, MODE_AUTO),
        cost_fixed=self_cost_per_1k(inp, MODE_FIXED),
        api_cost=api_cost_per_1k(inp),
        cheaper=self_is_cheaper(inp, MODE_AUTO),
        step_up_monthly=n_auto * inp.per_instance_rps * SECONDS_PER_MONTH,
        step_down_rps=step_down,
        step_down_pct=(step_down / inp.per_instance_rps - 1.0) * 100.0,
        floor_binding=math.ceil(inp.avg_rps / inp.per_instance_rps) < n_auto)


# ---------------------------------------------------------------------------
# 4. 鎖としてつなぐ
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Chain:
    fit: Fit
    options: tuple[str, ...]
    dist: Distribution
    econ: Economics


def chain(device: str = "D", model: str = "classifier",
          devices: int = DEVICE_COUNT, mbps: float = LINE_MBPS,
          timeout_s: float = CLIENT_TIMEOUT_S,
          monthly_requests: float = 10_000_000.0) -> Chain:
    """4段を1本につなぐ。**入力を1つ変えたら下流が全部動く**のがこの関数の価値。"""
    fit = fit_of(device, model)
    return Chain(fit=fit, options=tuple(options_when_unfit(fit)),
                 dist=distribution(FOOTPRINTS[model].weights_mb, devices, mbps,
                                   timeout_s),
                 econ=economics(monthly_requests))


def report(ch: Chain) -> str:
    """標準出力に出す4段の結果。"""
    f, d, e = ch.fit, ch.dist, ch.econ
    lines = [
        "=== 運用と判断の鎖（復習4）===",
        f"測定条件: {MEASURED_CONDITIONS}",
        "",
        "[1] 端末に載るか（S11 / S14）",
        f"  対象      : {f.device} × {f.model}（池は {f.pools} つ）",
        f"  内訳      : {f.detail}",
        f"  判定      : {'載る' if f.ok else '載らない'}（余白 {f.slack}）",
        f"  詰まる池  : {f.tight_pool}／上限比 {f.over:,.2f} 倍",
        "",
        "[2] 載らないときに取れる手（S14）",
    ]
    lines += [f"  - {text}" for text in ch.options]
    lines += [
        "",
        "[3] 配れるか（S15・②物理計算）",
        f"  配るもの  : 重み {d.size_mb:,.2f} MB × {d.devices:,} 台 = "
        f"{d.total_gb:,.2f} GB",
        f"  所要      : {d.seconds:,.1f} 秒（{d.seconds / 60:.1f} 分・回線 "
        f"{d.mbps:.1f} Mbps を専有）",
        f"  同時上限  : {d.max_parallel:,} 台（タイムアウト {d.timeout_s:.0f} 秒／"
        f"1台 {d.seconds_per_device_at_max:,.1f} 秒）-> {d.waves_at_max:,} 波",
        "  段階展開  : " + " -> ".join(
            f"{added:,} 台（{sec:,.1f} 秒）"
            for added, sec in zip(d.stage_added, d.stage_seconds)),
        f"  観察込み  : {d.elapsed_hours:,.1f} 時間",
        "",
        "[4] 自前で持つべきか（S16・①実測 × ③前提値）",
        f"  月間件数  : {e.monthly_requests:,.0f} 件（平均 {e.avg_rps:.4f} rps / "
        f"1本 {e.per_instance_rps:.4f} rps）",
        f"  台数      : オートスケール {e.instances_auto} 本（利用率 "
        f"{e.utilization_auto:.1%}）／固定 {e.instances_fixed} 本（利用率 "
        f"{e.utilization_fixed:.1%}）",
        f"  単価      : 自前 {e.cost_auto:.4f}（オート）／{e.cost_fixed:.4f}（固定）／"
        f"API {e.api_cost:.4f}",
        "  判定      : " + ("オートスケールなら自前が安い" if e.cheaper
                            else "オートスケールでも API のほうが安い"),
        f"  整数の段差: 台数が1本増えるのは {e.step_up_monthly / 10000:,.1f} 万件から／"
        f"動作点が {e.step_down_rps:.4f} rps（1本）まで落ちたとき"
        f"（{e.step_down_pct:+.1f}%）"
        + ("。いまは下限が効いているので段差までの余裕は大きい"
           if e.floor_binding else ""),
    ]
    return "\n".join(lines)


def table(ch: Chain) -> str:
    """鎖を Markdown の表にする。**根拠の列を落とさない。**"""
    f, d, e = ch.fit, ch.dist, ch.econ
    rows = [
        ("① 端末に載るか", f"{f.device} × {f.model}",
         f"{'載る' if f.ok else '載らない'}（上限比 {f.over:,.2f} 倍）", "S11 / S14"),
        ("② 諦めるもの", f"詰まっている池: {f.tight_pool}",
         ch.options[0], "S14"),
        ("③ 配れるか", f"重み {d.size_mb:,.2f} MB × {d.devices:,} 台",
         f"{d.seconds:,.1f} 秒／同時上限 {d.max_parallel:,} 台", "S15"),
        ("④ 自前で持つべきか", f"月 {e.monthly_requests:,.0f} 件",
         f"自前 {e.cost_auto:.4f} / API {e.api_cost:.4f}"
         f"（{'自前が安い' if e.cheaper else 'API が安い'}）", "S09 / S10 / S16"),
    ]
    lines = ["| 段 | 入力 | 出力 | 根拠 |", "| :--- | :--- | :--- | :--- |"]
    lines += [f"| {a} | {b} | {c} | {src} |" for a, b, c, src in rows]
    return "\n".join(lines)


def memo(ch: Chain) -> str:
    """引き継げる Markdown。**種別（①②③）と再計算手順を必ず含める。**"""
    f, d, e = ch.fit, ch.dist, ch.econ
    return "\n".join([
        "# 運用と判断の鎖（復習4）",
        "",
        f"- 測定条件：{MEASURED_CONDITIONS}",
        "- **絶対値は再現しません。** レイテンシは同じ環境でも実行ごとに 2 倍程度"
        "ぶれます。ここに載せているのは、ぶれない算術（載るか・配れるか・段差）だけです。",
        "",
        "## 1. 前提（種別を混ぜない）",
        "",
        "| 入力 | 値 | 種別 |",
        "| :--- | --: | :--- |",
        f"| 動作点の rps | 並列{POINT.concurrency}・{POINT.throughput_rps}"
        f"（1本の安全な能力 {e.per_instance_rps:.4f}） | ① 実測 |",
        f"| 配るモデルのサイズ | {d.size_mb:,.2f} MB | ① 実測（ファイルサイズ） |",
        f"| KVキャッシュ（系列長 {SEQ_LEN:,}） | {KV_05B_MB:.2f} MB | ② 決定的な計算 |",
        f"| 端末の上限 | {f.detail} | ③ 前提値 |",
        f"| 台数・回線・タイムアウト | {d.devices:,} 台 / {d.mbps:.1f} Mbps / "
        f"{d.timeout_s:.0f} 秒 | ③ 前提値 |",
        f"| 月間リクエスト数 | {e.monthly_requests:,.0f} 件 | ③ 前提値 |",
        "| ピークが平均の何倍か | 3.0 倍 | ③ 前提値（**未実測**） |",
        "",
        "## 2. 鎖の結果",
        "",
        table(ch),
        "",
        "## 3. 気づき",
        "",
        f"- 段階展開に分けても配布時間の合計は変わらない（{d.seconds:,.1f} 秒）。"
        "減るのは「間違った版が届く台数」であって帯域ではない",
        f"- 同時台数の上限 {d.max_parallel:,} 台を超えると 1 台あたりの所要が"
        f"タイムアウト {d.timeout_s:.0f} 秒を超え、全台が再送を始める（リトライストーム）",
        f"- 台数は整数なので、動作点が {e.step_down_pct:+.1f}% 動くだけで結論が"
        "反転しうる。**測定のぶれと区別できない大きさである**",
        f"- {quantization_note()}",
        f"- {kv_note()}",
        "",
        "## 4. 再計算手順",
        "",
        "1. `src/session04/sweep.py` で同時実行を振り、**SLO を満たす最大の点**を"
        "動作点に採る",
        "2. `src/session09/plan.py` で台数を数え直す",
        "3. `src/session10/cost_report.py` で単価と損益分岐を出し直す",
        "4. `src/review04/ops_chain.py --memo` で本メモを再生成する",
        "5. 段差（月間件数と動作点）が変わったら、再判断のトリガーのしきい値を"
        "書き換える",
    ])


# ---------------------------------------------------------------------------
# 5. CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="運用と判断の鎖（復習4）")
    parser.add_argument("--device", default="D",
                        choices=sorted(DEVICES) + ["E"])
    parser.add_argument("--model", default="classifier",
                        choices=sorted(FOOTPRINTS))
    parser.add_argument("--devices", type=int, default=DEVICE_COUNT)
    parser.add_argument("--mbps", type=float, default=LINE_MBPS)
    parser.add_argument("--timeout", type=float, default=CLIENT_TIMEOUT_S)
    parser.add_argument("--monthly-requests", type=float, default=10_000_000.0)
    parser.add_argument("--memo", action="store_true",
                        help="引き継げる Markdown を出す")
    args = parser.parse_args(argv)

    try:
        built = chain(device=args.device, model=args.model, devices=args.devices,
                      mbps=args.mbps, timeout_s=args.timeout,
                      monthly_requests=args.monthly_requests)
    except ValueError as err:
        print(f"前提が不正です: {err}", file=sys.stderr)
        return 2

    print(memo(built) if args.memo else report(built))
    return 0


if __name__ == "__main__":
    sys.exit(main())
