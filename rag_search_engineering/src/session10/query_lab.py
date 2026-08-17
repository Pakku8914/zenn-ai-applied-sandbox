#!/usr/bin/env python3
"""セッション10の小道具：入力側（クエリ）を整える道具一式。

検索側（索引・スコア・並べ替え）は触らない。触るのは「検索器に渡す文字列」だけ。

  classify              クエリを5つの型に分類する（優先順位付きルール）
  expand_query          略語をクエリ側で展開する（横断復習01で作ったものを章の形に整える）
  drop_query_stopwords  クエリ側の定型句を落とす
  decompose             複数条件クエリをサブ質問に分ける
  hyde_document         仮想文書を作る（LLMClient を差し替えられる形にしてある）
  resolve_followup      会話履歴から自立したクエリを作る
  suggest_term          索引の語彙に無い語へ訂正候補を出す
  RewriteRetriever      書き換え関数を1つ挟むだけの検索器
  MultiQueryRetriever   複数のクエリを投げて RRF で統合する検索器
  HydeRetriever         仮想文書を足してから検索する検索器
  TypeRouter            型ごとに打ち手を割り当てる検索器（呼び出し回数を数える）
  CountingClient        任意の LLMClient を包んで呼び出し回数を数える

検索器はどれも `search(query, k, filters)` を持つので、`ragkit.eval.evaluate` に
そのまま渡せる（既存の評価コードを1行も変えずに効果を測れるのが、この形にしている理由）。
"""

from __future__ import annotations

import difflib
import re
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ragkit.hybrid import rrf_fuse  # noqa: E402
from ragkit.lexical import LexicalIndex  # noqa: E402
from ragkit.models import Chunk  # noqa: E402
from ragkit.tokenize_ja import normalize  # noqa: E402

# ---------------------------------------------------------------------------
# 1. クエリの型（分類）
# ---------------------------------------------------------------------------

QUERY_TYPES = ("keyword", "natural", "abbrev", "multi_condition", "temporal")

# 時点性のクエリに現れる語。「今週」を入れていないのは、社員食堂のメニューのような
# 「そもそもコーパスに無い」質問まで時点性に寄せてしまうため（回答不能の判定は S11）。
TEMPORAL_MARKERS = ("現在", "最新", "今年", "今月", "最近", "改定", "旧版", "時点")

# 複数条件のクエリに現れる語と、「AとB」の並列パターン
MULTI_MARKERS = ("違い", "比較")
AND_PATTERN = re.compile(r"[0-9a-z一-龥ぁ-んァ-ヶ]と[0-9a-z一-龥ァ-ヶ]")

# 自然文の文末表現。これがあると「キーワード列」ではない
SENTENCE_MARKERS = ("ください", "ですか", "でしょうか", "ますか", "知りたい", "教えて", "何")


def is_temporal(q: str) -> bool:
    return any(m in q for m in TEMPORAL_MARKERS)


def is_multi_condition(q: str) -> bool:
    return any(m in q for m in MULTI_MARKERS) or bool(AND_PATTERN.search(q))


def is_abbrev(q: str) -> bool:
    """同義語辞書が発火するかどうかで判定する（辞書と分類の基準を1つにする）。"""
    return expand_query(q) != q


def is_keyword(q: str) -> bool:
    return len(q.split()) >= 2 and not any(m in q for m in SENTENCE_MARKERS)


RULES = {
    "temporal": is_temporal,
    "multi_condition": is_multi_condition,
    "abbrev": is_abbrev,
    "keyword": is_keyword,
}
# 上から順に当てて、最初に当たった型を返す。**順序が結果を決める**
DEFAULT_ORDER = ("temporal", "multi_condition", "abbrev", "keyword")


def classify(text: str, order: tuple[str, ...] = DEFAULT_ORDER) -> str:
    """クエリを5つの型のどれかに分類する。

    回答不能（unanswerable）は返さない。クエリ文だけを見ても「コーパスに答えがあるか」は
    分からないためで、その判定は検索してから行う（セッション11の主題）。
    """
    q = normalize(text)
    for name in order:
        if RULES[name](q):
            return name
    return "natural"


def confusion(queries, order: tuple[str, ...] = DEFAULT_ORDER) -> dict[str, Counter]:
    """正解の型 × 予測した型の集計表を作る。"""
    table: dict[str, Counter] = {}
    for q in queries:
        table.setdefault(q.type, Counter())[classify(q.text, order)] += 1
    return table


def print_confusion(table: dict[str, Counter], types=QUERY_TYPES) -> None:
    header = "gold / pred"
    print(f"{header:<18}" + "".join(f"{t:>16}" for t in types))
    for gold in sorted(table):
        row = table[gold]
        print(f"{gold:<18}" + "".join(f"{row.get(t, 0):>16}" for t in types))


# ---------------------------------------------------------------------------
# 2. ルールベースの書き換え（正規化・同義語・定型句）
# ---------------------------------------------------------------------------

# 左が利用者の言い方、右がコーパス側の正式名称。文書には正式名称しか書かれていない。
# 横断復習01で作った辞書をそのまま引き継いでいる（辞書を章ごとに作り直さない）。
SYNONYMS: dict[str, str] = {
    "年休": "有給休暇",
    "有休": "有給休暇",
    "残業": "時間外労働",
    "育休": "育児休業",
    "定期代": "通勤交通費",
    "パソコン": "貸与PC",
    "スマホ": "貸与スマートフォン",
    "携帯": "貸与スマートフォン",
    "パス": "パスワード",
    "PW": "パスワード",
    "MFA": "多要素認証",
    "二要素認証": "多要素認証",
    "2段階認証": "多要素認証",
    "社員証": "入退館カード",
    "フリーアドレス": "座席",
    "フィッシング": "標的型メール",
    "不審メール": "標的型メール",
    "SaaS": "外部サービス",
    "クラウドサービス": "外部サービス",
    "インシデント": "セキュリティ事故",
}


def expand_query(text: str, table: dict[str, str] | None = None) -> str:
    """クエリ側だけで同義語を足す。索引は作り直さない。

    約束ごとが2つある。

      1. 辞書のキーも、索引と同じ `normalize()` を通してから照合する（S03）
         こうしないと全角の「ＭＦＡ」が辞書に当たらない
      2. 正式名称がすでにクエリに入っているときは足さない
         同じ語を2回入れると tf が水増しされ、その語を含む文書が不当に上がる（S05）
    """
    table = SYNONYMS if table is None else table
    q = normalize(text)
    extra: list[str] = []
    added: set[str] = set()
    for key, canon in table.items():
        c = normalize(canon)
        if normalize(key) in q and c not in q and c not in added:
            added.add(c)
            extra.append(canon)
    return f"{text} {' '.join(extra)}" if extra else text


def expand_query_naive(text: str, table: dict[str, str] | None = None) -> str:
    """素朴版：辞書のキーをそのまま置換する。2つの理由で壊れる（教材用）。

      - 部分文字列に当たる：「パスワード」の中の「パス」まで置換してしまう
      - 表記ゆれに当たらない：全角の「ＭＦＡ」は素の `in` では見つからない
    """
    table = SYNONYMS if table is None else table
    out = text
    for key, canon in table.items():
        out = out.replace(key, canon)
    return out


# クエリ側の定型句。長いものから順に消す（短いものを先に消すと長い句が壊れる）
QUERY_STOPPHRASES = (
    "について教えてください",
    "を教えてください",
    "を知りたい",
    "教えてください",
    "知りたい",
    "を教えて",
)


def drop_query_stopwords(text: str, phrases: tuple[str, ...] = QUERY_STOPPHRASES) -> str:
    """「〜を教えてください」のような、どの文書にも同じだけ現れる定型句を落とす。"""
    out = text
    for phrase in phrases:
        out = out.replace(phrase, " ")
    return re.sub(r"\s+", " ", out).strip()


# ---------------------------------------------------------------------------
# 3. HyDE（仮想文書生成）
# ---------------------------------------------------------------------------

HYDE_SYSTEM = (
    "あなたは「みなと商事」の社内規程を書く担当者です。"
    "質問に答える規程の一節を、150字程度の日本語で書いてください。"
)


def hyde_prompt(query: str) -> str:
    return f"次の質問に答える社内規程の一節を書いてください。\n質問: {query}"


def hyde_document(query: str, client) -> str:
    """仮想文書（hypothetical document）を1本作る。"""
    return client.complete(HYDE_SYSTEM, hyde_prompt(query)).text


def hyde_query(query: str, document: str) -> str:
    """仮想文書をクエリに足す。**元のクエリを捨てない**のが安全側の設計。

    仮想文書だけで検索すると、生成が外したときに元の語まで失われる。
    """
    return f"{query} {document}"


def _hyde_doc(topic: str, detail: str) -> str:
    """仮想文書のひな形。主題語（正式名称）が必ず2回入る。"""
    return (
        f"{topic}に関する社内規程では、{detail}"
        f"{topic}の申請は社内ポータルの所定の様式から行い、"
        f"不明な点は所属部門の担当窓口に確認してください。"
    )


# 主題 -> その主題に付ける一文
HYDE_TOPIC_DETAIL: dict[str, str] = {
    "有給休暇": "取得は原則として事前に届け出ることとしています。",
    "時間外労働": "実施前に上長の承認を得ることとしています。",
    "育児休業": "開始予定日の前に申出書を提出することとしています。",
    "通勤交通費": "経路と金額を届け出て精算することとしています。",
    "貸与PC": "貸与時に台帳へ登録することとしています。",
    "貸与スマートフォン": "業務目的の利用に限ることとしています。",
    "パスワード": "定期的な変更と使い回しの禁止を定めています。",
    "多要素認証": "全アカウントで有効化することを定めています。",
    "入退館カード": "紛失時はただちに届け出ることとしています。",
    "座席": "私物を残さず退社することとしています。",
    "標的型メール": "開かずに報告することとしています。",
    "外部サービス": "利用前に審査を受けることとしています。",
    "セキュリティ事故": "発見者がただちに報告することとしています。",
    "会議室": "予約の上で利用することとしています。",
}

# needle -> 仮想文書が語る主題。**上から順に照合するので、長いキーを先に置く**
# （「パス」を「パスワード」より先に置くと、パスワードの質問まで「パス」で当たってしまう）
HYDE_NEEDLE_TOPIC: dict[str, str] = {
    "有給休暇": "有給休暇",
    "年休": "有給休暇",
    "有休": "有給休暇",
    "時間外労働": "時間外労働",
    "残業": "時間外労働",
    "育児休業": "育児休業",
    "育休": "育児休業",
    "通勤交通費": "通勤交通費",
    "定期代": "通勤交通費",
    "貸与PC": "貸与PC",
    "パソコン": "貸与PC",
    "貸与スマートフォン": "貸与スマートフォン",
    "スマホ": "貸与スマートフォン",
    "携帯": "貸与スマートフォン",
    "パスワード": "パスワード",
    "PW": "パスワード",
    "パス": "パスワード",
    "多要素認証": "多要素認証",
    "MFA": "多要素認証",
    "二要素認証": "多要素認証",
    "2段階認証": "多要素認証",
    "入退館カード": "入退館カード",
    "社員証": "入退館カード",
    "座席": "座席",
    "フリーアドレス": "座席",
    "標的型メール": "標的型メール",
    "フィッシング": "標的型メール",
    "不審メール": "標的型メール",
    "外部サービス": "外部サービス",
    "SaaS": "外部サービス",
    "クラウドサービス": "外部サービス",
    "セキュリティ事故": "セキュリティ事故",
    "インシデント": "セキュリティ事故",
    "会議室": "会議室",
    # ここだけ意図的に主題をずらしてある。「駐車場」と聞かれて「通勤交通費」の話を
    # 書いてしまう＝主題のずれた幻覚を、決定的に再現するための仕掛け
    "駐車場": "通勤交通費",
}

HYDE_STUB_RULES: dict[str, str] = {
    needle: _hyde_doc(topic, HYDE_TOPIC_DETAIL[topic])
    for needle, topic in HYDE_NEEDLE_TOPIC.items()
}

# 主題が分からないときに返る当たり障りのない一般論。どの文書にもある語だけでできている
HYDE_DEFAULT = (
    "社内規程では、申請は所定の様式に必要事項を記入し、所属部門の担当窓口に提出します。"
    "承認後に手続きが完了し、期限を過ぎた場合は翌月の受付となります。"
    "詳細は社内ポータルの手順書を参照してください。"
)


def make_hyde_client():
    """HyDE 用の StubClient を作る（APIキー不要・決定的）。

    StubClient は「入力に含まれるキーワードで分岐する決定的な応答」なので、
    ここで返る文章は **LLM の実力ではなく、私たちが置いた仮定** である。
    HyDE の効果の大きさをこれで測ることはできない。測れるのは「機構」だけ。
    """
    from ragkit.llm import StubClient

    return StubClient(rules=HYDE_STUB_RULES, default=HYDE_DEFAULT)


# ---------------------------------------------------------------------------
# 4. 多クエリとクエリ分解
# ---------------------------------------------------------------------------

# 「AとBの◯◯の違い」を2本のサブ質問に割る
DECOMPOSE_RE = re.compile(r"(?P<a>.+?)と(?P<b>.+?)の(?P<aspect>.+?)の違い")


def decompose(text: str) -> list[str]:
    """複数条件クエリをサブ質問に分ける。分けられなければ元のまま1本で返す。"""
    m = DECOMPOSE_RE.search(text)
    if not m:
        return [text]
    aspect = m.group("aspect")
    return [f"{m.group('a')}の{aspect}", f"{m.group('b')}の{aspect}"]


def multi_query(text: str, table: dict[str, str] | None = None) -> list[str]:
    """1つのクエリから複数の言い換えを作る（ルールベースの多クエリ生成）。

    LLM を使わずに作れる言い換えは「辞書で置き換えた版」と「定型句を落とした版」。
    重複は落とし、元のクエリは必ず先頭に残す。
    """
    variants = [text, expand_query(text, table), drop_query_stopwords(text)]
    out: list[str] = []
    for v in variants:
        v = v.strip()
        if v and v not in out:
            out.append(v)
    return out


# ---------------------------------------------------------------------------
# 5. 会話文脈からの自立化
# ---------------------------------------------------------------------------

DEIXIS = ("それ", "その", "これ", "この", "あれ", "上記", "さっき", "前述", "もっと")


def needs_context(text: str) -> bool:
    """指示語を含むか。含むなら、そのままでは検索できない（自立していない）。"""
    q = normalize(text)
    return any(d in q for d in DEIXIS)


def carry_over(history: list[str], text: str) -> str:
    """ルール版の自立化：直前の発話をそのまま前に付ける。安いが冗長になる。"""
    if not history or not needs_context(text):
        return text
    return f"{history[-1]} {text}"


FOLLOWUP_SYSTEM = (
    "あなたは検索クエリを整える担当者です。会話履歴を読み、最後の発話を"
    "単独で検索できる1文に書き換えてください。新しい条件を足さないこと。"
)


def followup_prompt(history: list[str], text: str) -> str:
    lines = "\n".join(f"- {h}" for h in history)
    return f"会話履歴:\n{lines}\n最後の発話: {text}\n書き換えた検索クエリ:"


def resolve_followup(history: list[str], text: str, client) -> str:
    """LLM 版の自立化。指示語が無ければ呼ばない（呼び出しを減らす設計）。"""
    if not history or not needs_context(text):
        return text
    return client.complete(FOLLOWUP_SYSTEM, followup_prompt(history, text)).text.strip()


# 直前の発話の主題（履歴側の語）で分岐する。StubClient は「最初に当たったキー」を返す
FOLLOWUP_STUB_RULES: dict[str, str] = {
    "有給休暇": "有給休暇の申請期限は何日前までか",
    "会議室": "会議室の連続利用の上限は何時間か",
    "多要素認証": "多要素認証の登録期限はいつまでか",
}


def make_followup_client():
    """自立化用の StubClient（APIキー不要・決定的）。"""
    from ragkit.llm import StubClient

    return StubClient(rules=FOLLOWUP_STUB_RULES, default="（書き換えられませんでした）")


# ---------------------------------------------------------------------------
# 6. スペル訂正の候補出し
# ---------------------------------------------------------------------------


def suggest_term(term: str, vocab, n: int = 1, cutoff: float = 0.6) -> list[str]:
    """索引の語彙から、綴りの近い語を候補として返す。

    **索引に存在する語には絶対にかけない**こと。正しく打てている語を
    「似ている別の語」に書き換えると、静かに間違った検索になる。
    """
    if term in vocab:
        return []
    return difflib.get_close_matches(term, list(vocab), n=n, cutoff=cutoff)


# ---------------------------------------------------------------------------
# 7. 検索器（どれも search(query, k, filters) を持つ）
# ---------------------------------------------------------------------------


class RewriteRetriever:
    """既存の検索器を包んで、書き換え関数を1つ挟むだけの検索器。"""

    def __init__(self, index, rewrite) -> None:
        self.index = index
        self.rewrite = rewrite
        self.rewrites = 0  # 実際に文字列が変わった回数

    def search(self, query: str, k: int = 10, filters: dict | None = None):
        rewritten = self.rewrite(query)
        if rewritten != query:
            self.rewrites += 1
        return self.index.search(rewritten, k=k, filters=filters)


class MultiQueryRetriever:
    """1つのクエリから複数のクエリを作り、結果を RRF で統合する検索器。

    generate: str -> list[str]（1本しか返さなければ、統合前後で順位は変わらない）
    """

    def __init__(self, index, generate, candidates: int = 20, rrf_k: int = 60) -> None:
        self.index = index
        self.generate = generate
        self.candidates = candidates
        self.rrf_k = rrf_k
        self.searches = 0  # 検索の実行回数（コストの勘定に使う）

    def search(self, query: str, k: int = 10, filters: dict | None = None):
        variants = self.generate(query) or [query]
        lists = []
        for v in variants:
            self.searches += 1
            lists.append(self.index.search(v, k=self.candidates, filters=filters))
        return rrf_fuse(lists, k=k, rrf_k=self.rrf_k)


class HydeRetriever:
    """仮想文書を作ってからクエリに足して検索する検索器。"""

    def __init__(self, index, client, keep_query: bool = True) -> None:
        self.index = index
        self.client = client
        self.keep_query = keep_query
        self.calls = 0

    def search(self, query: str, k: int = 10, filters: dict | None = None):
        self.calls += 1
        doc = hyde_document(query, self.client)
        text = hyde_query(query, doc) if self.keep_query else doc
        return self.index.search(text, k=k, filters=filters)


class TypeRouter:
    """クエリの型ごとに打ち手を割り当てる検索器。

    「型 → 打ち手」の対応表を持つだけの、いちばん軽いルーティング。
    検索するかどうかや、どのツールを呼ぶかまでを動的に決める本格的なルーティングは
    姉妹教材『AIエージェント実践』の領分なので、ここでは踏み込まない。
    """

    def __init__(self, index, candidates: int = 20) -> None:
        self.index = index
        self.candidates = candidates
        self.stats: Counter = Counter()
        self.searches = 0
        self.llm_calls = 0  # この構成は LLM を1回も呼ばない

    def search(self, query: str, k: int = 10, filters: dict | None = None):
        qtype = classify(query)
        self.stats[qtype] += 1
        if qtype == "abbrev":
            self.searches += 1
            return self.index.search(expand_query(query), k=k, filters=filters)
        if qtype == "multi_condition":
            subs = decompose(query)
            lists = []
            for s in subs:
                self.searches += 1
                lists.append(self.index.search(s, k=self.candidates, filters=filters))
            return rrf_fuse(lists, k=k)
        self.searches += 1
        return self.index.search(query, k=k, filters=filters)


# ---------------------------------------------------------------------------
# 8. コストの勘定
# ---------------------------------------------------------------------------


class CountingClient:
    """任意の LLMClient を包んで、呼び出し回数と文字数を数える。

    レイテンシは測らない。StubClient も合成カセットも即答するので、
    ここで測った時間は実運用の待ち時間と何の関係もないため。
    """

    def __init__(self, inner) -> None:
        self.inner = inner
        self.calls = 0
        self.input_chars = 0
        self.output_chars = 0

    def complete(self, system: str, user: str, max_tokens: int = 1024):
        self.calls += 1
        self.input_chars += len(system) + len(user)
        res = self.inner.complete(system, user, max_tokens=max_tokens)
        self.output_chars += len(res.text)
        return res


def call_plan(queries, targets: set[str] | None = None) -> dict[str, int]:
    """「どの型で LLM を呼ぶか」を決めたときの呼び出し回数を数える。

    targets=None なら全クエリで呼ぶ（＝いちばん高い構成）。
    """
    plan: Counter = Counter()
    for q in queries:
        qtype = classify(q.text)
        if targets is None or qtype in targets:
            plan[qtype] += 1
    plan["ALL"] = sum(v for key, v in plan.items() if key != "ALL")
    return dict(plan)


# ---------------------------------------------------------------------------
# 9. 比較用：索引側の同義語展開（セッション5の実装の再掲）
# ---------------------------------------------------------------------------

# 正式名称（コーパスに実在する語） -> 別称（クエリにだけ現れる語）
INDEX_SYNONYMS: dict[str, list[str]] = {
    "有給休暇": ["年休", "有休"],
    "時間外労働": ["残業"],
    "育児休業": ["育休"],
    "通勤交通費": ["定期代"],
    "貸与PC": ["パソコン"],
    "貸与スマートフォン": ["スマホ", "携帯"],
    "パスワード": ["パス", "PW"],
    "多要素認証": ["MFA", "二要素認証", "2段階認証"],
    "入退館カード": ["社員証"],
    "座席": ["フリーアドレス"],
    "標的型メール": ["フィッシング", "不審メール"],
    "外部サービス": ["SaaS", "クラウドサービス"],
    "セキュリティ事故": ["インシデント"],
}


class IndexSideSynonymIndex(LexicalIndex):
    """索引を作るときだけ別称を足す BM25（セッション5で作ったものと同じ実装）。

    この章では「索引側とクエリ側のどちらで展開するか」を1つのスクリプトで
    並べて比べたいので、比較のためだけにここへ写している。設計の説明は S05 を参照。
    """

    def __init__(self, synonyms: dict[str, list[str]] | None = None, k1: float = 1.2,
                 b: float = 0.75, mode: str = "morph") -> None:
        super().__init__(k1=k1, b=b, mode=mode)
        self.synonyms = INDEX_SYNONYMS if synonyms is None else synonyms
        self.expanded_chunks = 0

    def expand(self, text: str) -> str:
        extra = [alias for term, aliases in self.synonyms.items()
                 if term in text for alias in aliases]
        return text + "\n" + " ".join(extra) if extra else text

    def build(self, chunks: list[Chunk]) -> "IndexSideSynonymIndex":
        self.expanded_chunks = 0
        expanded: list[Chunk] = []
        for c in chunks:
            text = self.expand(c.text)
            if text != c.text:
                self.expanded_chunks += 1
            expanded.append(replace(c, text=text))
        super().build(expanded)
        # 索引は展開後の語で作り、返す本文は元のチャンクに戻す
        for c in chunks:
            self.chunks[c.chunk_id] = c
        return self


# ---------------------------------------------------------------------------
# 10. 失敗の分解（横断復習01の道具。打ち手を選ぶ根拠にする）
# ---------------------------------------------------------------------------


def failure_split(retriever, queries, qrels, k: int = 10,
                  pool: int = 100) -> dict[str, dict[str, float]]:
    """「1 - Recall@k」を到達不足と順位不足に分けて、クエリ型別に集計する。

    到達不足 = 1 - Recall@pool   候補にすら入っていない → 語彙・入力側・索引側の問題
    順位不足 = Recall@pool - Recall@k  候補には居る → 並べ替え（リランク）の問題
    """
    from ragkit.eval import recall_at_k

    acc: dict[str, list[tuple[float, float]]] = {}
    for q in queries:
        qr = qrels.get(q.query_id, {})
        if not any(g >= 1 for g in qr.values()):
            continue
        r_k = recall_at_k(retriever.search(q.text, k=k), qr, k)
        r_pool = recall_at_k(retriever.search(q.text, k=pool), qr, pool)
        acc.setdefault(q.type, []).append((r_k, r_pool))
        acc.setdefault("ALL", []).append((r_k, r_pool))

    out: dict[str, dict[str, float]] = {}
    for qtype, rows in acc.items():
        n = len(rows)
        recall = sum(a for a, _ in rows) / n
        reach = sum(b for _, b in rows) / n
        out[qtype] = {"n": float(n), "recall": recall, "reach": reach,
                      "rank_loss": reach - recall, "reach_loss": 1.0 - reach}
    return out
