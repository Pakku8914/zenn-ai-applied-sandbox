"""セッション16の共通ヘルパ：増分更新・孤児の掃除・版の切り替え・鮮度・A/B。

セッション7で作った道具（`uuid5(chunk_id)` による決定的な点ID、エイリアスの付け替え）を、
「事故なく回せる手順」に組み上げるための部品を置く。仕組みそのものの説明はセッション7を参照。

この章のスクリプトは埋め込みモデルを使わない。ベクトルは本文から決定的に作る（vector_for）。
同じ本文なら同じベクトル、違う本文なら違うベクトルになるので「更新した点のベクトルが
入れ替わったか」は確かめられるが、意味の近さは表さない（検索の精度は測れない）。
"""

from __future__ import annotations

import hashlib
import math
import sys
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
from qdrant_client.models import (  # noqa: E402
    CreateAlias,
    CreateAliasOperation,
    DeleteAlias,
    DeleteAliasOperation,
    Distance,
    PointIdsList,
    PointStruct,
    VectorParams,
)

from ragkit.dense import VECTOR_SIZE  # noqa: E402
from ragkit.models import Chunk, Doc  # noqa: E402

# 本書の基準日。as-of（いつ時点の話か）の既定値にする
ASOF = "2026-08-15"

# 点IDの名前空間（セッション7と同じ規約。ここを変えると全点のIDが変わる）
ID_NAMESPACE = uuid.NAMESPACE_URL
ID_PREFIX = "minato://chunk/"


# --- 同定と指紋 ---------------------------------------------------------------
def point_id(chunk_id: str) -> str:
    """chunk_id から決定的に点IDを作る（セッション7の規約をそのまま使う）。"""
    return str(uuid.uuid5(ID_NAMESPACE, f"{ID_PREFIX}{chunk_id}"))


def content_hash(text: str) -> str:
    """本文の指紋。セッション3の取り込みで使ったものと同じ考え方。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def vector_for(text: str) -> np.ndarray:
    """本文から決定的にベクトルを作る（この章の実験用の代役）。

    同じ本文なら同じベクトル、違う本文なら違うベクトルになる。
    埋め込みモデルの代わりであって、意味の近さは表さない。
    """
    rng = np.random.default_rng(int(content_hash(text), 16) % (2**32))
    v = rng.normal(size=VECTOR_SIZE).astype(np.float32)
    return v / np.linalg.norm(v)


# --- 長さを指定して作るテスト文書 ---------------------------------------------
_FILLER = (
    "みなと商事の社内手続きに関する説明です。申請は所定の様式で提出してください。"
    "承認は原則として3営業日以内に行われます。不明点は総務部までお問い合わせください。"
)


def filler(n: int) -> str:
    """ちょうど n 文字の本文を作る（同じ n なら常に同じ文字列）。"""
    if n <= 0:
        return ""
    return (_FILLER * (n // len(_FILLER) + 1))[:n]


def make_doc(doc_id: str, total_chars: int, updated_at: str = ASOF, tail: str = "") -> Doc:
    """`full_text` がちょうど total_chars 文字になる文書を作る。

    チャンク数を狙って作れるので、孤児チャンクの再現に使う。
    tail は本文の末尾に置く目印（改訂で消える一文など）。
    """
    title = f"{doc_id} 申請手順"
    n = total_chars - len(title) - 1 - len(tail)  # -1 は title と body の間の改行
    if n < 0:
        raise ValueError(f"total_chars が短すぎます: {total_chars}")
    return Doc(
        doc_id=doc_id,
        title=title,
        body=filler(n) + tail,
        category="オフィス",
        updated_at=updated_at,
        visibility="all",
        dept="総務部",
        source_type="procedure",
        theme="s16",
    )


# --- コレクションの操作 -------------------------------------------------------
def ensure(client, name: str) -> None:
    """無ければ作る（あれば触らない）。作り直さないのがポイント。"""
    if not client.collection_exists(name):
        client.create_collection(
            name, vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE)
        )


def recreate(client, name: str) -> None:
    if client.collection_exists(name):
        client.delete_collection(name)
    ensure(client, name)


def drop(client, *names: str) -> None:
    for name in names:
        if client.collection_exists(name):
            client.delete_collection(name)


def count(client, name: str) -> int:
    """点数を数える（反映待ちに左右されないよう exact で数える）。"""
    return client.count(name, exact=True).count


def index_state(client, collection: str) -> dict[str, dict]:
    """索引に「いま何が入っているか」を {chunk_id: {...}} で返す。"""
    out: dict[str, dict] = {}
    offset = None
    while True:
        records, offset = client.scroll(
            collection, limit=256, offset=offset, with_payload=True, with_vectors=False
        )
        for r in records:
            p = r.payload or {}
            out[p.get("chunk_id", str(r.id))] = {
                "point_id": r.id,
                "doc_id": p.get("doc_id"),
                "content_hash": p.get("content_hash"),
                "indexed_at": p.get("indexed_at"),
                "method": p.get("method"),
                "text": p.get("text", ""),
            }
        if offset is None:
            return out


def find_text(client, collection: str, needle: str) -> list[str]:
    """本文に needle を含む点の chunk_id を返す（小さなコレクション向けの総当たり）。"""
    return sorted(
        cid for cid, info in index_state(client, collection).items() if needle in info["text"]
    )


def doc_chunk_ids(client, collection: str, doc_id: str) -> list[str]:
    return sorted(
        cid for cid, info in index_state(client, collection).items() if info["doc_id"] == doc_id
    )


# --- 差分検出 -----------------------------------------------------------------
@dataclass(frozen=True)
class DocDiff:
    added: list[str]
    changed: list[str]
    removed: list[str]
    unchanged: list[str]

    def counts(self) -> dict[str, int]:
        return {
            "added": len(self.added),
            "changed": len(self.changed),
            "removed": len(self.removed),
            "unchanged": len(self.unchanged),
        }


def doc_state(docs: list[Doc]) -> dict[str, str]:
    """{doc_id: 本文の指紋}。前回の状態として保存しておく値。"""
    return {d.doc_id: content_hash(d.full_text) for d in docs}


def diff_docs(previous: dict[str, str], docs: list[Doc]) -> DocDiff:
    """前回の状態と今回の文書集合を突き合わせて、追加・更新・削除に分ける。"""
    current = doc_state(docs)
    both = set(current) & set(previous)
    return DocDiff(
        added=sorted(set(current) - set(previous)),
        changed=sorted(d for d in both if current[d] != previous[d]),
        removed=sorted(set(previous) - set(current)),
        unchanged=sorted(d for d in both if current[d] == previous[d]),
    )


def diff_by_updated_at(docs: list[Doc], since: str) -> list[str]:
    """更新日だけで差分を取る方法（削除は検出できず、更新日の直し忘れも拾えない）。"""
    return sorted(d.doc_id for d in docs if d.updated_at > since)


# --- 冪等な同期 ---------------------------------------------------------------
@dataclass
class SyncStats:
    upserted: int = 0
    deleted: int = 0
    unchanged: int = 0
    orphans: list[str] = field(default_factory=list)

    def line(self) -> str:
        return (
            f"追加更新 {self.upserted} / 削除 {self.deleted} / "
            f"変更なし {self.unchanged} / 孤児 {len(self.orphans)}"
        )


def sync(
    client,
    collection: str,
    chunks: list[Chunk],
    indexed_at: str = ASOF,
    prune: bool = True,
    dry_run: bool = False,
) -> SyncStats:
    """索引を「欲しい状態」にそろえる。何度実行しても同じ結果になる（冪等）。

    - 指紋が変わったチャンクだけ upsert する（変わっていない点は触らない）
    - 欲しい集合に無い点＝孤児チャンクを削除する（prune=False で事故を再現できる）
    - dry_run=True なら書き込まず、実行計画だけを返す
    """
    ensure(client, collection)
    current = index_state(client, collection)
    stats = SyncStats()

    points: list[PointStruct] = []
    for c in chunks:
        digest = content_hash(c.text)
        known = current.get(c.chunk_id)
        if known and known["content_hash"] == digest:
            stats.unchanged += 1
            continue
        points.append(
            PointStruct(
                id=point_id(c.chunk_id),
                vector=vector_for(c.text).tolist(),
                payload={
                    "chunk_id": c.chunk_id,
                    "doc_id": c.doc_id,
                    "text": c.text,
                    "content_hash": digest,
                    "indexed_at": indexed_at,
                    "updated_at": c.meta.get("updated_at", ""),
                    "method": c.meta.get("method", ""),
                },
            )
        )
    stats.upserted = len(points)

    desired = {c.chunk_id for c in chunks}
    stats.orphans = sorted(cid for cid in current if cid not in desired)
    if dry_run:
        return stats

    for i in range(0, len(points), 128):
        client.upsert(collection, points=points[i : i + 128], wait=True)
    if prune and stats.orphans:
        client.delete(
            collection,
            points_selector=PointIdsList(points=[point_id(cid) for cid in stats.orphans]),
            wait=True,
        )
        stats.deleted = len(stats.orphans)
    return stats


# --- 鮮度 ---------------------------------------------------------------------
def lag_days(updated_at: str, indexed_at: str) -> int:
    """元データが更新されてから索引に載るまでの日数。"""
    return (date.fromisoformat(indexed_at) - date.fromisoformat(updated_at)).days


def percentile(values: list[int], p: float) -> int:
    """最近接順位法のパーセンタイル（値の個数が少なくても意味が崩れない）。"""
    if not values:
        return 0
    s = sorted(values)
    rank = max(1, math.ceil(p * len(s)))
    return s[min(rank, len(s)) - 1]


# --- A/B ----------------------------------------------------------------------
def bucket(key: str, salt: str = "s16", ratio: int = 50) -> str:
    """キーから決定的に群を決める。同じキーは常に同じ群になる。

    ratio は B（新方式）に回す割合（%）。salt を変えると割り当てを引き直せる。
    """
    digest = hashlib.md5(f"{salt}:{key}".encode("utf-8")).hexdigest()
    return "B" if int(digest[:8], 16) % 100 < ratio else "A"


def tail_prob(n: int, k: int) -> float:
    """互角（勝率50%）の2つの検索器で、n 回中 k 回以上勝つ確率。"""
    return sum(math.comb(n, i) for i in range(k, n + 1)) / 2**n


# --- エイリアス ---------------------------------------------------------------
def alias_target(client, alias: str) -> str | None:
    for a in client.get_aliases().aliases:
        if a.alias_name == alias:
            return a.collection_name
    return None


def switch_alias(client, alias: str, target: str) -> None:
    """エイリアスを付け替える。削除と作成を1リクエストにまとめる（原子的に入れ替わる）。"""
    ops = []
    if alias_target(client, alias) is not None:
        ops.append(DeleteAliasOperation(delete_alias=DeleteAlias(alias_name=alias)))
    ops.append(
        CreateAliasOperation(create_alias=CreateAlias(collection_name=target, alias_name=alias))
    )
    client.update_collection_aliases(change_aliases_operations=ops)


def drop_alias(client, alias: str) -> None:
    if alias_target(client, alias) is not None:
        client.update_collection_aliases(
            change_aliases_operations=[
                DeleteAliasOperation(delete_alias=DeleteAlias(alias_name=alias))
            ]
        )
