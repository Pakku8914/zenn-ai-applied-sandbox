#!/usr/bin/env python3
"""忘却（学習前にできていたことができなくなる現象）を測るプローブ集（セッション9）。

学習したタスクの指標だけを見ていても忘却は見えない。**学習していない別タスク**を
学習前と学習後に同じ手続きで通し、出力を並べて比べるのが最も安い検出方法である。

  # 学習前（ベースモデル）
  python src/session09/forgetting.py --tag before
  # 学習後（セッション6で保存したアダプタを載せる）
  python src/session09/forgetting.py --adapter export/session06/adapter_classify --tag after

生成は `ftkit.evaluate.generate` を使う（`do_sample=False` なので決定的）。
**このスクリプトの出力の数値は環境とモデルで変わるため、本書には載せていない。
自分の実行結果を runs/forgetting_{tag}.json に残し、before と after を並べて読むこと。**
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ftkit.data import CATEGORIES, CLASSIFY_INSTRUCTION  # noqa: E402
from ftkit.evaluate import FORMAT_RE, generate  # noqa: E402

RUNS = Path(__file__).resolve().parents[2] / "runs"


@dataclass(frozen=True)
class Probe:
    id: str
    kind: str      # "held_out"（学習していない別タスク）/ "trained"（学習したタスク）
    prompt: str
    watch: str     # 出力を人が読むときの観点


# 忘却プローブ。**学習データに含まれない指示**を並べるのが要点。
# 学習したタスク（trained）を1つだけ混ぜておくと、「学習は効いているが
# 他が壊れた」のか「学習自体が効いていない」のかを同じレポートで切り分けられる。
PROBES: list[Probe] = [
    Probe(
        id="P-01",
        kind="held_out",
        prompt="3の倍数を小さい順に5つ、カンマ区切りで書いてください。",
        watch="数字を列挙できるか（形式の指示に従えるか）",
    ),
    Probe(
        id="P-02",
        kind="held_out",
        prompt="次の文を丁寧な言い方に書き換えてください。『資料送っといて』",
        watch="自由文の書き換えができるか（1語だけ返していないか）",
    ),
    Probe(
        id="P-03",
        kind="held_out",
        prompt="日本の首都はどこですか。一文で答えてください。",
        watch="事実の質問に答えられるか（学習で知識が壊れていないか）",
    ),
    Probe(
        id="P-04",
        kind="held_out",
        prompt=("次の問い合わせを1文で要約してください。"
                "『先月の出張で使ったタクシー代を精算したいのですが、領収書を失くしました』"),
        watch="要約になっているか（区分名だけを返して学習タスクに引きずられていないか）",
    ),
    Probe(
        id="P-05",
        kind="trained",
        prompt=f"{CLASSIFY_INSTRUCTION}\n\n問い合わせ: 有給休暇の申請はいつまでですか",
        watch="学習したタスクは動いているか（比較の基準）",
    ),
]


def auto_metrics(text: str) -> dict:
    """人が読む前に機械で拾える特徴。数値の良し悪しは決めない（観察のための材料）。"""
    return {
        "chars": len(text),
        "lines": len(text.splitlines()),
        "category_words": sum(1 for category in CATEGORIES if category in text),
        "looks_format": bool(FORMAT_RE.match(text.strip())),
    }


def probe_report(model, tokenizer, probes: list[Probe] = PROBES,
                 max_new_tokens: int = 48) -> list[dict]:
    """プローブを1件ずつ決定的に生成し、レコードの一覧を返す。"""
    records: list[dict] = []
    for probe in probes:
        output = generate(model, tokenizer, probe.prompt, max_new_tokens=max_new_tokens)
        records.append({"id": probe.id, "kind": probe.kind, "watch": probe.watch,
                        "prompt": probe.prompt, "output": output, **auto_metrics(output)})
    return records


def save_report(records: list[dict], tag: str, meta: dict | None = None) -> Path:
    RUNS.mkdir(parents=True, exist_ok=True)
    path = RUNS / f"forgetting_{tag}.json"
    path.write_text(json.dumps({"tag": tag, "meta": meta or {}, "records": records},
                               ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> None:
    from ftkit.models import FAST_MODEL, JA_MODEL, load_model, load_tokenizer

    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=["fast", "ja"], default="fast")
    parser.add_argument("--adapter", default="", help="LoRAアダプタのディレクトリ（学習後を測るとき）")
    parser.add_argument("--tag", default="before")
    parser.add_argument("--max-new-tokens", type=int, default=48)
    parser.add_argument("--dtype", choices=["fp32", "bf16"], default="fp32")
    args = parser.parse_args()

    import torch

    model_name = FAST_MODEL if args.model == "fast" else JA_MODEL
    tokenizer = load_tokenizer(model_name)
    model = load_model(model_name,
                       dtype=torch.float32 if args.dtype == "fp32" else torch.bfloat16)
    if args.adapter:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, args.adapter)

    records = probe_report(model, tokenizer, PROBES, max_new_tokens=args.max_new_tokens)
    for record in records:
        print(f"[{record['id']}/{record['kind']}] {record['prompt'][:32]}...")
        print(f"  出力     : {record['output']!r}")
        print(f"  自動計測 : {record['chars']}文字 {record['lines']}行 "
              f"区分語={record['category_words']} 定型={record['looks_format']}")
        print(f"  観点     : {record['watch']}")

    path = save_report(records, args.tag,
                       {"model": model_name, "adapter": args.adapter, "dtype": args.dtype})
    print(f"\n-> {path}")
    print("学習前（--tag before）と学習後（--tag after）の2つを並べて読むこと。")


if __name__ == "__main__":
    main()
