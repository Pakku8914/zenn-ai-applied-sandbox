#!/usr/bin/env python3
"""横断復習04：権限を検索層で止める道具を、セッション13の記憶から組み直す。

    Principal -> 許可リスト -> フィルタ -> 検索 -> 混入検査 -> キャッシュ

`src/session13/common.py` と同じ設計を、あえてもう一度書いている。写経ではなく
「思い出して書く」ためのファイルなので、細部（fail-closed の書き方・空辞書の罠・
キャッシュ鍵に何を入れるか）を自分の言葉で説明できるかどうかを確かめてほしい。

埋め込みモデルも Qdrant も使わない（BM25 だけで回る）。

実行:  docker compose exec app python src/review04/access_guard.py
"""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs, load_queries  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402
from ragkit.models import Doc, Hit, Query  # noqa: E402

# 役割 -> 見てよい visibility。権限モデルの単一の真実はここ1か所に置く
ROLE_VISIBILITY: dict[str, tuple[str, ...]] = {
    "member": ("all",),
    "manager": ("all", "manager"),
}

# 情報漏洩の経路（セッション13）。検索層で候補に入れなければ6本まとめて閉じる
LEAK_PATHS: tuple[tuple[str, str, bool], ...] = (
    ("検索結果の一覧UI", "題名・本文の抜粋", False),
    ("プロンプト（外部APIへの送信内容）", "本文まるごと", False),
    ("回答の本文", "本文の要約", True),  # 生成側の指示で塞げる可能性があるのはここだけ
    ("引用（題名と chunk_id）", "文書が存在するという事実", False),
    ("ログと監査証跡", "本文・題名が保存され続ける", False),
    ("キャッシュ", "他人の権限で作った結果", False),
)


# --- 1. 権限の解決（fail-closed）---------------------------------------------
def allowed_visibility(role: str) -> tuple[str, ...]:
    """役割から許可リストを引く。知らない役割は止める（fail-closed）。

    `ROLE_VISIBILITY.get(role, ("all",))` と書きたくなるが、それは
    「知らない役割には一般公開ぶんを見せる」という判断を暗黙に埋め込むこと。
    """
    if role not in ROLE_VISIBILITY:
        raise PermissionError(f"未知の役割です: {role!r}（fail-closed のため検索しません）")
    return ROLE_VISIBILITY[role]


@dataclass(frozen=True)
class Principal:
    """検索を実行する主体。権限に関わる属性をここに集約する。"""

    user_id: str
    role: str
    dept: str = ""

    @property
    def visibility(self) -> tuple[str, ...]:
        return allowed_visibility(self.role)

    def cache_scope(self) -> str:
        """キャッシュ鍵に混ぜる権限スコープ。見える範囲が同じ人は同じ文字列になる。"""
        return "vis:" + "|".join(self.visibility)


def visibility_filter(principal: Principal) -> dict:
    """検索層へ渡すフィルタ辞書。空の辞書を返してはいけない（フィルタ無しと同義）。"""
    allowed = principal.visibility
    if not allowed:
        raise PermissionError("許可リストが空です（fail-closed のため検索しません）")
    return {"visibility": list(allowed)}


# --- 2. 検索器のラッパ ---------------------------------------------------------
class AccessAwareRetriever:
    """検索に権限フィルタを必ず添えるラッパ。Principal 無しでは生成できない。"""

    def __init__(self, inner, principal: Principal) -> None:
        self.inner = inner
        self.principal = principal

    def search(self, query: str, k: int = 10, filters: dict | None = None) -> list[Hit]:
        merged = dict(filters or {})
        merged.update(visibility_filter(self.principal))  # 権限条件が常に勝つ
        return self.inner.search(query, k=k, filters=merged)


class PostFilterRetriever:
    """比較用（本番で使ってはいけない）。検索してから Python で捨てる実装。"""

    def __init__(self, inner, principal: Principal) -> None:
        self.inner = inner
        self.principal = principal

    def search(self, query: str, k: int = 10, filters: dict | None = None) -> list[Hit]:
        allowed = set(self.principal.visibility)
        return [h for h in self.inner.search(query, k=k, filters=filters)
                if h.meta.get("visibility") in allowed]


# --- 3. 混入検査 ---------------------------------------------------------------
def leaked_hits(hits: list[Hit], principal: Principal) -> list[Hit]:
    """許可されていない可視性のヒット。メタデータ欠損（None）も混入として数える。"""
    allowed = set(principal.visibility)
    return [h for h in hits if h.meta.get("visibility") not in allowed]


@dataclass
class SweepResult:
    label: str
    n_queries: int = 0
    n_hits: int = 0
    n_leaked_queries: int = 0
    n_leaked_hits: int = 0
    n_short: int = 0
    examples: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return self.n_leaked_hits == 0

    def line(self) -> str:
        return (f"{self.label:<30} クエリ{self.n_queries:>4}件 / ヒット{self.n_hits:>5}件 / "
                f"混入{self.n_leaked_hits:>3}件 / k未満{self.n_short:>4}件")


def sweep(search_fn, principal: Principal, queries: list[Query], k: int = 10,
          label: str = "", max_examples: int = 3) -> SweepResult:
    """全クエリを1つの権限で回し、混入を数える。"""
    res = SweepResult(label=label or principal.role)
    for q in queries:
        hits = search_fn(q.text, k)
        res.n_queries += 1
        res.n_hits += len(hits)
        if len(hits) < k:
            res.n_short += 1
        bad = leaked_hits(hits, principal)
        if bad:
            res.n_leaked_queries += 1
            res.n_leaked_hits += len(bad)
            for h in bad[: max(0, max_examples - len(res.examples))]:
                res.examples.append((q.query_id, h.chunk_id, str(h.meta.get("visibility"))))
    return res


# --- 4. プローブクエリ（攻撃者側の引き方）--------------------------------------
def restricted_docs(docs: list[Doc] | None = None) -> list[Doc]:
    return sorted([d for d in (docs or load_docs()) if d.visibility != "all"],
                  key=lambda d: d.doc_id)


def probe_queries(docs: list[Doc] | None = None) -> list[Query]:
    """制限文書そのものを狙って引くクエリ。業務クエリには攻撃者の引き方が無い。"""
    return [Query(query_id=f"P-{i:03d}", text=d.title.replace("（管理職限定）", ""),
                  type="probe")
            for i, d in enumerate(restricted_docs(docs), start=1)]


def check_queries() -> list[Query]:
    """混入検査に使うクエリ集合：業務クエリ120件＋プローブ。"""
    return load_queries() + probe_queries()


# --- 5. キャッシュと点ID -------------------------------------------------------
class ScopedCache:
    """検索結果のキャッシュ。key_mode で鍵の作り方を切り替えて挙動を比べる。

      "query_only" — クエリ本文だけ（最も速く、最も危ない）
      "principal"  — 権限スコープを含める（推奨）
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
        self.store[key] = retriever.search(query, k=k)
        return self.store[key]

    def invalidate_doc(self, doc_id: str) -> int:
        """指定文書を含むエントリを捨てる。権限変更・削除要求のときに必ず呼ぶ。"""
        victims = [key for key, hits in self.store.items()
                   if any(h.doc_id == doc_id for h in hits)]
        for key in victims:
            del self.store[key]
        return len(victims)


ID_NAMESPACE = uuid.NAMESPACE_URL
ID_PREFIX = "minato://chunk/"


def point_id(chunk_id: str) -> str:
    """chunk_id から決定的に点IDを作る（セッション7・13・16と同じ規約）。

    権限変更はこのIDを変えずにペイロードだけ更新する。IDを作り直すと
    「消し忘れた旧IDの点が、旧い権限のまま索引に残る」事故になる。
    """
    return str(uuid.uuid5(ID_NAMESPACE, f"{ID_PREFIX}{chunk_id}"))


# --- 6. 索引 -------------------------------------------------------------------
_INDEX: LexicalIndex | None = None


def lexical_index() -> LexicalIndex:
    global _INDEX
    if _INDEX is None:
        _INDEX = LexicalIndex().build(chunk_all(load_docs(), "fixed", size=400, overlap=80))
    return _INDEX


def main() -> None:
    docs = load_docs()
    index = lexical_index()
    member = Principal("u-1043", "member", "経理部")
    manager = Principal("u-2001", "manager", "経理部")
    queries = check_queries()

    print(f"文書 {len(docs)} 件 / 制限文書 {len(restricted_docs(docs))} 件 / "
          f"検査クエリ {len(queries)} 件（業務 {len(load_queries())} + プローブ "
          f"{len(probe_queries(docs))}）")

    print("\n=== 1. 混入検査（k=10・member 基準で数える）===")
    conditions = [
        ("フィルタ無し", lambda t, k: index.search(t, k=k), member),
        ("事後フィルタ(member)", PostFilterRetriever(index, member).search, member),
        ("事前フィルタ(member)", AccessAwareRetriever(index, member).search, member),
        ("事前フィルタ(manager)", AccessAwareRetriever(index, manager).search, manager),
    ]
    results = {}
    for label, fn, who in conditions:
        res = sweep(lambda t, k, fn=fn: fn(t, k=k), who, queries, k=10, label=label)
        results[label] = res
        print("  " + res.line())
    for qid, cid, vis in results["フィルタ無し"].examples:
        print(f"    混入例: {qid} -> {cid}（visibility={vis}）")

    print("\n=== 2. キャッシュ鍵に権限スコープを入れるか ===")
    probe = probe_queries(docs)[0].text
    for mode in ("query_only", "principal"):
        cache = ScopedCache(mode)
        first = cache.get_or_search(AccessAwareRetriever(index, manager), manager, probe)
        second = cache.get_or_search(AccessAwareRetriever(index, member), member, probe)
        print(f"  key_mode={mode:<11} 管理職 {len(first)}件 -> 一般社員 {len(second)}件 / "
              f"一般社員への混入 {len(leaked_hits(second, member))}件 / "
              f"キャッシュヒット {cache.hit_count}")

    print("\n=== 3. 権限変更は点IDを変えずにペイロードを更新する ===")
    target = restricted_docs(docs)[0]
    cache = ScopedCache("principal")
    cache.get_or_search(AccessAwareRetriever(index, manager), manager, probe)
    print(f"  {target.doc_id}#001 の点ID: {point_id(f'{target.doc_id}#001')}")
    print(f"  権限変更で捨てたキャッシュ: {cache.invalidate_doc(target.doc_id)} 件")

    print("\n=== 4. 漏洩経路（生成側の指示で塞げるのは1本だけ）===")
    for i, (name, what, by_prompt) in enumerate(LEAK_PATHS, start=1):
        print(f"  経路{i} {name:<28} {what:<24} 指示で塞げる: {'△' if by_prompt else '×'}")


if __name__ == "__main__":
    main()
