#!/usr/bin/env python3
"""最終プロジェクト：みなと商事の検索基盤（製品側のコード）。

    docker compose exec app python src/final/search_platform.py

**新しい検索方式は1つも作らない。** 決めるのは「どの部品を、どの順で重ねるか」だけ。

  1段目   BM25（S05）＋ クエリ側の同義語展開（Review01・S10）
  権限    AccessAwareRetriever（S13）を**最も内側**に置く（事前フィルタ）
  2段目   リランク（S09・任意）。候補数はレイテンシ予算から逆算する
  生成    コンテキスト構成（S11）＋ 合成カセット（APIキー不要）
  後処理  6判定（S11・mid02）。ok 以外は利用者に出さない
  記録    S17 のログスキーマ（取り込み口でマスキング）

ファイル名を `platform.py` にしていないのは、標準ライブラリの `platform` を
隠してしまうため（実行ディレクトリが `sys.path` の先頭に入る）。
"""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from reuse import ROOT, access, lab, mask, plan, post  # noqa: E402,F401

from ragkit.answer import SYSTEM_PROMPT, build_user_prompt  # noqa: E402
from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402
from ragkit.llm import FixtureClient, cache_key  # noqa: E402
from ragkit.models import Hit  # noqa: E402

# --- レイテンシ予算（S09 の実測から逆算する）---------------------------------
LATENCY_BUDGET_MS = 500  # 検索から回答までの p95 目標
FIRST_STAGE_MS = 20      # 1段目（BM25 + 権限フィルタ）に引き当てる分
LOG_SALT = "minato-final"  # 実運用では環境変数から読む（コードに置かない）
JST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class PlatformConfig:
    """凍結する設定。**ここに書いてある値がすべて合成カセットの鍵に効く。**

    1つでも変えたらカセットを作り直す（`python src/final/final_cassette.py`）。
    """

    name: str = "final-v1"
    chunk_method: str = "fixed"
    chunk_size: int = 400
    chunk_overlap: int = 80
    synonyms: bool = True            # クエリ側の同義語展開（到達不足への打ち手）
    hybrid: bool = False             # 密ベクトルを足して min-max で融合する（要 Qdrant）
    hybrid_candidates: int = 50
    hybrid_weights: tuple[float, float] = (0.3, 1.0)  # (レキシカル, 密ベクトル)
    rerank_candidates: int = 0       # 0 でリランク無し。予算 500ms なら 12
    top_k: int = 5                   # 生成に渡す件数
    max_chars: int = 2000            # コンテキストの上限
    min_score: float | None = None   # 低スコアの足切り（未測定なので既定は無効）
    strict_citations: bool = True    # 引用の母集合をコンテキスト内に絞る
    cassette: str = "answers_final_v1"

    def summary(self) -> dict:
        return asdict(self)


#: 採用する構成（成果物①の決定事項と一致させる）
ADOPTED = PlatformConfig()
#: 比較用の基準線（同義語展開を外しただけ。他は1つも変えない）
BASELINE = PlatformConfig(name="baseline-v0", synonyms=False)

#: 役割の定義（S13 の許可リストをそのまま使う）
MEMBER = access.Principal(user_id="u-1001", role="member", dept="営業部")
MANAGER = access.Principal(user_id="u-2001", role="manager", dept="営業部")
ROLES: dict[str, access.Principal] = {"member": MEMBER, "manager": MANAGER}


def budget_candidates(budget_ms: int = LATENCY_BUDGET_MS,
                      first_stage_ms: int = FIRST_STAGE_MS) -> int:
    """レイテンシ予算からリランクの候補数を逆算する（S09 の実測を補間）。

    予算をすべてリランクに使えるわけではない。1段目に引き当てた分を先に引く。
    """
    return plan.candidates_for_budget(budget_ms - first_stage_ms)


#: チャンクと転置索引はプロセス内で使い回す（同じチャンク方式なら1つで足りる）
_CACHE: dict[tuple, tuple[list, LexicalIndex]] = {}


def chunks_and_index(config: PlatformConfig) -> tuple[list, LexicalIndex]:
    """チャンク方式ごとに1回だけ索引を作る。構成を並べて比べるときに効く。"""
    key = (config.chunk_method, config.chunk_size, config.chunk_overlap)
    if key not in _CACHE:
        chunks = chunk_all(load_docs(), config.chunk_method,
                           size=config.chunk_size, overlap=config.chunk_overlap)
        _CACHE[key] = (chunks, LexicalIndex().build(chunks))
    return _CACHE[key]


class SearchPlatform:
    """検索基盤の入口。1リクエストの入口を1つにして、権限を通らない経路を作らない。

    `client` を渡すと生成クライアントを差し替えられる（カセット生成時は StubClient）。
    """

    def __init__(self, config: PlatformConfig = ADOPTED, client=None) -> None:
        self.config = config
        self.chunks, self.index = chunks_and_index(config)
        # 同義語展開は索引の外側（索引を作り直さずに載せ替えられる）
        base = lab.SynonymRetriever(self.index) if config.synonyms else self.index
        if config.hybrid:
            # 任意段：密ベクトルを足して min-max で融合する（S08 の 0.3:1.0）。
            # コレクションは**既存のものを再利用する**（作り直さない）。
            from ragkit.hybrid import HybridRetriever

            dense = access.dense_index(build_if_missing=False)
            base = HybridRetriever([base, dense], candidates=config.hybrid_candidates,
                                   mode="minmax", weights=list(config.hybrid_weights))
        self.base = base
        self._client = client
        self._pipelines: dict[str, post.AnswerPipeline] = {}

    # --- 生成クライアント -----------------------------------------------------
    @property
    def client(self):
        """既定は合成カセット。**APIキーは不要。**"""
        if self._client is None:
            self._client = FixtureClient(self.config.cassette)
        return self._client

    # --- 検索 -----------------------------------------------------------------
    def retriever(self, principal: access.Principal):
        """権限フィルタを最内側に置いた検索器を返す。

        `AccessAwareRetriever` は Principal 無しでは作れないので、
        **フィルタを付け忘れた検索をそもそも書けない**。
        """
        return access.AccessAwareRetriever(self.base, principal)

    def pipeline(self, principal: access.Principal) -> post.AnswerPipeline:
        """検索 → コンテキスト → 生成 → 後処理 を1本にした入口（mid02 の再利用）。"""
        key = f"{principal.role}|{principal.user_id}"
        if key not in self._pipelines:
            self._pipelines[key] = post.AnswerPipeline(
                self.retriever(principal), self.client,
                top_k=self.config.top_k, max_chars=self.config.max_chars,
                min_score=self.config.min_score,
                strict_citations=self.config.strict_citations,
                # リランクは権限フィルタの「外側」に重なる（＝候補は必ず権限済み）
                rerank_candidates=self.config.rerank_candidates or None,
            )
        return self._pipelines[key]

    def retrieve(self, principal: access.Principal, query_text: str) -> list[Hit]:
        """生成に渡すのと**まったく同じ**候補を返す（カセットの鍵をそろえるため）。"""
        return self.pipeline(principal).retrieve(query_text)

    def prompt_key(self, principal: access.Principal, query_text: str) -> tuple[str, str]:
        """(プロンプト, カセットの鍵) を返す。鍵はプロンプト全体の SHA-256。"""
        hits = self.retrieve(principal, query_text)
        user = build_user_prompt(query_text, hits, max_chars=self.config.max_chars)
        return user, cache_key(SYSTEM_PROMPT, user)

    # --- 回答 -----------------------------------------------------------------
    def answer(self, principal: access.Principal, query_text: str,
               query_id: str = "") -> post.Result:
        """1リクエストを処理する。ok 以外は本文を定型文に差し替えて返す。"""
        return self.pipeline(principal).run(query_text, query_id)

    # --- 記録 -----------------------------------------------------------------
    def log_record(self, principal: access.Principal, query_text: str,
                   result: post.Result, latency_ms: int, request_id: str,
                   session_id: str = "sess-0001", ts: str | None = None) -> dict:
        """保存してよい形のログ行を作る（S17）。**取り込み口で落とすのが唯一守られる設計。**"""
        top = result.top_score
        raw = {
            "ts": ts or datetime.now(JST).isoformat(timespec="seconds"),
            "request_id": request_id,
            "session_id": session_id,
            "user_id": principal.user_id,
            "user_role": principal.role,
            "user_dept": principal.dept,
            "query_text": query_text,
            "profile": self.config.name,
            "n_results": len(result.context_ids),
            "verdict": result.verdict,
            "top_score": round(top, 4) if top != float("-inf") else None,
            "latency_ms": latency_ms,
            # ここから下は sanitize が落とす（保存しない）
            "raw_ip": "10.20.30.40",
            "user_agent": "Mozilla/5.0",
            "answer_text": result.text,
        }
        return mask.sanitize(raw, salt=LOG_SALT, text_policy="mask")


def main() -> None:
    from final_cassette import ensure_cassette

    ensure_cassette()
    platform = SearchPlatform(ADOPTED)
    query = "MFAの設定方法を教えてください"

    print("=== 1. 採用した構成（凍結）===")
    for key, value in platform.config.summary().items():
        print(f"  {key:<18}: {value}")
    print(f"  レイテンシ予算 {LATENCY_BUDGET_MS}ms・1段目 {FIRST_STAGE_MS}ms "
          f"→ リランクの候補上限 {budget_candidates()} 件")

    print("\n=== 2. 権限で結果が変わる（同じ質問・違う利用者）===")
    for name, principal in ROLES.items():
        hits = platform.retrieve(principal, query)
        vis = sorted({h.meta.get("visibility") for h in hits})
        print(f"  {name:<8} 許可={principal.visibility} 件数={len(hits)} visibility={vis}")

    print("\n=== 3. 回答（合成カセット・後処理つき）===")
    result = platform.answer(MEMBER, query, "Q-DEMO")
    print(f"  判定: {result.verdict} / 利用者に出した: {result.delivered}")
    print(f"  引用: {list(result.citations)}")
    print(f"  本文: {result.text[:60]}...")

    print("\n=== 4. 保存するログ行（マスキング済み）===")
    record = platform.log_record(MEMBER, query, result, latency_ms=31,
                                 request_id="req-0001", ts="2026-08-15T09:12:00+09:00")
    for key, value in record.items():
        print(f"  {key:<12}: {value}")
    print("\n  ※ raw_ip / user_agent / answer_text は保存しない（取り込み口で落とす）")


if __name__ == "__main__":
    main()
