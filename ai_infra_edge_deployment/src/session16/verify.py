#!/usr/bin/env python3
"""セッション16の自己検証。

    python src/session16/verify.py

検証するのは**決定的な計算と、そこから出る関係だけ**である。レイテンシのような
環境依存の絶対値は期待値に書かない（本書の全章共通の作法）。ここに出る数字は

  - ①実測値（動作点 1.13 rps・量子化後のファイルサイズ）を入力にした算術
  - ②物理計算（往復の下限・転送量）
  - ③前提値（件数・人員・軸のスコア）

のいずれかなので、誰の環境でも同じ値になる。**外部ネットワークには触らない。**
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from decision import (  # noqa: E402
    API, AXES, DECISIONS, EDGE, FOOTPRINTS, HOURS_PER_MONTH, HYBRID, MODE_AUTO,
    MODE_FIXED, OPTIONS, POINT, SCAN_SPAN, SCENARIOS, SELF, STAFF_NEEDED,
    STAGES, WEIGHTS, Inputs, Stage, Trigger, api_cost_per_1k, breakeven,
    cost_ratio, device_ratio, document_markdown, fits,
    flips, footprint_mb, fragility_order, gate_reasons, mcu_flash_ratio,
    missing_sections, observe_days_total, ranking, ratios_monotonic, score_of,
    self_cost_per_1k, self_is_cheaper, survivors, triggers_for, weighted_score,
)

failures: list[str] = []
checked = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global checked
    checked += 1
    print(f"{'OK' if cond else 'NG'} {label}" + (f" — {detail}" if detail else ""))
    if not cond:
        failures.append(label)


def raises(fn) -> bool:
    """例外になることを確かめる。**黙って受け取らない**ことの検証。"""
    try:
        fn()
    except ValueError:
        return True
    return False


def axis_record(sc, a: str, b: str) -> tuple[int, int]:
    """8軸を1対1で数えて（勝ち, 負け）を返す。同点は数えない。

    採点表がある案を構造的に有利にしていないかを見るための道具。
    """
    wins = sum(1 for ax in AXES
               if score_of(sc, a, ax.key) > score_of(sc, b, ax.key))
    losses = sum(1 for ax in AXES
                 if score_of(sc, a, ax.key) < score_of(sc, b, ax.key))
    return wins, losses


S1, S2, S3 = SCENARIOS["s1"], SCENARIOS["s2"], SCENARIOS["s3"]

print("=== セッション16：自己検証 ===")

# --- [1] 前提 ---------------------------------------------------------------
print("\n[1] 前提（数値の種別を混ぜない）")
check("動作点は実測値をそのまま使う",
      POINT.concurrency == 2 and POINT.throughput_rps == 1.13,
      f"並列{POINT.concurrency} / TTFT p95 {POINT.ttft_p95_ms:.0f} ms / "
      f"{POINT.throughput_rps} rps / TPOT {POINT.tpot_p50_ms} ms")
check("1本の能力はヘッドルームを引いた 0.791 rps",
      abs(S2.inputs.per_instance_rps - 0.791) < 1e-9,
      f"{S2.inputs.per_instance_rps:.4f} rps")
check("月間件数から平均 rps が出る",
      abs(S2.inputs.avg_rps - 3.8580246913580245) < 1e-9
      and abs(S2.inputs.requests_per_hour - 13888.888888888889) < 1e-6,
      f"{S2.inputs.monthly_requests:,.0f} 件 -> {S2.inputs.avg_rps:.4f} rps "
      f"({S2.inputs.requests_per_hour:,.2f} 件/時)")
check("軸は8本で、そのうち4本がゲートとしても働く",
      len(AXES) == 8 and sum(1 for a in AXES if a.is_gate) == 4,
      "／".join(a.name for a in AXES if a.is_gate))
check("選択肢は4案（ハイブリッドを忘れない）", len(OPTIONS) == 4,
      "／".join(OPTIONS))
check("前提が不正なら黙って受け取らない",
      raises(lambda: Inputs(monthly_requests=0))
      and raises(lambda: Inputs(monthly_requests=100, peak_factor=0.5)))

# --- [2] ゲート -------------------------------------------------------------
print("\n[2] ゲート（採点より先に効く）")
r_api, r_self = gate_reasons(S3, API), gate_reasons(S3, SELF)
check("S3 のクラウド側は2つの理由で落ちる",
      len(r_api) == 2 and len(r_self) == 2,
      f"クラウドAPI: {len(r_api)} 件 / 自前ホスティング: {len(r_self)} 件")
check("理由は打ち切らずに全部返る",
      any("オフライン" in x for x in r_api)
      and any("生データ" in x for x in r_api),
      "／".join(r_api))
check("S3 のレイテンシのゲートは通る（失格の理由はレイテンシではない）",
      not any("往復" in x for x in r_api),
      "1,000 km の往復の下限 10.0 ms は SLO 100 ms の 10.0%（②物理計算）")
check("8B級はエッジのゲートで落ちる",
      not any(o == EDGE for o in survivors(S1)) and device_ratio(S1, "8b") > 1.0,
      f"{footprint_mb('8b'):,.2f} MB は{S1.device_name} の上限の "
      f"{device_ratio(S1, '8b'):.1f} 倍")
check("S1 のハイブリッドは人員のゲートで落ちる",
      any("運用人員" in x for x in gate_reasons(S1, HYBRID)),
      f"必要 {STAFF_NEEDED[HYBRID]} 人 > {S1.staff} 人")
ok_d, margin_d = fits(S3.device, FOOTPRINTS["classifier"])
check("分類器 int8 は端末D に載る", ok_d,
      f"{footprint_mb('classifier'):,.2f} MB ≦ {S3.device.limit_mb:,.2f} MB"
      f"（余白 {margin_d:,.2f} MB）")
check("同じ分類器がマイコン級（端末E）には載らない",
      mcu_flash_ratio("classifier") > 1.0,
      f"Flash 上限の {mcu_flash_ratio('classifier'):.1f} 倍")
check("0.5B は端末A に載るが端末D には載らない",
      fits(S1.device, FOOTPRINTS["0.5b"])[0]
      and not fits(S3.device, FOOTPRINTS["0.5b"])[0],
      f"{footprint_mb('0.5b'):,.2f} MB / 端末A {S1.device.limit_mb:,.2f} MB / "
      f"端末D {S3.device.limit_mb:,.2f} MB")
check("生き残る案はシナリオごとに変わる",
      survivors(S1) == [API, SELF] and survivors(S2) == [API, SELF, HYBRID]
      and survivors(S3) == [EDGE, HYBRID],
      f"S1 {survivors(S1)} / S2 {survivors(S2)} / S3 {survivors(S3)}")
check("ゲートで落ちた案は採点できない（点数で埋め合わせられない）",
      raises(lambda: weighted_score(S3, API, WEIGHTS[0])),
      "スコアが満点でも失格は失格")

# --- [3] 単価と損益分岐 -----------------------------------------------------
print("\n[3] 単価と損益分岐")
n_fixed, n_auto = S2.inputs.instances(MODE_FIXED), S2.inputs.instances(MODE_AUTO)
c_fixed = self_cost_per_1k(S2.inputs, MODE_FIXED)
c_auto = self_cost_per_1k(S2.inputs, MODE_AUTO)
api_1k = api_cost_per_1k(S2.inputs)
check("単価は運転の仕方で反転する",
      n_fixed == 15 and n_auto == 5 and c_fixed > api_1k > c_auto,
      f"固定{n_fixed}本 {c_fixed:.4f} / オートスケール{n_auto}本 {c_auto:.4f} / "
      f"API {api_1k:.4f}")
check("単価は台数に比例する（利用率が件数で決まるとき）",
      abs(c_fixed / c_auto - n_fixed / n_auto) < 1e-9,
      f"{c_fixed / c_auto:.2f} 倍 = {n_fixed} ÷ {n_auto}")
check("利用率は台数の決め方で変わる",
      abs(S2.inputs.utilization(MODE_AUTO) - 0.6828) < 1e-3
      and abs(S2.inputs.utilization(MODE_FIXED) - 0.2276) < 1e-3,
      f"固定 {S2.inputs.utilization(MODE_FIXED) * 100:.1f}% / "
      f"オートスケール {S2.inputs.utilization(MODE_AUTO) * 100:.1f}%")
be1, be2 = breakeven(S1.inputs.assumptions()), breakeven(S2.inputs.assumptions())
check("S1 は自前が API の 36.59 倍",
      not self_is_cheaper(S1.inputs) and abs(cost_ratio(S1, SELF) - 36.5854) < 1e-3,
      f"自前 {self_cost_per_1k(S1.inputs):.4f} / API {api_cost_per_1k(S1.inputs):.4f}"
      f" = {cost_ratio(S1, SELF):.2f} 倍")
ratio_needed = be1.requests_per_hour * HOURS_PER_MONTH / S1.inputs.monthly_requests
check("単価の比は「損益分岐までに必要な件数の倍率」と一致する",
      abs(ratio_needed - cost_ratio(S1, SELF)) < 1e-6,
      f"{be1.requests_per_hour * HOURS_PER_MONTH / 10000:,.1f}万件 ÷ "
      f"{S1.inputs.monthly_requests / 10000:,.1f}万件 = {ratio_needed:.2f} 倍")
check("損益分岐は能力の内側（需要が増えれば到達できる）",
      be1.achievable and be2.achievable,
      f"S1 {be1.requests_per_hour:,.2f} ≦ {be1.capacity_per_hour:,.1f} 件/時 / "
      f"S2 {be2.requests_per_hour:,.2f} ≦ {be2.capacity_per_hour:,.1f} 件/時")
check("損益分岐の利用率は台数に依存しない",
      abs(be1.utilization - be2.utilization) < 1e-9,
      f"S1 {be1.utilization * 100:.1f}% = S2 {be2.utilization * 100:.1f}%"
      "（固定費と API 単価だけで決まる）")

# --- [4] 感度分析 -----------------------------------------------------------
print("\n[4] 感度分析（どの前提が結論を変えるか）")
order = fragility_order(S2)
top = order[0]
by_field = {f.field: f for f in flips(S2)}
check("いちばん脆い前提は価格ではなく動作点",
      top.field == "point_rps",
      f"{top.label}：{top.nearest_pct:+.1f}% で反転")
check("上位2つは同じ境目（台数が1本増える点）",
      {order[0].field, order[1].field} == {"point_rps", "monthly_requests"},
      f"{order[0].label} {order[0].nearest_pct:+.1f}% / "
      f"{order[1].label} {order[1].nearest_pct:+.1f}%")
check("反転する動作点は 0.7716 rps（1本）",
      abs(by_field["point_rps"].value_at("down") - 0.7716049382716049) < 1e-6,
      f"{by_field['point_rps'].base_value:.4f} -> "
      f"{by_field['point_rps'].value_at('down'):.4f} rps")
check("感度は非対称（良くなる側では反転しない）",
      by_field["point_rps"].up is None
      and self_is_cheaper(replace(S2.inputs,
                                  point_rps=S2.inputs.point_rps * 1.1)),
      "動作点の rps を +10% しても結論は変わらない")
up_m = by_field["monthly_requests"].up
after = replace(S2.inputs, monthly_requests=S2.inputs.monthly_requests * up_m)
check("件数と単価の関係は単調でない",
      after.instances() == 6 and not self_is_cheaper(after),
      f"件数 {by_field['monthly_requests'].nearest_pct:+.1f}% で台数が"
      f"{after.instances()}本になり反転する")
check("減る側の反転は損益分岐と一致する",
      abs(by_field["monthly_requests"].value_at("down")
          - be2.requests_per_hour * HOURS_PER_MONTH) < 1.0,
      f"{by_field['monthly_requests'].value_at('down') / 10000:,.1f}万件")
check("価格の前提は動作点より堅い",
      by_field["hourly_cost"].fragility > top.fragility
      and by_field["api_output_price_per_1m"].fragility > top.fragility,
      f"インスタンス時間単価 {by_field['hourly_cost'].nearest_pct:+.1f}% / "
      f"API の出力トークン単価 "
      f"{by_field['api_output_price_per_1m'].nearest_pct:+.1f}%")
check("オートスケールではピーク倍率は結論を変えない",
      by_field["peak_factor"].nearest is None,
      f"±{SCAN_SPAN * 100:.0f}% の範囲で反転しない（台数は平均から決まる）")
check("S1 の結論はどの前提でも反転しない（桁で開いた差は消えない）",
      all(f.nearest is None for f in flips(S1)),
      f"±{SCAN_SPAN * 100:.0f}% の範囲で反転する前提が1つも無い")
check("単価の比較対象が無いシナリオでは感度分析をしない",
      raises(lambda: flips(S3)), "S3 は本書のトークン単価の形が当てはまらない")

# --- [5] 重み付きスコア -----------------------------------------------------
print("\n[5] 重み付きスコア")
wa, wb = WEIGHTS
top_a, top_b = ranking(S1, wa)[0], ranking(S1, wb)[0]
check("重みを変えると1位が入れ替わる",
      top_a[0] == API and top_b[0] == SELF,
      f"{wa.key}: {top_a[0]} {top_a[1]:.2f} / {wb.key}: {top_b[0]} {top_b[1]:.2f}")
check("単価が 36.59 倍高い案が1位になることがある",
      top_b[0] == SELF and cost_ratio(S1, SELF) > 30,
      "スコアが 1〜5 に圧縮されるので、桁違いの差が総合点に現れない"
      "（→ ゲートに昇格させる）")
tops2 = {ranking(S2, w)[0][0] for w in WEIGHTS}
check("S2 はどの重みでもハイブリッドが1位（採点表の構造）",
      tops2 == {HYBRID},
      " / ".join(f"{w.key}: {ranking(S2, w)[0][0]} {ranking(S2, w)[0][1]:.2f}"
                 for w in WEIGHTS))
record = {o: axis_record(S2, HYBRID, o) for o in (API, SELF, EDGE)}
check("ハイブリッドはクラウド2案には勝ち越すが、エッジには勝ち越せない",
      record[API][0] > record[API][1] and record[SELF][0] > record[SELF][1]
      and record[EDGE][0] < record[EDGE][1],
      " / ".join(f"対{o} {w}勝{l}敗" for o, (w, l) in record.items()))
top3_a, top3_b = ranking(S3, wa)[0], ranking(S3, wb)[0]
check("S3 も重みで1位が入れ替わる",
      top3_a[0] == HYBRID and top3_b[0] == EDGE,
      f"{wa.key}: {top3_a[0]} {top3_a[1]:.2f} / {wb.key}: {top3_b[0]} "
      f"{top3_b[1]:.2f}")

# --- [6] 移行計画 -----------------------------------------------------------
print("\n[6] 移行計画")
check("段の割合は単調に増える", ratios_monotonic(),
      " -> ".join(f"{s.ratio:.0%}" for s in STAGES))
check("全段に撤退条件がある", all(s.retreat for s in STAGES),
      f"{len(STAGES)} 段すべて")
check(f"観察期間の合計は {observe_days_total()} 日", observe_days_total() == 29)
check("判断は3値（進めない を消さない）", DECISIONS == ("進める", "進めない", "戻す"),
      "／".join(DECISIONS))
check("観察しない段は作れない",
      raises(lambda: Stage("第5段", 1.0, 0, "進む", "戻す")),
      "observe_days は 1 日以上")
check("進む条件と撤退条件の片方だけの段は作れない",
      raises(lambda: Stage("第5段", 1.0, 1, "進む", "")),
      "対で持たないと「進めない」が判定できない")
check("影運転は 0% で始まる（利用者に影響を出さずに測る段）",
      STAGES[0].ratio == 0.0, STAGES[0].name)

# --- [7] 再判断のトリガー ---------------------------------------------------
print("\n[7] 再判断のトリガー")
trigs = triggers_for(S2)
check("トリガーは5要素すべてが埋まっている",
      len(trigs) == 5 and all(t.metric and t.threshold and t.window
                              and t.action and t.owner for t in trigs),
      f"{len(trigs)} 本")
check("しきい値の無いトリガーは検査で落ちる",
      raises(lambda: Trigger("状況が変わったら見直す", "", "", "見直す", "")),
      "「状況が変わったら見直す」は例外になる")
check("しきい値は感度分析の反転値から来ている",
      any("0.7716" in t.threshold for t in trigs)
      and any("1,025.1万件" in t.threshold for t in trigs),
      "／".join(t.threshold for t in trigs[:3]))
check("同じ境目を2つの観測点で見張っている",
      any("914.6万件" in t.threshold for t in trigs)
      and any("62.5%" in t.threshold for t in trigs),
      f"月間件数 {be2.requests_per_hour * HOURS_PER_MONTH / 10000:,.1f}万件 と "
      f"利用率 {be2.utilization * 100:.1f}%")
check("取得できない指標はアクションが「測る」から始まる",
      any(t.metric.startswith("動作点") and "測り" in t.action for t in trigs),
      "ダッシュボードに無い指標は、測る手段も一緒に決める")
check("S1（結論が堅い側）でもトリガーは作れる",
      len(triggers_for(S1)) >= 4
      and any("を超える" in t.threshold for t in triggers_for(S1)),
      "向きが逆になる（件数が増えたら自前を再検討）")

# --- [8] 意思決定文書 -------------------------------------------------------
print("\n[8] 意思決定文書")
doc = document_markdown(S2, wa)
check("6つの欄と再計算手順がすべて埋まっている", missing_sections(doc) == [],
      f"{len(doc):,} 文字")
check("測定条件の欄がある", "測定条件" in doc and "2026-08-15" in doc)
broken = doc.replace("## 6. 再判断のトリガー", "## 6. トリガー")
check("欄が欠けたら検出できる",
      missing_sections(broken) == ["6. 再判断のトリガー"],
      f"欠落 {missing_sections(broken)}")
check("結論の根拠に総合点を使わないと書いてある",
      "総合点は根拠ではありません" in doc and "決め手になった軸" in doc)
check("未実測の前提は空欄にせず「未実測」と書く", "**未実測**" in doc,
      "空欄は「問題なし」と読まれる")
doc3 = document_markdown(S3, wb)
check("単価が計算できないシナリオでも文書は成立する",
      missing_sections(doc3) == [] and "単価の比較は不要" in doc3,
      "ゲートで2案が消えるので単価の計算が要らない")
check("通信量は②物理計算で出る",
      "61.80 GB/月" in doc3 and "3.09 GB/月" in doc3,
      "生データ 61.80 GB/月 → 一次判定で 5.0% だけ送れば 3.09 GB/月")

print(f"\n検証 {checked} 件")
if failures:
    print(f"NG {len(failures)} 件: " + " / ".join(failures))
    sys.exit(1)
print("すべて OK（失敗 0 件）")
