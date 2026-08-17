#!/usr/bin/env python3
"""セッション14：文書の参照関係を Python の標準データ構造だけでグラフにする。

グラフDBもグラフライブラリも使わない（requirements.txt を増やさない）。
章のすべてのスクリプトがこのモジュールを import する。

用語:
  参照名  文書タイトルから版・枝番の丸括弧を落とした呼び名（例「有給休暇の申請規程」）
  言及    本文に参照名が現れること
  エッジ  言及を解決して得た文書間のリンク。related / mentions / delegates_to の3型
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.chunk import chunk_all  # noqa: E402
from ragkit.corpus import load_docs  # noqa: E402
from ragkit.eval import hits_to_docs  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402
from ragkit.models import Doc  # noqa: E402

# 文書名として扱う語尾。これで終わる名前だけを辞書に載せる（「本規程」などを弾くため）
REF_KINDS = ("規程", "手順書", "チェックリスト", "細則", "補則")
EDGE_KINDS = ("related", "mentions", "delegates_to")
# 委任（「別に定める◯◯に従う」）を見分ける手がかり
DELEGATION_MARKERS = ("別に定める", "に従う")

CANDIDATE_K = 50  # 候補集合の大きさ（セッション9の多段検索と同じ既定）
CONTEXT_K = 10    # 生成に渡す想定の件数

_TRAILING_PAREN = re.compile(r"（[^（）]*）$")
_QUOTED = re.compile(r"「([^「」]+)」")
_RELATED_SECTION = re.compile(r"##\s*関連文書\n(.*?)(?=\n##|\Z)", re.DOTALL)
_SENTENCE = re.compile(r"(?<=。)|\n")


# ---------------------------------------------------------------------------
# 1. 参照名の辞書（エンティティの語彙）
# ---------------------------------------------------------------------------
def ref_name(title: str) -> str:
    """タイトルから版・枝番の丸括弧を落として参照名にする。

    「有給休暇の申請手順書（第1版）」-> 「有給休暇の申請手順書」
    「多要素認証の登録規程（2026年度版）」-> 「多要素認証の登録規程」
    """
    return _TRAILING_PAREN.sub("", title)


def build_name_index(docs: list[Doc]) -> dict[str, tuple[str, ...]]:
    """参照名 -> その名前で呼ばれうる文書。文書種別の語で終わる名前だけを載せる。"""
    index: dict[str, list[str]] = defaultdict(list)
    for d in docs:
        name = ref_name(d.title)
        if name.endswith(REF_KINDS):
            index[name].append(d.doc_id)
    return {name: tuple(sorted(ids)) for name, ids in sorted(index.items())}


# ---------------------------------------------------------------------------
# 2. 言及の抽出（辞書ベース）と、書式からの抽出（構造ベース）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Mention:
    src: str                      # 言及した文書
    name: str                     # 本文に現れた参照名
    kind: str                     # related / mentions / delegates_to
    candidates: tuple[str, ...]   # 参照先の候補（複数ありうる）

    @property
    def ambiguous(self) -> bool:
        return len(self.candidates) > 1


def mention_kind(doc: Doc, name: str) -> str:
    """言及がどの型のエッジになるかを、書かれ方から決める。

    関連文書の一覧に並んでいるだけなら related、
    「別に定める◯◯に従う」のように条件を委ねているなら delegates_to。
    """
    for section in _RELATED_SECTION.findall(doc.body):
        if name in section:
            return "related"
    for sent in _SENTENCE.split(doc.body):
        if name in sent and any(w in sent for w in DELEGATION_MARKERS):
            return "delegates_to"
    return "mentions"


def extract_mentions(docs: list[Doc], index: dict[str, tuple[str, ...]]) -> list[Mention]:
    """辞書（既知のタイトル）を本文に照合して言及を拾う。LLM は使わない。"""
    out: list[Mention] = []
    for d in docs:
        for name, ids in index.items():
            if name not in d.body:
                continue
            candidates = tuple(i for i in ids if i != d.doc_id)  # 自己参照は捨てる
            if candidates:
                out.append(Mention(d.doc_id, name, mention_kind(d, name), candidates))
    return out


def candidate_expressions(doc: Doc) -> list[str]:
    """辞書を使わず、書式だけから「参照らしい表現」を拾う。

    ・かぎ括弧で囲まれ、文書種別の語で終わるもの
    ・「## 関連文書」節に読点区切りで並んでいるもの
    """
    found: list[str] = []
    for m in _QUOTED.finditer(doc.body):
        name = m.group(1).strip()
        if name.endswith(REF_KINDS):
            found.append(name)
    for section in _RELATED_SECTION.findall(doc.body):
        for seg in re.split(r"[、。\n]", section):
            seg = seg.strip()
            if seg.endswith(REF_KINDS):
                found.append(seg)
    return found


def dangling_references(docs: list[Doc], index: dict[str, tuple[str, ...]]) -> list[tuple[str, str]]:
    """書式からは参照に見えるのに、辞書で解決できない参照（リンク切れ）。"""
    return [(d.doc_id, name) for d in docs
            for name in candidate_expressions(d) if name not in index]


# ---------------------------------------------------------------------------
# 3. グラフ本体（dict と set だけで作る）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    kind: str


class DocGraph:
    """文書グラフ。ノードは文書と部署、エッジは参照（doc->doc）と所管（doc->dept）。

    link="all"    : 参照先が絞れないときは候補すべてにつなぐ（取りこぼさない代わりに汚れる）
    link="newest" : 更新日が最新の1件だけにつなぐ（旧版を引かない代わりに取りこぼす）
    """

    def __init__(self, docs: list[Doc], link: str = "all") -> None:
        if link not in ("all", "newest"):
            raise ValueError(f"link は 'all' か 'newest' を指定してください（受け取った値: {link}）")
        self.link = link
        self.docs = {d.doc_id: d for d in docs}
        self.by_title = {d.title: d.doc_id for d in docs}
        self.name_index = build_name_index(docs)
        self.mentions = extract_mentions(docs, self.name_index)

        edges: set[Edge] = set()
        for m in self.mentions:
            for dst in self.resolve(m):
                edges.add(Edge(m.src, dst, m.kind))
        self.edges = tuple(sorted(edges, key=lambda e: (e.src, e.dst, e.kind)))

        adj_out: dict[str, list[Edge]] = defaultdict(list)
        adj_in: dict[str, list[Edge]] = defaultdict(list)
        for e in self.edges:
            adj_out[e.src].append(e)
            adj_in[e.dst].append(e)
        self.adj_out = {k: tuple(v) for k, v in adj_out.items()}
        self.adj_in = {k: tuple(v) for k, v in adj_in.items()}

        # 部署ノード（メタデータから0円で作れるエッジ）
        self.depts = tuple(sorted({d.dept for d in docs}))
        self.dept_docs = {dept: tuple(sorted(d.doc_id for d in docs if d.dept == dept))
                          for dept in self.depts}

    # --- 参照の解決 --------------------------------------------------------
    def resolve(self, m: Mention) -> tuple[str, ...]:
        if self.link == "all" or len(m.candidates) == 1:
            return m.candidates
        newest = max(m.candidates, key=lambda i: (self.docs[i].updated_at, i))
        return (newest,)

    # --- 参照 --------------------------------------------------------------
    @property
    def n_nodes(self) -> int:
        return len(self.docs) + len(self.depts)

    def edges_of(self, kind: str) -> tuple[Edge, ...]:
        return tuple(e for e in self.edges if e.kind == kind)

    def in_degree(self, doc_id: str, kinds: tuple[str, ...] | None = None) -> int:
        return len([e for e in self.adj_in.get(doc_id, ()) if kinds is None or e.kind in kinds])

    def out_degree(self, doc_id: str, kinds: tuple[str, ...] | None = None) -> int:
        return len([e for e in self.adj_out.get(doc_id, ()) if kinds is None or e.kind in kinds])

    def neighbors(self, doc_id: str, kinds: tuple[str, ...] | None = None,
                  backward: bool = False) -> tuple[str, ...]:
        out = [e.dst for e in self.adj_out.get(doc_id, ()) if kinds is None or e.kind in kinds]
        if backward:
            out += [e.src for e in self.adj_in.get(doc_id, ()) if kinds is None or e.kind in kinds]
        return tuple(sorted(set(out)))

    def cross_theme_edges(self) -> tuple[Edge, ...]:
        """テーマ（語彙のかたまり）をまたぐエッジ。theme は答え合わせにだけ使う。"""
        return tuple(e for e in self.edges if self.docs[e.src].theme != self.docs[e.dst].theme)

    # --- 探索 --------------------------------------------------------------
    def expand(self, seeds, hops: int = 1, kinds: tuple[str, ...] | None = None,
               backward: bool = False) -> set[str]:
        """seeds から hops 回だけ辿って到達できる文書集合（seeds を含む）。"""
        seen, frontier = set(seeds), set(seeds)
        for _ in range(max(0, hops)):
            nxt: set[str] = set()
            for doc_id in frontier:
                nxt.update(self.neighbors(doc_id, kinds, backward))
            nxt -= seen
            if not nxt:
                break
            seen |= nxt
            frontier = nxt
        return seen

    def path(self, src: str, dst: str, max_hops: int = 3,
             kinds: tuple[str, ...] | None = None) -> list[str]:
        """src から dst への最短経路。見つからなければ空リスト。"""
        prev: dict[str, str] = {src: ""}
        frontier = [src]
        for _ in range(max(1, max_hops)):
            if dst in prev:
                break
            nxt: list[str] = []
            for doc_id in frontier:
                for nb in self.neighbors(doc_id, kinds):
                    if nb not in prev:
                        prev[nb] = doc_id
                        nxt.append(nb)
            frontier = nxt
            if not frontier:
                break
        if dst not in prev:
            return []
        path = [dst]
        while prev[path[-1]]:
            path.append(prev[path[-1]])
        return list(reversed(path))

    # --- 表示 --------------------------------------------------------------
    def title(self, doc_id: str) -> str:
        return self.docs[doc_id].title

    def label(self, doc_id: str) -> str:
        return f"{doc_id} {self.docs[doc_id].title}"


# ---------------------------------------------------------------------------
# 4. 検索とグラフをまとめた実験台
# ---------------------------------------------------------------------------
class Bench:
    """コーパス・チャンク・BM25索引・グラフをまとめて用意する。"""

    def __init__(self, link: str = "all") -> None:
        self.docs = load_docs()
        self.by_id = {d.doc_id: d for d in self.docs}
        self.by_title = {d.title: d.doc_id for d in self.docs}
        self.chunks = chunk_all(self.docs, "fixed", size=400, overlap=80)
        self.index = LexicalIndex().build(self.chunks)
        self.graph = DocGraph(self.docs, link=link)
        self._parent_index = None

    def search_docs(self, query: str, k: int = CONTEXT_K) -> list[str]:
        """検索結果を順位を保ったまま doc_id の列に畳む。"""
        return hits_to_docs(self.index.search(query, k=k))

    def has_answer(self, doc_ids, fact: str) -> bool:
        """答えの文字列が、その文書集合のどこかに書かれているか。"""
        return any(fact in self.by_id[d].full_text for d in doc_ids)

    def parent_index(self) -> LexicalIndex:
        """親子チャンク（子で検索し親で答える）の索引。セッション4の方式をそのまま使う。"""
        if self._parent_index is None:
            chunks = chunk_all(self.docs, "parent_window", child=200, window=600)
            self._parent_index = LexicalIndex().build(chunks)
        return self._parent_index

    def parent_context(self, query: str, k: int = CONTEXT_K) -> str:
        """親子チャンクで組み立てたコンテキスト（親テキストの連結）。"""
        hits = self.parent_index().search(query, k=k)
        return "\n".join(h.meta.get("parent_text", h.text) for h in hits)

    def doc_id(self, title: str) -> str:
        return self.by_title[title]


# ---------------------------------------------------------------------------
# 5. マルチホップ質問（この章で定義する。queries.jsonl には入っていない）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class HopQuestion:
    qid: str
    text: str
    bridge_title: str  # 参照元（起点）になる文書
    answer_title: str  # 答えが書かれている文書
    fact: str          # 答えの本体。コンテキストに載ったかの判定に使う


MULTIHOP_QUESTIONS: tuple[HopQuestion, ...] = (
    HopQuestion(
        "MH-01", "情報の持ち出しで電子媒体を使うときの条件を知りたい",
        "情報の持ち出しに関する補則", "USBメモリの利用規程", "会社が貸与した暗号化機器のみ"),
    HopQuestion(
        "MH-02", "外部サービスを利用しているときに問題が起きた場合、社内ではどう扱う決まりですか",
        "外部サービスの利用申請に関する補則", "セキュリティ事故の報告規程", "発見から1時間以内"),
    HopQuestion(
        "MH-03", "PCの返却をするとき、社内システムの利用が止まるタイミングを知りたい",
        "PCの返却に関する補則", "退職時のアカウント停止規程", "最終出社日の18時"),
)


def hop_report(bench: Bench, q: HopQuestion) -> dict:
    """1つのマルチホップ質問について、検索とグラフ拡張の結果をまとめる。"""
    top = bench.search_docs(q.text, k=CONTEXT_K)
    cand = bench.search_docs(q.text, k=CANDIDATE_K)
    bridge = bench.doc_id(q.bridge_title)
    answer = bench.doc_id(q.answer_title)
    typed = bench.graph.expand(cand, hops=1, kinds=("delegates_to",))
    untyped = bench.graph.expand(cand, hops=1)
    return {
        "qid": q.qid,
        "text": q.text,
        "fact": q.fact,
        "bridge": bridge,
        "answer": answer,
        "top_docs": top,
        "cand_docs": cand,
        "answer_in_top": bench.has_answer(top, q.fact),
        "answer_in_cand": bench.has_answer(cand, q.fact),
        "bridge_in_top": bridge in top,
        "bridge_in_cand": bridge in cand,
        "answer_reached": answer in typed,
        "added_typed": len(typed) - len(cand),
        "added_untyped": len(untyped) - len(cand),
        "path": bench.graph.path(bridge, answer, max_hops=2, kinds=("delegates_to",)),
    }
