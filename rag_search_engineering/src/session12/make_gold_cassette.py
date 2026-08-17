#!/usr/bin/env python3
"""上限測定用の合成カセットを作る。

    python src/session12/make_gold_cassette.py

上限測定では「検索結果」ではなく「判定データから作った正解チャンク」を渡す。
コンテキストが変わればプロンプトが変わり、プロンプトが変わればカセットのキーが変わる。
つまり fixtures/answers_v1.json は一切当たらない。もう1本カセットが要る――これが
合成カセット（および記録済みレスポンス全般）の管理コストである。

生成物: fixtures/answers_gold_v1.json

このカセットには、生成側の欠陥を2種類だけ意図的に混ぜてある（合成データなので、
実 API の失敗率を表すものではない）。
  - 19件おき: コンテキストに無い chunk_id を引用する
  - 23件おき: 根拠が手元にあるのに回答不能と答える（過剰な回答不能）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_lab import MAX_CHARS, TOP_K, Bench  # noqa: E402

from ragkit.answer import SYSTEM_PROMPT, build_user_prompt  # noqa: E402
from ragkit.llm import FIXTURE_DIR, cache_key  # noqa: E402
from ragkit.models import Hit, Query  # noqa: E402

CASSETTE = "answers_gold_v1"
FLAW_CITATION = 19   # この間隔で「存在しない引用」を混ぜる
FLAW_ABSTAIN = 23    # この間隔で「根拠があるのに回答不能」を混ぜる


def synth_gold(query: Query, hits: list[Hit], i: int) -> dict:
    """上限測定用の合成応答。正解チャンクが手元にある前提の答え方をする。"""
    if not hits:  # 適合文書がコーパスに無い＝回答不能クエリ
        return {"answerable": False,
                "answer": "参考文書には該当する記載が見つかりませんでした。"
                          "社内ポータルの担当窓口へお問い合わせください。",
                "citations": []}
    top = hits[0]
    title = top.meta.get("title", "")
    if i % FLAW_CITATION == 0:
        return {"answerable": True,
                "answer": f"「{title}」の規程に基づき、所定の期限までに手続きしてください。",
                "citations": ["DOC-9999#001"]}
    if i % FLAW_ABSTAIN == 0:
        return {"answerable": False,
                "answer": "参考文書からは判断できませんでした。",
                "citations": []}
    excerpt = " ".join(top.text[:60].split())
    return {"answerable": True,
            "answer": f"「{title}」によると、{excerpt} とされています。"
                      f"詳細は引用元の記載を確認してください。",
            "citations": [h.chunk_id for h in hits[:2]]}


def build(bench: Bench | None = None, name: str = CASSETTE, k: int = TOP_K) -> Path:
    """カセットを生成してパスを返す。verify からも呼べるように関数に切ってある。"""
    bench = bench or Bench()
    data: dict[str, dict] = {}
    for i, q in enumerate(bench.queries):
        hits = bench.gold_hits(q, k)
        user = build_user_prompt(q.text, hits, max_chars=MAX_CHARS)
        payload = synth_gold(q, hits, i)
        text = json.dumps(payload, ensure_ascii=False)
        data[cache_key(SYSTEM_PROMPT, user)] = {
            "text": text, "query_id": q.query_id, "n_gold": len(hits),
            "input_tokens": len(user) // 3, "output_tokens": len(text) // 3,
        }
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = FIXTURE_DIR / f"{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> None:
    bench = Bench()
    path = build(bench)
    data = json.loads(path.read_text(encoding="utf-8"))
    answerable = sum(1 for v in data.values() if '"answerable": true' in v["text"])
    empty_ctx = sum(1 for v in data.values() if v["n_gold"] == 0)
    print(f"{path.relative_to(path.parents[1])}: {len(data)} 件")
    print(f"  回答した応答          : {answerable} 件")
    print(f"  正解チャンクが0件     : {empty_ctx} 件（回答不能クエリ）")
    print(f"  クエリ数              : {len(bench.queries)} 件")
    print("キーはプロンプト全体のハッシュなので、TOP_K や MAX_CHARS を変えたら作り直すこと。")


if __name__ == "__main__":
    main()
