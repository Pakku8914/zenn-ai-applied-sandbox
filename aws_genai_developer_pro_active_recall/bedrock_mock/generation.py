"""決定的な擬似生成エンジン。

このモックは実際の基盤モデルを動かしません。代わりに
「同じ入力なら必ず同じ出力を返す」ルールベースの生成器を持ちます。
教材の「期待される出力」を固定でき、課金もネットワークも要らないためです。

実装しているふるまい（いずれも教材の演習と対応しています）:

| ふるまい | 何の学習に使うか |
| :--- | :--- |
| `<context>` があれば必ずその文だけを根拠に答える | RAG のグラウンディング |
| `<context>` が無い事実質問には自信満々に作り話をする | ハルシネーション検出・評価 |
| `max_tokens` を超えたら途中で切って `max_tokens` を返す | コンテキスト溢れのトラブルシュート |
| `temperature=0` は完全に決定的、`>0` は入力に紐づく別バリアント | 再現性・A/B テスト |
| ツール定義があり質問がツールに合致すれば `tool_use` を返す | エージェント・関数呼び出し |
| `cachePoint` があれば読み書きトークンを別集計する | プロンプトキャッシュのコスト効果 |
"""

from __future__ import annotations

import hashlib
import math
import re
import struct
import unicodedata

# ---------------------------------------------------------------------------
# トークン計算
# ---------------------------------------------------------------------------

_ASCII_CHARS_PER_TOKEN = 4


def count_tokens(text: str) -> int:
    """おおよそのトークン数を決定的に数える。

    実際の Bedrock は各モデル固有のトークナイザを使いますが、モックでは
    「ASCII は4文字で1トークン、日本語などの非 ASCII は1文字1トークン」
    という単純な規則に固定します。日本語が英語よりトークンを食うという
    実務上の重要な非対称は、この近似でも保たれます。
    """
    if not text:
        return 0
    ascii_run = 0
    tokens = 0
    for ch in text:
        if ord(ch) < 128:
            ascii_run += 1
        else:
            tokens += 1
    tokens += math.ceil(ascii_run / _ASCII_CHARS_PER_TOKEN)
    return tokens


def truncate_to_tokens(text: str, max_tokens: int) -> tuple[str, bool]:
    """トークン上限に収まるよう切り詰める。(切り詰めた文字列, 切ったか) を返す。"""
    if max_tokens <= 0:
        return "", True
    if count_tokens(text) <= max_tokens:
        return text, False
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if count_tokens(text[:mid]) <= max_tokens:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo], True


# ---------------------------------------------------------------------------
# 埋め込み
# ---------------------------------------------------------------------------


def embed(text: str, dimensions: int = 1024, normalize: bool = True) -> list[float]:
    """文字 n-gram のハッシュを使った決定的な埋め込みを返す。

    実 Titan Embeddings のような意味理解はありません。文字の重なりに反応する
    「語彙的な類似度」を返すだけです。それでもベクトル検索の仕組み・次元数・
    正規化・コサイン類似度の演習は成立します（RAG の品質そのものを論じる章では
    この限界を明示しています）。
    """
    vec = [0.0] * dimensions
    normalized = unicodedata.normalize("NFKC", text).lower()
    grams = [normalized[i : i + 3] for i in range(max(len(normalized) - 2, 1))]
    for gram in grams:
        digest = hashlib.sha256(gram.encode("utf-8")).digest()
        # 8バイトずつ使って「どの次元に」「どちら向きに」足すかを決める
        index = struct.unpack(">I", digest[0:4])[0] % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        weight = 1.0 + (digest[5] / 255.0)
        vec[index] += sign * weight
    if normalize:
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        vec = [v / norm for v in vec]
    return [round(v, 6) for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return round(dot / (na * nb), 6)


# ---------------------------------------------------------------------------
# 入力の解析
# ---------------------------------------------------------------------------

_CONTEXT_PATTERN = re.compile(
    r"<(context|documents|資料)>(?P<body>.*?)</\1>", re.DOTALL | re.IGNORECASE
)
_SENTENCE_SPLIT = re.compile(r"(?<=[。．.!?！？\n])")
_STOPWORDS = {
    "の", "は", "を", "に", "が", "で", "と", "も", "から", "まで", "です", "ます",
    "ですか", "でしょうか", "教えて", "ください", "について", "とは", "何", "なに",
    "the", "a", "an", "of", "is", "are", "what", "how", "please", "tell", "me",
}


def extract_context(prompt: str) -> list[str]:
    """プロンプト内の <context> ブロックを文のリストにして返す。"""
    blocks = [m.group("body") for m in _CONTEXT_PATTERN.finditer(prompt)]
    sentences: list[str] = []
    for block in blocks:
        for raw in _SENTENCE_SPLIT.split(block):
            s = raw.strip()
            if len(s) >= 6:
                sentences.append(s)
    return sentences


def _keywords(text: str) -> set[str]:
    cleaned = _CONTEXT_PATTERN.sub(" ", text)
    cleaned = unicodedata.normalize("NFKC", cleaned).lower()
    tokens = re.findall(r"[0-9a-z]+|[ぁ-んァ-ヴー]{2,}|[一-龥]{1,}", cleaned)
    return {t for t in tokens if t not in _STOPWORDS and len(t) >= 2}


def _overlap_score(question: str, sentence: str) -> int:
    qk = _keywords(question)
    sk = _keywords(sentence)
    return len(qk & sk)


# ---------------------------------------------------------------------------
# 生成
# ---------------------------------------------------------------------------

_JSON_HINT = re.compile(r"\bjson\b|スキーマ|schema", re.IGNORECASE)
_SUMMARY_HINT = re.compile(r"要約|summar", re.IGNORECASE)
_TRANSLATE_HINT = re.compile(r"翻訳|translat", re.IGNORECASE)
_CLASSIFY_HINT = re.compile(r"分類|classif|カテゴリ|ラベル", re.IGNORECASE)

# 出典が無いときに返す「もっともらしい作り話」のテンプレート。
# 数値・日付をあえて具体的に入れてあるので、事実確認の演習で必ず引っかかる。
_HALLUCINATION_TEMPLATES = (
    "はい、{topic}については2023年4月の仕様変更で上限が5,000件に引き上げられました。"
    "移行手順は公式ブログの第3節にまとめられています。",
    "{topic}の既定値は 128 です。運用チームの標準設定では 256 に変更するのが一般的です。",
    "{topic}は3つのプランで提供されており、Standard プランの月額は 49 ドルです。",
)


def _seed(*parts: str) -> int:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()
    return struct.unpack(">I", digest[:4])[0]


_HIRAGANA_ONLY = re.compile(r"^[ぁ-ん]+$")


def _topic(question: str) -> str:
    """作り話のテンプレートに差し込む「主題語」を決定的に選ぶ。

    ひらがなだけの語（「められますか」のような語尾の連なり）を主題にすると
    日本語として崩れてしまうため、漢字・カタカナ・英数字を含む語を優先する。
    """
    keywords = _keywords(question)
    candidates = [k for k in keywords if not _HIRAGANA_ONLY.match(k)] or list(keywords)
    if not candidates:
        return "この項目"
    return sorted(candidates, key=lambda k: (-len(k), k))[0]


def generate_text(
    *,
    model_id: str,
    prompt: str,
    system: str = "",
    temperature: float = 0.0,
    max_tokens: int = 512,
    hallucinate: bool = True,
) -> tuple[str, str]:
    """(生成テキスト, stopReason) を返す。stopReason は end_turn か max_tokens。"""
    context = extract_context(prompt)
    seed = _seed(model_id, system, prompt, f"{temperature:.2f}")

    if context:
        ranked = sorted(
            context, key=lambda s: (-_overlap_score(prompt, s), context.index(s))
        )
        best = [s for s in ranked if _overlap_score(prompt, s) > 0][:2]
        if best:
            body = "".join(best)
            text = f"提供された資料によると、{body}\n\n（根拠: 検索で取得した資料内の記述）"
        else:
            text = (
                "提供された資料には、その質問に答えられる記述が見つかりませんでした。"
                "資料の範囲外の内容のため、推測での回答は行いません。"
            )
    elif _JSON_HINT.search(prompt) or _JSON_HINT.search(system):
        # 構造化出力の演習用。必ずパース可能な JSON だけを返す
        text = (
            '{"summary": "入力の要点を1文で表した結果です。", '
            f'"sentiment": "{["positive", "neutral", "negative"][seed % 3]}", '
            '"keywords": ["生成AI", "Amazon Bedrock", "運用"]}'
        )
    elif _SUMMARY_HINT.search(prompt):
        text = (
            "要約: 入力されたテキストの主張は3点に整理できます。"
            "1点目は目的、2点目は制約、3点目は次の行動です。"
        )
    elif _TRANSLATE_HINT.search(prompt):
        text = "Translation: This is the deterministic translation produced by the mock endpoint."
    elif _CLASSIFY_HINT.search(prompt):
        text = ["請求に関する問い合わせ", "技術的な不具合", "解約の相談"][seed % 3]
    elif hallucinate:
        template = _HALLUCINATION_TEMPLATES[seed % len(_HALLUCINATION_TEMPLATES)]
        text = template.format(topic=_topic(prompt))
    else:
        text = (
            "根拠となる資料が与えられていないため、確認できる情報の範囲では回答できません。"
        )

    text, truncated = truncate_to_tokens(text, max_tokens)
    return text, ("max_tokens" if truncated else "end_turn")


def choose_tool(
    *, tools: list[dict], prompt: str, already_called: set[str]
) -> dict | None:
    """ツール定義と質問から、呼ぶべきツールを決定的に選ぶ。

    同じツールを2回続けて選ばない（`already_called`）ため、
    ReAct ループが必ず有限回で終わります。
    """
    scored: list[tuple[int, dict]] = []
    for tool in tools:
        spec = tool.get("toolSpec", tool)
        name = spec.get("name", "")
        if name in already_called:
            continue
        haystack = f"{name} {spec.get('description', '')}"
        score = len(_keywords(haystack) & _keywords(prompt))
        # ツール名がそのまま出てきたら強く反応させる
        if name and name.lower().replace("_", "") in prompt.lower().replace("_", ""):
            score += 5
        if score > 0:
            scored.append((score, spec))
    if not scored:
        return None
    scored.sort(key=lambda pair: (-pair[0], pair[1].get("name", "")))
    spec = scored[0][1]
    schema = (spec.get("inputSchema") or {}).get("json") or {}
    properties: dict = schema.get("properties") or {}
    payload: dict[str, object] = {}
    for key, prop in properties.items():
        kind = prop.get("type", "string")
        if kind == "string":
            payload[key] = _topic(prompt)
        elif kind in ("number", "integer"):
            payload[key] = 1
        elif kind == "boolean":
            payload[key] = True
        else:
            payload[key] = None
    return {"name": spec.get("name", "unknown"), "input": payload}
