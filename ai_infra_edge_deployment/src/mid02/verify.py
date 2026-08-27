#!/usr/bin/env python3
"""中間プロジェクト2の自己検証。

検証するのは**判定と計算のロジック**であって、レイテンシの絶対値ではない。

- 区分表と参照ラベルの整合（件数・境界事例の宣言）
- 特徴量化が決定的で、20 件が異なるベクトルになること
- 出力の解釈（形式違反の3パターンを違反と判定できること）
- 測定条件の突き合わせ（揃っていない／書いていない を比較不可にできること）
- 単価と損益分岐（クラウドは件数に依存せず、エッジは件数に反比例する）
- 配布時間（サイズ比の逆数がそのまま時間比になる）
- 差の内訳（エッジであること × タスクの切り出し ＝ 全体の比）
- ハイブリッドの単調性（しきい値を上げると送信率が単調に増える）
- 成果物5点の書き出し

**同値性（fp32 と int8）の合否はアサーションしない。** 合否は環境と
モデルによって決まるもので、「合格しなければ演習が失敗」という性質のもの
ではない。ここでは判定が出せること・構造が正しいことだけを確かめ、
合否は記録して表示する。

推論サーバを使う第10節は SKIP_SERVER=1 で飛ばせる。
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.mid02.cloud_side import (  # noqa: E402
    CloudRun, Decision, PARSE_DEMO, parse_symbol, violation_reason,
)
from src.mid02.compare import (  # noqa: E402
    MUST_DECLARE, MUST_MATCH, SIZE_FP32_MB, SIZE_INT8_MB, breakeven_requests,
    check_conditions, cloud_cost_per_1k, cost_rows, distribution_seconds,
    edge_cost_per_1k, latency_breakdown,
)
from src.mid02.decision import DELIVERABLES, documents, write_all  # noqa: E402
from src.mid02.hybrid import DEMO_MARGINS, route, sweep  # noqa: E402
from src.mid02.task import (  # noqa: E402
    BORDERLINE, CATEGORIES, N_CLASSES, REFERENCE_LABELS, SYMBOLS,
    feature_matrix, featurize, label_counts,
)
from tools.prompts import QUESTIONS  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def bail() -> None:
    if failures:
        print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
        sys.exit(1)


CLOUD_COND = {"input_set": "tools/prompts.py:QUESTIONS", "n_inputs": 20,
              "output_form": "category_id+confidence",
              "measure_point": "区分IDを受け取るまで", "median_of": 3,
              "model": "qwen05b-q4_k_m.gguf", "network_roundtrip": "含む",
              "warmup": 2}
EDGE_COND = {"input_set": "tools/prompts.py:QUESTIONS", "n_inputs": 20,
             "output_form": "category_id+confidence",
             "measure_point": "区分IDを受け取るまで", "median_of": 3,
             "model": "classifier_int8.onnx(17.56MB)",
             "network_roundtrip": "含まない", "warmup": 3}

# --- 1. 区分表と参照ラベル ---------------------------------------------------
print("=== 1. 区分表と参照ラベル ===")
check("区分は6つある", len(CATEGORIES) == N_CLASSES == 6,
      "/".join(SYMBOLS))
check("参照ラベルは QUESTIONS と1対1",
      len(REFERENCE_LABELS) == len(QUESTIONS) == 20,
      f"{len(REFERENCE_LABELS)} 件")
check("参照ラベルはすべて有効な区分",
      all(0 <= x < N_CLASSES for x in REFERENCE_LABELS),
      f"件数の分布 {label_counts()}")
check("すべての区分に1件以上ある", all(n > 0 for n in label_counts()),
      f"{label_counts()}（合計 {sum(label_counts())}）")
check("境界事例は参照ラベルと別の区分を指している",
      all(alt != REFERENCE_LABELS[i] for i, (alt, _) in BORDERLINE.items()),
      f"{len(BORDERLINE)} 件")
check("境界事例の索引は範囲内",
      all(0 <= i < len(QUESTIONS) for i in BORDERLINE),
      " ".join(f"#{i + 1}" for i in sorted(BORDERLINE)))

# --- 2. 特徴量化 -------------------------------------------------------------
print("\n=== 2. 特徴量化（決定的であること）===")
mat, again = feature_matrix(), feature_matrix()
check("2回作って完全一致する（決定的）", np.array_equal(mat, again),
      f"形状 {mat.shape}")
check("次元は 384", mat.shape == (20, 384), str(mat.shape))
check("20 件が異なるベクトルになる",
      len({tuple(row.tolist()) for row in mat}) == 20,
      f"{len({tuple(row.tolist()) for row in mat})} / 20 件")
norms = np.linalg.norm(mat, axis=1)
check("L2 ノルムが 1 に正規化されている",
      bool(np.allclose(norms, 1.0, atol=1e-5)),
      f"最小 {norms.min():.6f} / 最大 {norms.max():.6f}")
check("空文字でも落ちない", featurize("").shape == (384,), "例外にしない")

# --- 3. 出力の解釈 -----------------------------------------------------------
print("\n=== 3. 出力の解釈（形式違反）===")
check("記号1文字は解釈できる", parse_symbol("C") == 2, "C -> 2")
check("前後に文字があっても解釈できる", parse_symbol("区分: E") == 4,
      "区分: E -> 4")
check("区分名が続いても解釈できる", parse_symbol("A 勤怠・休暇") == 0,
      "A 勤怠・休暇 -> 0")
check("小文字でも解釈できる", parse_symbol("f") == 5, "f -> 5")
check("記号が無ければ違反", parse_symbol("わかりません") is None,
      violation_reason("わかりません"))
check("区分が複数あれば違反", parse_symbol("A または B") is None,
      violation_reason("A または B"))
check("空文字は違反", parse_symbol("") is None, violation_reason(""))
check("同じ記号の繰り返しは違反にしない", parse_symbol("AA") == 0, "AA -> 0")
parsed = sum(1 for raw in PARSE_DEMO if parse_symbol(raw) is not None)
check("PARSE_DEMO は解釈できる3件と違反3件",
      parsed == 3 and len(PARSE_DEMO) - parsed == 3,
      f"解釈 {parsed} 件 / 違反 {len(PARSE_DEMO) - parsed} 件")

synthetic = CloudRun(tuple(
    Decision(i, REFERENCE_LABELS[i] if i % 2 == 0 else None,
             1.0 if i % 2 == 0 else 0.0, "", 100.0 + i, 10.0 + i)
    for i in range(20)))
check("解釈できた件数と違反件数の合計が総件数",
      synthetic.parsed + synthetic.violations == len(synthetic.decisions),
      f"{synthetic.parsed} + {synthetic.violations} = 20")
agree = synthetic.agreement()
check("一致は境界事例とそれ以外に分けて数える",
      agree["clear_total"] + agree["close_total"] == synthetic.parsed
      and agree["close_total"] <= len(BORDERLINE),
      f"明らかな件 {agree['clear_agree']}/{agree['clear_total']} / "
      f"境界事例 {agree['close_agree']}/{agree['close_total']}")

# --- 4. 測定条件の突き合わせ -------------------------------------------------
print("\n=== 4. 測定条件の突き合わせ ===")
m = check_conditions(CLOUD_COND, EDGE_COND)
check("揃うべき条件が揃っていれば比較可", m.comparable,
      f"{m.verdict()}（揃っている {len(m.matched)} 件）")
check("揃えられない条件は宣言済みとして数える", len(m.declared) == 3,
      " / ".join(k for k, _, _ in m.declared))
check("揃うべき条件が違えば比較不可",
      not check_conditions(CLOUD_COND, {**EDGE_COND, "median_of": 1}).comparable,
      "median_of 3 ⇔ 1")
check("入力集合が違えば比較不可",
      not check_conditions(CLOUD_COND,
                           {**EDGE_COND, "input_set": "別の集合"}).comparable,
      "input_set が不一致")
missing_cond = {k: v for k, v in EDGE_COND.items() if k != "network_roundtrip"}
missed = check_conditions(CLOUD_COND, missing_cond)
check("条件が書かれていなければ比較不可",
      not missed.comparable and missed.missing == ("network_roundtrip",),
      "network_roundtrip が未記載")
same = check_conditions(CLOUD_COND, CLOUD_COND)
check("すべて同じなら「比較可」（宣言なし）",
      same.verdict() == "比較可" and not same.declared,
      f"揃っている {len(same.matched)} 件")
check("突き合わせるキーは 5 + 3",
      len(MUST_MATCH) == 5 and len(MUST_DECLARE) == 3,
      f"{MUST_MATCH} / {MUST_DECLARE}")

# --- 5. 単価 -----------------------------------------------------------------
print("\n=== 5. 単価（相対単位）===")
cloud_1k = cloud_cost_per_1k()
check("クラウドの1000件単価は式から出る", abs(cloud_1k - 0.3511729) < 1e-6,
      f"(1 × 3) ÷ (1.13 × 3600 × 3 × 0.7) × 1000 = {cloud_1k:.6f}")
check("クラウドの単価は件数に依存しない", cloud_cost_per_1k() == cloud_1k,
      "引数を取らない（構造で保証している）")
check("エッジの単価は件数に反比例する",
      abs(edge_cost_per_1k(1_000_000) - 0.1) < 1e-12
      and abs(edge_cost_per_1k(100_000) - 1.0) < 1e-12,
      "1,000,000 件で 0.1000 / 100,000 件で 1.0000（10 倍）")
check("件数 0 では単価が定義できない",
      edge_cost_per_1k(0) == float("inf"), "無限大を返す")
be = breakeven_requests()
check("損益分岐は固定費 ÷ クラウドの1リクエスト単価",
      abs(be - 100.0 / (cloud_1k / 1000.0)) < 1e-6, f"{be:,.0f} 件")
check("分岐点でエッジとクラウドの単価が一致する",
      abs(edge_cost_per_1k(be) - cloud_1k) < 1e-9,
      f"{edge_cost_per_1k(be):.6f} = {cloud_1k:.6f}")
check("固定費を2倍にすると分岐点も2倍",
      abs(breakeven_requests(200.0) - 2 * be) < 1e-6,
      f"{be:,.0f} 件 -> {breakeven_requests(200.0):,.0f} 件")
rows = cost_rows()
check("分岐点より少ない件数ではクラウドが安い",
      all(r["cheaper"] == "クラウド" for r in rows
          if r["requests"] < be * 0.99),
      " / ".join(f"{r['requests']:,.0f}:{r['cheaper']}" for r in rows))
check("分岐点より多い件数ではエッジが安い",
      all(r["cheaper"] == "エッジ" for r in rows
          if r["requests"] > be * 1.01),
      "件数を書かずに「安い」と言えない理由がこれ")
check("分岐点の行は「同じ」と判定される",
      any(r["cheaper"] == "同じ（分岐点）" for r in rows),
      f"{be:,.0f} 件の行")

# --- 6. 配布時間 -------------------------------------------------------------
print("\n=== 6. 配布時間（理論下限）===")
sec8, sec32 = distribution_seconds(SIZE_INT8_MB), distribution_seconds(SIZE_FP32_MB)
check("int8 は fp32 より配布が速い", sec8 < sec32,
      f"{sec8:,.1f} 秒（{sec8 / 60:.1f} 分） < {sec32:,.1f} 秒"
      f"（{sec32 / 60:.1f} 分）")
check("時間比はサイズ比の逆数と一致する",
      abs(sec32 / sec8 - SIZE_FP32_MB / SIZE_INT8_MB) < 1e-9,
      f"{sec32 / sec8:.4f} 倍")
check("台数に比例する",
      abs(distribution_seconds(SIZE_INT8_MB, 2000) - 2 * sec8) < 1e-9,
      "1,000 台 -> 2,000 台で 2 倍")
check("回線を2倍にすると半分",
      abs(distribution_seconds(SIZE_INT8_MB, mbps=200.0) - sec8 / 2) < 1e-9,
      "100 Mbps -> 200 Mbps")

# --- 7. 差の内訳 -------------------------------------------------------------
print("\n=== 7. 差の内訳 ===")
b = latency_breakdown()
check("2項の積が全体の比になる",
      abs(b["edge_effect"] * b["task_effect"] - b["total_ratio"]) < 1e-6,
      f"{b['edge_effect']:.1f} 倍 × {b['task_effect']:.1f} 倍 = "
      f"{b['total_ratio']:.1f} 倍")
check("往復の物理下限は距離に比例する",
      abs(latency_breakdown(distance_km=1000.0)["rtt_floor_ms"]
          - 2 * b["rtt_floor_ms"]) < 1e-9,
      f"500 km で {b['rtt_floor_ms']:.2f} ms")
near = latency_breakdown(distance_km=50.0)
check("距離が縮むとエッジであることの効き幅が落ちる",
      near["edge_effect"] < b["edge_effect"],
      f"{b['edge_effect']:.1f} 倍 -> {near['edge_effect']:.1f} 倍"
      "（500 km -> 50 km）")
check("距離が縮むとタスクの切り出しの効き幅が相対的に大きくなる",
      near["task_effect"] > b["task_effect"],
      f"{b['task_effect']:.1f} 倍 -> {near['task_effect']:.1f} 倍"
      "（全体の比は同じなので、①が減れば②が増える）")

# --- 8. ハイブリッドの振り分け -----------------------------------------------
print("\n=== 8. ハイブリッドの振り分け ===")
check("しきい値 0 では1件も送らない", route(DEMO_MARGINS, 0.0).to_cloud == 0,
      f"0 / {len(DEMO_MARGINS)} 件")
check("しきい値 1 では全件送る",
      route(DEMO_MARGINS, 1.0).to_cloud == len(DEMO_MARGINS),
      f"{len(DEMO_MARGINS)} / {len(DEMO_MARGINS)} 件")
ratios = [r["send_ratio"] for r in sweep(DEMO_MARGINS)]
check("しきい値を上げると送信率は単調に増える",
      all(a <= b2 for a, b2 in zip(ratios, ratios[1:])),
      f"{ratios[0]:.1%} -> {ratios[-1]:.1%}")
costs = [r["cost_per_1k"] for r in sweep(DEMO_MARGINS)]
check("送信率が上がると単価も上がる",
      all(a <= b2 for a, b2 in zip(costs, costs[1:])),
      f"{costs[0]:.4f} -> {costs[-1]:.4f}")
check("全件クラウドはクラウド単独より高い", costs[-1] > cloud_1k,
      f"{costs[-1]:.4f} > {cloud_1k:.4f}（固定費と従量費の両方が乗る）")
for row in sweep(DEMO_MARGINS):
    if abs(row["threshold"] - 0.10) < 1e-9:
        check("しきい値 0.10 の行が例示のマージンから決まる",
              row["to_cloud"] == 3 and abs(row["send_ratio"] - 0.15) < 1e-9,
              f"クラウドへ 3 件（15.0%）/ 単価 {row['cost_per_1k']:.4f} / "
              f"回線断でも {row['offline_ok_per_1k']:.0f} 件")
leak = sweep(DEMO_MARGINS)
check("プライバシーとオフライン耐性は送信率と逆に動く",
      all(abs(r["leaked_per_1k"] + r["offline_ok_per_1k"] - 1000) < 1e-9
          for r in leak),
      "出る件数 + 回線断でも処理できる件数 = 1000（常に）")

# --- 9. 成果物5点 -------------------------------------------------------------
print("\n=== 9. 成果物5点 ===")
names = [name for name, _ in DELIVERABLES]
docs = documents()
check("成果物は5点そろっている",
      len(names) == 5 and set(names) == set(docs), " / ".join(names))
check("比較表に7軸すべてが入っている",
      all(k in docs["02-comparison.md"]
          for k in ("区分IDまで", "スループット", "1000件単価", "精度",
                    "オフライン耐性", "プライバシー", "運用の手間")),
      "7軸 + 測定条件 + 測っていないこと")
check("判断に逆転条件の節がある",
      "前提が変われば結論が変わる条件" in docs["03-decision.md"],
      "第4節")
check("リスク一覧に検知方法と戻し方の列がある",
      "検知方法" in docs["05-risks.md"] and "戻し方" in docs["05-risks.md"],
      "全行に埋まっている")
buffer = io.StringIO()
with tempfile.TemporaryDirectory() as tmp:
    with contextlib.redirect_stdout(buffer):
        code = write_all(tmp)
    written = sorted(p.name for p in Path(tmp).iterdir())
check("5点すべてを書き出せる", code == 0 and written == sorted(names),
      "一時ディレクトリに 5 ファイル")

bail()

# --- 10. エッジ側の実行（onnxruntime）----------------------------------------
print("\n=== 10. エッジ側の実行（合否はアサーションしない）===")
from src.mid02.edge_side import (  # noqa: E402
    DEVICE_D_LIMIT_MB, MARGIN, decisions, ensure_pair, equivalence,
    footprint_mb, probabilities,
)
from infrakit.edge import file_size_mb  # noqa: E402

fp32_path, int8_path = ensure_pair()
size32, size8 = file_size_mb(fp32_path), file_size_mb(int8_path)
check("fp32 と int8 の両方がある", size32 > 0 and size8 > 0,
      f"fp32 {size32:.2f} MB / int8 {size8:.2f} MB")
check("int8 は fp32 より小さい", size8 < size32,
      f"{size8 / size32:.1%}（サイズ比）")
fp = footprint_mb(size8)
check("端末Dの上限に収まる", fp["total_mb"] <= DEVICE_D_LIMIT_MB,
      f"{fp['total_mb']:.2f} MB <= {DEVICE_D_LIMIT_MB:.1f} MB"
      "（KVキャッシュは 0）")

p32 = probabilities(fp32_path, 1)
p8 = probabilities(int8_path, 1)
check("6クラスの確率が 20 件ぶん返る",
      p8.shape == (20, 6), str(p8.shape))
check("確率の和は 1", bool(np.allclose(p8.sum(axis=1), 1.0, atol=1e-5)),
      "softmax の出力")
check("同じ入力なら同じ出力（決定的）",
      bool(np.array_equal(p8, probabilities(int8_path, 1))),
      "2回推論して完全一致")
d8 = decisions(p8)
check("マージンは 0 以上", all(d.margin >= 0.0 for d in d8),
      f"最小 {min(d.margin for d in d8):.6f}")
check("確度は最大クラスの確率と一致する",
      all(abs(d.confidence - float(p8[i].max())) < 1e-9
          for i, d in enumerate(d8)), "softmax の最大値")

eq = equivalence(p32, p8)
check("同値性の判定を出せる",
      eq.samples == 20 and eq.clear_total + eq.close_total == 20,
      f"最大差 {eq.max_diff:.6f} / 一致 {eq.agree}/20 / "
      f"マージン {MARGIN:.2f} 以上 {eq.clear_agree}/{eq.clear_total}")
print(f"    記録: 判定は「{'合格' if eq.passed else '不合格'}」"
      "（**合否はアサーションしていません**。"
      "どう扱うかを答案に書くのが課題です）")

# 判定ロジックの健全性は、モデルに依存しない合成データで確かめる
# （実モデルの合否は環境で決まるので、そこをアサーションにしてはいけない）
REF = np.tile(np.array([0.50, 0.30, 0.10, 0.05, 0.03, 0.02],
                       dtype=np.float32), (20, 1))
SWAPPED = np.tile(np.array([0.30, 0.50, 0.10, 0.05, 0.03, 0.02],
                           dtype=np.float32), (20, 1))
perfect = equivalence(REF, REF)
check("自分自身と比べれば合格になる（判定ロジックの健全性）",
      perfect.passed and perfect.max_diff == 0.0 and perfect.agree == 20,
      "最大差 0.000000 / 一致 20/20")
broken = equivalence(REF, SWAPPED)
check("1位と2位が入れ替わった出力は不合格になる",
      not broken.passed and broken.clear_total == 20 and broken.clear_agree == 0,
      f"最大差 {broken.max_diff:.4f}（マージン {MARGIN:.2f} 以上が全件不一致）")
tiny = equivalence(REF, REF + np.float32(0.005))
check("わずかな差なら合格のまま", tiny.passed,
      f"最大差 {tiny.max_diff:.4f} <= {tiny.max_diff_limit:.3f}")

bail()

# --- 11. 推論サーバでの確認 ---------------------------------------------------
print("\n=== 11. 推論サーバでの確認（SKIP_SERVER=1 で飛ばせる）===")
if os.environ.get("SKIP_SERVER") == "1":
    print("SKIP_SERVER=1 のため推論サーバを使う検証を飛ばします。")
else:
    from infrakit.client import LlamaClient  # noqa: E402
    from src.mid02.cloud_side import classify  # noqa: E402

    client = LlamaClient()
    alive = client.health()
    check("推論サーバに接続できる", alive,
          "" if alive else "docker compose up -d llama を実行してください")
    bail()

    live = CloudRun(tuple(classify(client, QUESTIONS[i], i) for i in range(6)))
    check("6 件すべてに結果が付く", len(live.decisions) == 6, "エラーでも結果は返る")
    check("解釈できた件数と違反件数の合計が総件数",
          live.parsed + live.violations == 6,
          f"解釈 {live.parsed} 件 / 違反 {live.violations} 件"
          f"（{live.violation_rate:.1%}）")
    check("解釈できた区分はすべて有効な範囲",
          all(0 <= d.category_id < N_CLASSES
              for d in live.decisions if d.parsed),
          f"0〜{N_CLASSES - 1}")
    check("確度は2値しか取らない",
          {d.confidence for d in live.decisions} <= {0.0, 1.0},
          "言語モデルから確率が取れないため（案Aを一次判定に置けない理由）")
    check("TTFT は総時間以下",
          all(d.ttft_ms <= d.latency_ms + 1e-6 for d in live.decisions),
          "レイテンシの絶対値はアサーションしていません")
    lat = live.latency()
    print(f"    記録: 区分IDまで p50 {lat['p50']:.0f} ms / p95 {lat['p95']:.0f} ms"
          "（この環境の値。期待値にはしていません）")
    for d in live.decisions:
        if not d.parsed:
            print(f"    形式違反の実物 #{d.index + 1}: {d.raw!r}")

bail()
print("\n中間プロジェクト2の検証はすべて成功しました。")
