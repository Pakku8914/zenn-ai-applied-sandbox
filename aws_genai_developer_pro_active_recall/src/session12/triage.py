#!/usr/bin/env python3
"""セッション12: 1件の要求を層ごとに分解して原因を切り分ける。

    docker compose exec app python src/session12/triage.py
    docker compose exec app python src/session12/triage.py P16

多層防御を入れると、必ず「止まるはずのないものが止まった」という報告が来ます。
そのとき知りたいのは**どの層が止めたか**ではなく、**なぜその層に届いたか**です。
このスクリプトは1件だけを流し、各層の中間結果を並べます。

    匿名化後の入力 → 決めたカテゴリ → 投げた検索クエリ → 取れた資料
    → モデルの回答 → 断りの印の有無 → 各層の判定

最後に**原因の切り分け**を2つ行います。

    1. 質問の語と資料の語で共通するものがあるか
       （0 語なら、モックの生成器は必ず「資料の範囲外」と答える）
    2. 入力ガードレール（PII の匿名化）を外しても同じ結果になるか
       （同じ結果なら、匿名化はこの遮断の原因ではない）

**この2つを分けて確かめるのが要点です。** 「安全機構が止めた」ように見える事象の
原因が、安全機構の外（検索・プロンプト・生成）にあることは珍しくありません。
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session05")
sys.path.insert(0, "/workspace/src/session12")

from bedrock_mock import generation  # noqa: E402

import attack_set  # noqa: E402
import retriever  # noqa: E402
import safety  # noqa: E402


def keywords(text: str) -> set[str]:
    """モックの語分割を覗く（教材用）。

    実 AWS の Guardrails や Knowledge Bases の内部はこう見えません。ここでは
    「なぜ噛み合わなかったか」を数字で見せるために、モックの内部関数を借ります。
    """
    return generation._keywords(text)  # noqa: SLF001


def shared_words(question: str, sources: list[str]) -> list[str]:
    """質問の語のうち、資料にも現れるもの。**0 語なら根拠づけは成立しない。**"""
    source_words: set[str] = set()
    for text in sources:
        source_words |= keywords(text)
    return sorted(keywords(question) & source_words)


def walk(probe_id: str) -> None:
    probe = attack_set.by_id(probe_id)
    pipe = safety.SafetyPipeline()

    print(f"=== {probe_id} の各層の中間結果 ===")
    print(f"  狙い: {probe.note}")
    print(f"  入力: {probe.text}")

    l1 = safety.pre_filter(probe.text)
    print(f"  {l1.line()}")
    if l1.blocked:
        print("  ここで止まったので、以降の層には届いていません")
        return

    l2 = safety.input_guardrail(pipe.runtime, l1.text)
    print(f"  {l2.line()}")
    if l2.blocked:
        print("  ここで止まったので、検索も基盤モデルの呼び出しも発生していません")
        return

    masked = l2.text
    category = safety.to_category(masked)
    query = retriever.to_keywords(masked) or masked
    hits = retriever.search(
        pipe.agent, query, mode="HYBRID", top_k=safety.TOP_K, category=category
    )
    sources = [hit["text"] for hit in hits]
    print(f"  匿名化後: {masked}")
    print(f"  カテゴリ: {category} / 検索クエリ: {query}")
    print(f"  資料: {len(hits)}件")
    for hit in hits:
        print(f"    - {hit['title']}")

    answer = pipe.call_model(masked, sources)
    print(f"  モデルの回答: {answer.splitlines()[0]}")
    print(
        "  断りの印（資料の範囲外）: "
        f"{'あり' if safety.registry.REFUSAL_MARKER in answer else 'なし'}"
    )
    l3 = safety.post_check(answer, sources, question=masked)
    print(f"  {l3.line()}")
    if not l3.blocked:
        print(f"  {safety.response_filter(l3.text).line()}")


def main() -> None:
    probe_id = sys.argv[1] if len(sys.argv) > 1 else "P19"
    walk(probe_id)

    probe = attack_set.by_id(probe_id)
    pipe = safety.SafetyPipeline()

    print()
    print("=== 原因の切り分け ===")

    # 1. 語が噛み合っているか（噛み合っていなければ、そもそも答えは作れない）
    masked = safety.input_guardrail(
        pipe.runtime, safety.pre_filter(probe.text).text
    ).text
    query = retriever.to_keywords(masked) or masked
    sources = [
        hit["text"]
        for hit in retriever.search(
            pipe.agent,
            query,
            mode="HYBRID",
            top_k=safety.TOP_K,
            category=safety.to_category(masked),
        )
    ]
    shared = shared_words(masked, sources)
    print(f"  質問の語と資料の語で共通するもの: {len(shared)} 語 -> {shared}")

    reference = attack_set.by_id("P23")
    ref_sources = [
        hit["text"]
        for hit in retriever.search(
            pipe.agent,
            retriever.to_keywords(reference.text) or reference.text,
            mode="HYBRID",
            top_k=safety.TOP_K,
            category=safety.to_category(reference.text),
        )
    ]
    ref_shared = shared_words(reference.text, ref_sources)
    print(f"  参考: P23（通る質問）の共通語: {len(ref_shared)} 語 -> {ref_shared}")

    # 2. 匿名化が原因かどうか（外して同じ結果なら原因ではない）
    without_pii = safety.SafetyPipeline(use_input_guardrail=False).handle(probe.text)
    print(
        "  入力ガードレール（PII の匿名化）を外した結果: "
        f"{without_pii.layer} {without_pii.reason}"
    )


if __name__ == "__main__":
    main()
