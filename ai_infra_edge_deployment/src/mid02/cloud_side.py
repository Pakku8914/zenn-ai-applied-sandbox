#!/usr/bin/env python3
"""案A：クラウドの推論サーバで一次分類する（中間プロジェクト2）。

    python src/mid02/cloud_side.py --parse-demo      # 出力の解釈（サーバ不要）
    python src/mid02/cloud_side.py --repeats 3       # 20 件 × 3 回測って中央値

言語モデルに分類させると、**分類器には存在しないリスク**が1つ増える。
区分として解釈できない出力が返ることで、本書はこれを「形式違反」と呼ぶ。
比較表には、片方にしか存在しないリスクも書く。
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

SANDBOX = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SANDBOX))

from infrakit.client import LlamaClient  # noqa: E402
from src.mid02.task import (  # noqa: E402
    BORDERLINE, CATEGORIES, PROTOCOL, REFERENCE_LABELS, SYMBOLS,
)
from tools.prompts import QUESTIONS  # noqa: E402

REPORTS = SANDBOX / "reports"

MAX_TOKENS = 8
"""出力は記号1文字で足りる。**プリフィルは変わらずデコードだけが短くなる**ので、
セッション3・4 の max_tokens=48 の実測値とは条件が違う。混ぜて表に置かない。"""

CLASSIFY_TEMPLATE = (
    "あなたは社内ヘルプデスクの一次受付です。\n"
    "次の問い合わせを、以下の6区分のいずれか1つに分類してください。\n"
    "区分の記号（A-F）だけを1文字で出力し、説明や句読点は出力しないでください。\n\n"
    + "".join(f"{sym} {name}\n" for sym, name in CATEGORIES)
    + "\n問い合わせ: {question}\n区分: "
)

PARSE_DEMO: tuple[str, ...] = ("C", "区分: E", "A 勤怠・休暇", "わかりません",
                               "A または B", "")


@dataclass(frozen=True)
class Decision:
    """1件の判定結果。**案Bと同じ形**にしておくのが比較の前提。"""

    index: int
    category_id: int | None
    confidence: float
    raw: str = ""
    latency_ms: float = 0.0
    ttft_ms: float = 0.0

    @property
    def parsed(self) -> bool:
        return self.category_id is not None


def parse_symbol(raw: str) -> int | None:
    """出力から区分 ID を取り出す。**曖昧な出力を既定の区分に寄せない。**

    寄せてしまうと形式違反が表から消え、案Bとの比較で「案Aにしかないリスク」を
    見落とす。0 個（見つからない）も 2 個以上（どれか分からない）も違反にする。
    """
    found = sorted({SYMBOLS.index(ch) for ch in raw.upper() if ch in SYMBOLS})
    return found[0] if len(found) == 1 else None


def violation_reason(raw: str) -> str:
    """形式違反の理由を1つに決める（表に出すため）。"""
    found = {ch for ch in raw.upper() if ch in SYMBOLS}
    if not raw:
        return "形式違反（空）"
    if len(found) > 1:
        return "形式違反（区分が複数）"
    return "形式違反（記号が無い）"


def classify(client: LlamaClient, question: str, index: int,
             max_tokens: int = MAX_TOKENS) -> Decision:
    res = client.generate(CLASSIFY_TEMPLATE.format(question=question),
                          max_tokens=max_tokens, temperature=0.0)
    cid = None if res.error else parse_symbol(res.text)
    # 確度は2値しか作れない（言語モデルから確率が取れない）。
    # だから**案Aを一次判定に置くハイブリッドは作れない**。
    return Decision(index, cid, 1.0 if cid is not None else 0.0,
                    (res.text or "").strip(), res.total_ms, res.ttft_ms)


@dataclass
class CloudRun:
    decisions: tuple[Decision, ...] = ()
    conditions: dict = field(default_factory=dict)

    @property
    def parsed(self) -> int:
        return sum(1 for d in self.decisions if d.parsed)

    @property
    def violations(self) -> int:
        return len(self.decisions) - self.parsed

    @property
    def violation_rate(self) -> float:
        return self.violations / len(self.decisions) if self.decisions else 0.0

    def latency(self, attr: str = "latency_ms") -> dict[str, float]:
        values = sorted(getattr(d, attr) for d in self.decisions if d.parsed)
        if not values:
            return {"p50": 0.0, "p95": 0.0, "max": 0.0}
        return {"p50": statistics.median(values),
                "p95": values[max(int(len(values) * 0.95) - 1, 0)],
                "max": values[-1]}

    def agreement(self) -> dict[str, int]:
        """参照ラベルとの一致を、境界事例とそれ以外に分けて数える。"""
        clear_total = clear_agree = close_total = close_agree = 0
        for d in self.decisions:
            if not d.parsed:
                continue
            hit = d.category_id == REFERENCE_LABELS[d.index]
            if d.index in BORDERLINE:
                close_total += 1
                close_agree += int(hit)
            else:
                clear_total += 1
                clear_agree += int(hit)
        return {"clear_total": clear_total, "clear_agree": clear_agree,
                "close_total": close_total, "close_agree": close_agree}


def run(client: LlamaClient, n: int = len(QUESTIONS), repeats: int = 3,
        warmup: int = 2, max_tokens: int = MAX_TOKENS) -> CloudRun:
    """20 件 × repeats 回。**中央値を採るのは代表値のぶれを潰すため**（取り決め6）。"""
    for i in range(warmup):
        client.generate(CLASSIFY_TEMPLATE.format(question=QUESTIONS[i % n]),
                        max_tokens=max_tokens)
    props = client.props()
    best: list[Decision] = []
    for i in range(n):
        tries = [classify(client, QUESTIONS[i], i, max_tokens)
                 for _ in range(repeats)]
        median = statistics.median(t.latency_ms for t in tries)
        # 中央値に最も近い試行を代表にする（判定と時間の組を壊さない）
        best.append(min(tries, key=lambda t: abs(t.latency_ms - median)))
    return CloudRun(tuple(best), {
        "side": "cloud", "date": str(date.today()),
        "input_set": "tools/prompts.py:QUESTIONS", "n_inputs": n,
        "output_form": "category_id+confidence", "measure_point": "区分IDを受け取るまで",
        "median_of": repeats, "warmup": warmup, "max_tokens": max_tokens,
        "temperature": 0.0, "model": str(props.get("model_path", "unknown")),
        "n_ctx": props.get("n_ctx"), "network_roundtrip": "含む",
        "protocol": {k: v for k, v in PROTOCOL},
    })


def show_parse_demo() -> None:
    print("=== 出力の解釈（形式違反の3パターン）===")
    print("| サーバの出力 | 区分 ID | 判定 |")
    print("| :--- | --: | :--- |")
    for raw in PARSE_DEMO:
        cid = parse_symbol(raw)
        shown = f"`{raw}`" if raw else "（空文字）"
        if cid is None:
            print(f"| {shown} | — | {violation_reason(raw)} |")
        else:
            print(f"| {shown} | {cid} | 解釈できた |")
    print("-> 曖昧な出力を既定の区分に寄せない。寄せると表からリスクが消える。")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="案A：クラウドで一次分類する")
    parser.add_argument("--parse-demo", action="store_true",
                        help="出力の解釈だけを確認する（サーバ不要）")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=MAX_TOKENS)
    parser.add_argument("--out", default="reports/mid02_cloud.json")
    args = parser.parse_args(argv)

    if args.parse_demo:
        show_parse_demo()
        return 0

    client = LlamaClient()
    if not client.health():
        print("推論サーバに接続できません。docker compose up -d llama を実行してください。",
              file=sys.stderr)
        return 1

    result = run(client, repeats=args.repeats, max_tokens=args.max_tokens)
    agree = result.agreement()
    lat, ttft = result.latency(), result.latency("ttft_ms")

    print("=== 案A：クラウドで一次分類（この環境の値）===")
    print(f"件数          : {len(result.decisions)} 件"
          f"（{args.repeats} 回測って中央値）")
    print(f"解釈できた件数: {result.parsed} 件")
    print(f"形式違反      : {result.violations} 件"
          f"（{result.violation_rate:.1%}）")
    for d in result.decisions:
        if not d.parsed:
            print(f"  #{d.index + 1} の出力: {d.raw!r}")
    print(f"区分IDまで p50: {lat['p50']:.0f} ms / p95: {lat['p95']:.0f} ms")
    print(f"最初の反応 p50: {ttft['p50']:.0f} ms / p95: {ttft['p95']:.0f} ms")
    print(f"参照ラベル一致: 明らかな件 {agree['clear_agree']}/{agree['clear_total']} / "
          f"境界事例 {agree['close_agree']}/{agree['close_total']}")
    print(f"測定条件      : {json.dumps(result.conditions, ensure_ascii=False)}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"conditions": result.conditions,
         "parsed": result.parsed, "violations": result.violations,
         "violation_rate": result.violation_rate,
         "latency_ms": lat, "ttft_ms": ttft, "agreement": agree,
         "decisions": [{"index": d.index, "category_id": d.category_id,
                        "confidence": d.confidence, "raw": d.raw,
                        "latency_ms": round(d.latency_ms, 2),
                        "ttft_ms": round(d.ttft_ms, 2)}
                       for d in result.decisions]},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main() if os.environ.get("SKIP_SERVER") != "1" else 0)
