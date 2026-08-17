"""セッション13の共通部品：権限の解決・アクセス制御付き検索・混入検査・キャッシュ。

ここに置くのは「章をまたいで凍結する ragkit」ではなく、読者が自分の製品に持ち帰る側の
コードである。ragkit のシグネチャ（search(query, k, filters)）は一切変えず、
その外側に権限を強制する層をかぶせる。

方針:
  1. 許可リスト（allowlist）で書く。拒否リストは未知の値に対して開いてしまう
  2. 未知の役割・空の許可リストは例外にする（fail-closed）
  3. フィルタは検索の「前」に渡す。後段の Python で捨てる設計にはしない
"""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
from qdrant_client.models import (  # noqa: E402
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    Range,
    VectorParams,
)

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_queries  # noqa: E402
from ragkit.dense import VECTOR_SIZE, DenseIndex  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402
from ragkit.models import Doc, Hit, Query  # noqa: E402

COLLECTION = "minato_docs_fixed"

# 役割 -> 見てよい visibility の許可リスト。ここが権限モデルの単一の真実。
ROLE_VISIBILITY: dict[str, tuple[str, ...]] = {
    "member": ("all",),
    "manager": ("all", "manager"),
}


# --- 1. 権限の解決 -----------------------------------------------------------


def allowed_visibility(role: str) -> tuple[str, ...]:
    """役割から許可リストを引く。未知の役割は拒否する（fail-closed）。

    ここで `return ROLE_VISIBILITY.get(role, ("all",))` と書きたくなるが、
    それは「知らない役割には一般公開ぶんを見せる」という判断を暗黙に埋め込むことになる。
    知らないなら止める。
    """
    if role not in ROLE_VISIBILITY:
        raise PermissionError(
            f"未知の役割です: {role!r}（fail-closed のため検索を実行しません）"
        )
    return ROLE_VISIBILITY[role]


@dataclass(frozen=True)
class Principal:
    """検索を実行する主体。権限に関わる属性をここに集約する。

    認証・認可そのもの（誰が本当にこの人か・役割をどう払い出すか）は本書の範囲外で、
    アプリケーション側から渡ってくる前提に立つ。検索層の責務は
    「渡された Principal を検索条件へ確実に翻訳すること」だけ。
    """

    user_id: str
    role: str
    dept: str = ""

    @property
    def visibility(self) -> tuple[str, ...]:
        return allowed_visibility(self.role)

    def cache_scope(self) -> str:
        """キャッシュキーに混ぜる権限スコープ。権限が同じ人は同じ文字列になる。

        user_id を鍵にすると分離はできるがヒット率が人数分の1に落ちる。
        「見える範囲が同じ人」でまとめるのが、安全とヒット率の折り合いになる。
        """
        return "vis:" + "|".join(self.visibility)


def visibility_filter(principal: Principal) -> dict:
    """検索層へ渡すフィルタ辞書を作る。

    空の辞書を返してはいけない。ragkit の `_to_qdrant_filter({})` は None を返し、
    LexicalIndex の `if filters:` も偽になるため、**空の辞書はフィルタ無しと同義**になる。
    「条件が無いときは {} を返す」という善意の実装が、そのまま fail-open になる。
    """
    allowed = principal.visibility
    if not allowed:
        raise PermissionError("許可リストが空です（fail-closed のため検索を実行しません）")
    return {"visibility": list(allowed)}


# --- 2. アクセス制御付き検索 --------------------------------------------------


class AccessAwareRetriever:
    """検索器に権限フィルタを必ず添えるラッパ。

    Principal 無しでは生成できないので、「フィルタを付け忘れた検索」を
    そもそも書けなくする。呼び出し側が filters を渡しても、権限条件は上書きされない。
    """

    def __init__(self, inner, principal: Principal) -> None:
        self.inner = inner
        self.principal = principal

    def search(self, query: str, k: int = 10, filters: dict | None = None) -> list[Hit]:
        merged = dict(filters or {})
        merged.update(visibility_filter(self.principal))  # 権限条件が常に勝つ
        return self.inner.search(query, k=k, filters=merged)


class PostFilterRetriever:
    """比較用（本番で使ってはいけない）：検索してから Python で捨てる実装。

    混入は起きないが、上位k件から捨てるので**取りこぼす**。
    セッション7で測ったとおり、事前フィルタ4件に対して事後フィルタは0件になった。
    """

    def __init__(self, inner, principal: Principal) -> None:
        self.inner = inner
        self.principal = principal

    def search(self, query: str, k: int = 10, filters: dict | None = None) -> list[Hit]:
        allowed = set(self.principal.visibility)
        hits = self.inner.search(query, k=k, filters=filters)
        return [h for h in hits if h.meta.get("visibility") in allowed]


# --- 3. 混入検査 --------------------------------------------------------------


def leaked_hits(hits: list[Hit], principal: Principal) -> list[Hit]:
    """許可されていない可視性のヒットを拾う。

    `meta.get("visibility")` が None（欠損）のときも混入として数える。
    メタデータが欠けている文書を「たぶん公開だろう」と扱わないための fail-closed。
    """
    allowed = set(principal.visibility)
    return [h for h in hits if h.meta.get("visibility") not in allowed]


@dataclass
class SweepResult:
    """権限別・全クエリの混入検査の結果。"""

    label: str
    n_queries: int = 0
    n_leaked_queries: int = 0
    n_leaked_hits: int = 0
    n_short: int = 0  # 要求した k に満たなかったクエリ数
    n_empty: int = 0  # 0件になったクエリ数
    examples: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return self.n_leaked_hits == 0

    def line(self) -> str:
        return (
            f"{self.label:<34} クエリ{self.n_queries:>4}件 / "
            f"混入クエリ{self.n_leaked_queries:>3}件 / 混入ヒット{self.n_leaked_hits:>3}件 / "
            f"k未満{self.n_short:>3}件 / 0件{self.n_empty:>3}件"
        )


def sweep(search_fn, principal: Principal, queries: list[Query], k: int = 10,
          label: str = "", max_examples: int = 5) -> SweepResult:
    """全クエリを1つの権限で回し、混入を数える。

    search_fn(query_text, k) -> list[Hit] を受け取るので、
    事前フィルタ・事後フィルタ・フィルタ無しを同じ関数で比較できる。
    """
    res = SweepResult(label=label or principal.role)
    for q in queries:
        hits = search_fn(q.text, k)
        res.n_queries += 1
        if not hits:
            res.n_empty += 1
        if len(hits) < k:
            res.n_short += 1
        bad = leaked_hits(hits, principal)
        if bad:
            res.n_leaked_queries += 1
            res.n_leaked_hits += len(bad)
            for h in bad:
                if len(res.examples) < max_examples:
                    res.examples.append(
                        (q.query_id, h.chunk_id, str(h.meta.get("visibility")))
                    )
    return res


# --- 4. プローブクエリ（レッドチーム側の視点）---------------------------------


def restricted_docs(docs: list[Doc] | None = None) -> list[Doc]:
    """visibility が all 以外の文書（＝一般社員に見せてはいけない文書）。"""
    return sorted(
        [d for d in (docs or load_docs()) if d.visibility != "all"], key=lambda d: d.doc_id
    )


def probe_queries(docs: list[Doc] | None = None) -> list[Query]:
    """制限文書そのものを狙って引くクエリを作る。

    評価用の120クエリは「業務で聞かれそうな質問」なので、攻撃者の引き方が入っていない。
    権限のテストには、**秘密の側の語で引くクエリ**を必ず混ぜる。
    """
    out: list[Query] = []
    for i, d in enumerate(restricted_docs(docs), start=1):
        text = d.title.replace("（管理職限定）", "")
        out.append(Query(query_id=f"P-{i:03d}", text=text, type="probe"))
    return out


def leak_test_queries() -> list[Query]:
    """混入検査に使うクエリ集合：業務クエリ（回答不能を含む）＋プローブ。"""
    return load_queries() + probe_queries()


# --- 5. キャッシュ ------------------------------------------------------------


class SearchCache:
    """検索結果のキャッシュ。key_mode で鍵の作り方を切り替えて挙動を比べる。

    key_mode:
      "query_only" — クエリ本文だけを鍵にする（最も速く、最も危ない）
      "principal"  — 権限スコープを鍵に含める（本書の推奨）
      "user"       — 利用者ごとに分ける（安全だがヒット率が落ちる）
    """

    def __init__(self, key_mode: str = "principal") -> None:
        if key_mode not in ("query_only", "principal", "user"):
            raise ValueError(f"unknown key_mode: {key_mode}")
        self.key_mode = key_mode
        self.store: dict[str, list[Hit]] = {}
        self.hit_count = 0
        self.miss_count = 0

    def key(self, principal: Principal, query: str, k: int) -> str:
        if self.key_mode == "query_only":
            return f"q={query}|k={k}"
        if self.key_mode == "user":
            return f"user={principal.user_id}|q={query}|k={k}"
        return f"{principal.cache_scope()}|q={query}|k={k}"

    def get_or_search(self, retriever, principal: Principal, query: str,
                      k: int = 10) -> list[Hit]:
        key = self.key(principal, query, k)
        if key in self.store:
            self.hit_count += 1
            return self.store[key]
        self.miss_count += 1
        hits = retriever.search(query, k=k)
        self.store[key] = hits
        return hits

    def invalidate_doc(self, doc_id: str) -> int:
        """指定文書を含むエントリを捨てる。権限変更・削除要求のときに必ず呼ぶ。"""
        victims = [key for key, hits in self.store.items() if any(h.doc_id == doc_id for h in hits)]
        for key in victims:
            del self.store[key]
        return len(victims)

    def clear(self) -> None:
        self.store.clear()


# --- 6. 索引と Qdrant のヘルパ ------------------------------------------------

ID_NAMESPACE = uuid.NAMESPACE_URL
ID_PREFIX = "minato://chunk/"

_LEXICAL: LexicalIndex | None = None


def point_id(chunk_id: str) -> str:
    """chunk_id から決定的に点IDを作る（セッション7と同じ規約）。"""
    return str(uuid.uuid5(ID_NAMESPACE, f"{ID_PREFIX}{chunk_id}"))


def all_chunks(size: int = 400, overlap: int = 80):
    return chunk_all(load_docs(), "fixed", size=size, overlap=overlap)


def lexical_index() -> LexicalIndex:
    """BM25 索引（プロセス内で1度だけ構築する）。埋め込みモデルは不要。"""
    global _LEXICAL
    if _LEXICAL is None:
        _LEXICAL = LexicalIndex().build(all_chunks())
    return _LEXICAL


def qdrant_client():
    """Qdrant のクライアント（コレクションは触らない）。"""
    return DenseIndex("__s13_client__").client


def dense_index(build_if_missing: bool = True) -> DenseIndex:
    """minato_docs_fixed を使う密ベクトル検索器。

    既存のコレクションを再利用する。無いときだけ作る（作り直さない）。
    """
    idx = DenseIndex(COLLECTION)
    if not idx.client.collection_exists(COLLECTION):
        if not build_if_missing:
            raise SystemExit(
                f"{COLLECTION} がありません。先に `python src/session07/verify.py` を実行してください。"
            )
        print(f"{COLLECTION} が無いので作成します（1分程度かかります）")
        idx.build(all_chunks())
    return idx


def synth_vectors(n: int, seed: int = 20260815) -> np.ndarray:
    """決定的な合成ベクトル（正規化済み）。中身に意味は無い。

    この章で見たいのは「フィルタが何を残すか」であって順位ではないので、
    一時コレクションの検証には合成ベクトルで足りる。
    """
    rng = np.random.default_rng(seed)
    v = rng.normal(size=(n, VECTOR_SIZE)).astype(np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    return v


def visible_to(role: str) -> Filter:
    """役割から Qdrant のフィルタを作る（許可リストをそのまま MatchAny にする）。"""
    return Filter(
        must=[FieldCondition(key="visibility", match=MatchAny(any=list(allowed_visibility(role))))]
    )


# --- 7. 時点性（有効期間）------------------------------------------------------

FAR_FUTURE = 99991231


def as_ord(iso_date: str) -> int:
    """YYYY-MM-DD を 20260815 のような整数にする。

    範囲条件は数値で書くのが最も素直（文字列日付の大小比較は実装差に振り回される）。
    """
    return int(iso_date.replace("-", ""))


def build_versions() -> list[dict]:
    """規程（policy）を主題ごとにまとめ、有効期間（valid_from / valid_to）を計算する。

    同じ日付の版が複数あるときは、どちらも「後継なし」として現行に残す。
    """
    policies = [d for d in load_docs() if d.source_type == "policy"]
    by_theme: dict[str, list[Doc]] = {}
    for d in policies:
        by_theme.setdefault(d.theme, []).append(d)

    rows: list[dict] = []
    for theme, group in by_theme.items():
        dates = sorted({as_ord(d.updated_at) for d in group})
        for d in group:
            start = as_ord(d.updated_at)
            later = [x for x in dates if x > start]
            end = later[0] if later else FAR_FUTURE
            rows.append({
                "doc_id": d.doc_id, "title": d.title, "theme": theme,
                "valid_from": start, "valid_to": end, "is_current": end == FAR_FUTURE,
            })
    return sorted(rows, key=lambda r: r["doc_id"])


def asof_filter(asof: int) -> Filter:
    """その時点で有効だった版だけを残す（valid_from <= asof < valid_to）。"""
    return Filter(must=[
        FieldCondition(key="valid_from", range=Range(lte=asof)),
        FieldCondition(key="valid_to", range=Range(gt=asof)),
    ])


def current_filter() -> Filter:
    """派生フラグ（is_current）による等値フィルタ。更新漏れに弱い。"""
    return Filter(must=[FieldCondition(key="is_current", match=MatchValue(value=True))])


def recreate(client, name: str) -> None:
    """一時コレクションを作り直す（既にあれば消してから作る）。"""
    if client.collection_exists(name):
        client.delete_collection(name)
    client.create_collection(
        name, vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE)
    )


def count(client, name: str, count_filter=None) -> int:
    return client.count(name, count_filter=count_filter, exact=True).count


def drop(client, *names: str) -> None:
    for name in names:
        if client.collection_exists(name):
            client.delete_collection(name)
