#!/usr/bin/env python3
"""セッション19: 症状から原因へたどる切り分けツール。

    docker compose exec app python src/session19/diagnose.py
    docker compose exec app python src/session19/diagnose.py S6-REFUSE-WITH-HITS

セッション12の `src/session12/triage.py` は「1件の要求を層ごとに分解する」道具でした。
本章はそれを**症状の側から**一般化します。違いは3つです。

    1. 症状コードを入れると**確認順序**が出る（どこから見るかを迷わせない）
    2. 説明責任ログ（セッション14）の1行から**候補原因を絞る**
    3. ログだけで決まらないものは ablation（片方を外して同じか見る）で確定させる

**同じ症状には複数の原因があります。** このツールが候補を1つに決め打ちしないのは、
現場でいちばん高くつく間違いが「最初に思いついた原因に決めてしまうこと」だからです。
原因を1つに絞るのは、ログの欄か実験のどちらかで**除外できたとき**だけにします。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

sys.path.insert(0, "/workspace")

from bedrock_mock import generation  # noqa: E402

# ---------------------------------------------------------------------------
# 原因の辞書（コードで呼べる名前を付けておく）
# ---------------------------------------------------------------------------

# 原因に短いコードを与えるのは、監視・チケット・事後報告で**同じ語**を使うためです。
# 「なんか調子が悪い」を毎回自然文で書くと、件数を数えられず傾向も見えません。
CAUSES: dict[str, str] = {
    "C-NONE": "異常なし（根拠つきで答えられている）",
    "C-TRUNCATION": "出力が max_tokens で打ち切られた",
    "C-CONTEXT-OVERFLOW": "入力がコンテキスト長を超えた",
    "C-STREAM-CUT": "ストリーミングが完了イベントの前に切れた",
    "C-BAD-ARGUMENT": "リクエストの引数・スキーマが誤っている",
    "C-UNSUPPORTED-MODEL": "そのモデルが対応していない機能を呼んだ",
    "C-AUTHZ": "認可（IAM・モデルアクセス）で拒否された",
    "C-MODEL-UNAVAILABLE": "そのリージョンでモデルを呼べない",
    "C-BREAKER-OPEN": "サーキットブレーカーが開いていて呼んでいない",
    "C-CONFIG-DRIFT": "設定が差し替わって別のモデルを呼んでいる",
    "C-QUOTA": "割当（クォータ）が要求に足りない",
    "C-RETRY-STORM": "リトライの二重掛けで要求数が掛け算になっている",
    "C-EXTERNAL-LATENCY": "遅延が基盤モデルの外（検索・ツール・網）で起きている",
    "C-EMPTY-RETRIEVAL": "検索が0件（メタデータフィルタ・分類・索引）",
    "C-INDEX-STALE": "索引が古い（同期漏れ・埋め込みの不一致）",
    "C-NO-GROUNDING-CONTRACT": "出力契約（出典行）を落とした版で動いている",
    "C-KEYWORD-MISMATCH": "質問と資料の語が噛み合っていない",
    "C-CHUNK-BOUNDARY": "答えがチャンク境界で分断されている",
    "C-PROMPT-REGRESSION": "プロンプトの版が承認版と違う",
    "C-GUARDRAIL-BLOCK": "入口のガードレールが遮断した",
}


@dataclass(frozen=True)
class Candidate:
    """1つの候補原因。**「見る欄」と「決め手」が無い候補は書かない。**

    打ち手だけを並べた手順書は現場で役に立ちません。「まず maxTokens を上げる」で
    直ってしまうと、直した気になったまま本当の原因（入力の膨張）が残ります。
    """

    cause: str  # CAUSES のキー
    field: str  # 一次情報の「どの欄」を見るか
    ruling: str  # これが原因だと決まる／除外できる条件（決定的な性質だけ）
    fix: str  # 決まったときの打ち手


@dataclass(frozen=True)
class Symptom:
    code: str
    reported: str  # 利用者や監視から来る言葉（技術用語に翻訳する前の姿）
    source: str  # 一次情報の出どころ
    candidates: tuple[Candidate, ...]


# ---------------------------------------------------------------------------
# 症状カタログ（本章の中心。**候補は必ず2つ以上**書く）
# ---------------------------------------------------------------------------

SYMPTOMS: dict[str, Symptom] = {
    "S1-TRUNCATED": Symptom(
        code="S1-TRUNCATED",
        reported="回答が途中で切れる／JSON がパースできない",
        source="説明責任ログの stopReason・inputTokens・outputTokens",
        candidates=(
            Candidate(
                "C-TRUNCATION",
                "stopReason",
                "max_tokens なら確定。end_turn なら除外できる",
                "maxTokens を上げる／資料を要約して渡す／引用件数を減らす",
            ),
            Candidate(
                "C-CONTEXT-OVERFLOW",
                "呼ぶ前の見積りトークンとモデルの context_window",
                "見積りが context_window を超えていれば確定（この場合 400 が返り stopReason は残らない）",
                "動的チャンク（入る分だけ詰める）／段階的に要約／質問を分割して複数回答",
            ),
            Candidate(
                "C-STREAM-CUT",
                "ConverseStream の messageStop イベントの有無",
                "contentBlockDelta は届いたのに messageStop が無ければ確定",
                "read_timeout を延ばす／途中結果を採用しない／相関 ID で同一要求を追う",
            ),
        ),
    ),
    "S2-BAD-REQUEST": Symptom(
        code="S2-BAD-REQUEST",
        reported="呼び出しが即座に失敗する（待っても直らない）",
        source="例外クラス名・HTTP ステータス・operation_name・エラーメッセージ本文",
        candidates=(
            Candidate(
                "C-BAD-ARGUMENT",
                "例外クラス名（ValidationException）とメッセージ本文",
                "メッセージが引数名・スキーマに言及していれば確定",
                "リクエストを組み立てる側を直す。リトライしない",
            ),
            Candidate(
                "C-UNSUPPORTED-MODEL",
                "メッセージ本文とモデル ID",
                "別のモデル ID で同じ呼び出しが通れば確定",
                "モデルとカタログの対応表を見直す（埋め込みモデルに Converse は無い）",
            ),
            Candidate(
                "C-AUTHZ",
                "例外クラス名（AccessDeniedException）と呼び出した principal",
                "同じ引数で別のロールから通れば確定",
                "IAM ポリシーとモデルアクセスの有効化を直す。リトライしない",
            ),
        ),
    ),
    "S3-MODEL-DOWN": Symptom(
        code="S3-MODEL-DOWN",
        reported="特定のモデルだけ落ちる／勝手に別モデルの回答になる",
        source="説明責任ログの attempts と modelId、設定の版",
        candidates=(
            Candidate(
                "C-MODEL-UNAVAILABLE",
                "attempts の outcome（ServiceUnavailableException）",
                "attempts の1件目が 503 で2件目が ok なら確定",
                "フェイルオーバー先を確認する／推論プロファイル経由に切り替える",
            ),
            Candidate(
                "C-BREAKER-OPEN",
                "attempts の outcome（skipped_open）",
                "skipped_open が並んでいれば確定（そのモデルへ要求は出ていない）",
                "クールダウンの長さを見直す／半開での試行が通るか確認する",
            ),
            Candidate(
                "C-CONFIG-DRIFT",
                "modelId と設定（SSM／AppConfig）の版",
                "attempts が1件だけで modelId が想定と違えば確定",
                "設定の配布経路を1つに絞る／検証を通らない設定を配らせない",
            ),
        ),
    ),
    "S4-THROTTLED": Symptom(
        code="S4-THROTTLED",
        reported="429 が増えた／急に遅くなった",
        source="スロットリング回数、送信した要求数、metrics.latencyMs とクライアント実測の差",
        candidates=(
            Candidate(
                "C-QUOTA",
                "スロットリング回数と論理呼び出し数の比",
                "1呼び出しあたりの 429 が1回未満でも増え続けていれば確定",
                "同時実行を絞る／キューで平準化する／割当の引き上げを申請する",
            ),
            Candidate(
                "C-RETRY-STORM",
                "送信した要求数 ÷ 論理呼び出し数",
                "比が max_attempts + 1 を超えていれば確定（リトライが二重）",
                "リトライ層を1つに決める（SDK か自作のどちらか）",
            ),
            Candidate(
                "C-EXTERNAL-LATENCY",
                "metrics.latencyMs とクライアントで測った時間の差",
                "サーバーが返す latencyMs が変わらないのに実測だけ伸びていれば確定",
                "検索・ツール・網のどこで待っているかを区間ごとに測る",
            ),
        ),
    ),
    "S5-NO-CITATION": Symptom(
        code="S5-NO-CITATION",
        reported="引用が付かない／根拠のない数字を答える",
        source="説明責任ログの citationCount・modelId・citations[].revision・promptChecksum",
        candidates=(
            Candidate(
                "C-EMPTY-RETRIEVAL",
                "citationCount と modelId",
                "citationCount が0で modelId が null なら確定（呼ぶ前に止まっている）",
                "メタデータフィルタと分類の対応を見直す／絞り込みを外して再検索する",
            ),
            Candidate(
                "C-INDEX-STALE",
                "citations[].revision とリネージ台帳の最新版",
                "引いた版が台帳の最新版より古ければ確定",
                "取り込みを再実行する／prune で消えた行を戻す／埋め込みモデルの版をそろえる",
            ),
            Candidate(
                "C-NO-GROUNDING-CONTRACT",
                "promptVersion と promptChecksum",
                "承認版のハッシュと違えば確定",
                "承認済みの版へ戻す／回帰テストの必須フレーズを増やす",
            ),
        ),
    ),
    "S6-REFUSE-WITH-HITS": Symptom(
        code="S6-REFUSE-WITH-HITS",
        reported="資料は出ているのに「資料の範囲外」と断られる",
        source="説明責任ログの outcome・citationCount・stopReason・promptChecksum ＋ 共通語の数",
        candidates=(
            Candidate(
                "C-TRUNCATION",
                "stopReason",
                "max_tokens なら確定（根拠の印ごと切れている）",
                "maxTokens を上げる／資料を要約して渡す",
            ),
            Candidate(
                "C-PROMPT-REGRESSION",
                "promptChecksum",
                "承認版のハッシュと違えば確定。一致すれば**除外できる**",
                "承認済みの版へ戻す",
            ),
            Candidate(
                "C-KEYWORD-MISMATCH",
                "質問の語と引用本文の語で共通するものの数",
                "共通語が0語なら確定（検索は当たっていても答えは作れない）",
                "質問を書き換える／クエリ書き換えの辞書を足す／同義語をメタデータに持つ",
            ),
            Candidate(
                "C-CHUNK-BOUNDARY",
                "引用本文に答えの文が含まれているか",
                "共通語があるのに答えの文が引用に無ければ確定",
                "チャンクを重ねて分割する／親子チャンクにする／上位k件を増やす",
            ),
        ),
    ),
}

# 例外コードだけで残る候補。**コードは症状であって原因ではありません。**
ERROR_CANDIDATES: dict[str, tuple[str, ...]] = {
    "ValidationException": ("C-BAD-ARGUMENT", "C-UNSUPPORTED-MODEL", "C-CONTEXT-OVERFLOW"),
    "AccessDeniedException": ("C-AUTHZ",),
    "ResourceNotFoundException": ("C-CONFIG-DRIFT",),
    "ServiceUnavailableException": ("C-MODEL-UNAVAILABLE", "C-BREAKER-OPEN"),
    "ThrottlingException": ("C-QUOTA", "C-RETRY-STORM"),
}

# メッセージ本文に現れたらモデル側の非対応だと決まる語（候補を1つに絞る決め手）
UNSUPPORTED_HINTS = ("サポートしていません", "model identifier is invalid")


# ---------------------------------------------------------------------------
# ログ1行から候補を絞る
# ---------------------------------------------------------------------------


def narrow(entry: dict) -> list[str]:
    """説明責任ログ1行だけを見て、残る候補原因を返す。

    **ログだけで1つに決まる症状と、決まらない症状があります。** 決まらないときに
    1つ返す実装にすると、読み手はそれを答えだと思い込みます。ここでは正直に
    複数返し、次に何を確かめれば消えるかは `SYMPTOMS` の `ruling` に書いてあります。
    """
    outcome = entry.get("outcome")
    if outcome == "blocked":
        return ["C-GUARDRAIL-BLOCK"]
    if outcome == "no_citation":
        return ["C-EMPTY-RETRIEVAL", "C-INDEX-STALE"]
    if outcome == "exhausted":
        # 同じ結末でも、打ち切りかどうかは stopReason だけで分かれる
        if entry.get("stopReason") == "max_tokens":
            return ["C-TRUNCATION"]
        return ["C-KEYWORD-MISMATCH", "C-CHUNK-BOUNDARY", "C-PROMPT-REGRESSION"]
    if outcome == "answered":
        return ["C-NONE"]
    return []


def from_error(code: str, message: str = "") -> list[str]:
    """例外コード（＋メッセージ）から候補を絞る。

    コードだけでは絞りきれないことを見せるのが狙いです。`ValidationException` は
    引数の誤りでもモデルの非対応でも入力超過でも返ります。
    """
    if any(hint in message for hint in UNSUPPORTED_HINTS):
        return ["C-UNSUPPORTED-MODEL"]
    return list(ERROR_CANDIDATES.get(code, []))


def confirm(
    candidates: list[str], *, checksum_matches: bool, shared_words_count: int
) -> str:
    """候補を1つに確定させる。**安い検査から順に当てる。**

    ハッシュの比較は計算だけで済み、共通語の数え上げは検索を1回やり直せば済みます。
    どちらもモデルを呼びません。**課金の要る実験は最後**に置きます。
    """
    if "C-PROMPT-REGRESSION" in candidates and not checksum_matches:
        return "C-PROMPT-REGRESSION"
    remaining = [c for c in candidates if c != "C-PROMPT-REGRESSION"]
    if "C-KEYWORD-MISMATCH" in remaining and shared_words_count == 0:
        return "C-KEYWORD-MISMATCH"
    remaining = [c for c in remaining if c != "C-KEYWORD-MISMATCH"]
    return remaining[0] if remaining else "C-NONE"


# ---------------------------------------------------------------------------
# ablation（片方を外して同じ結果か見る）
# ---------------------------------------------------------------------------


def keywords(text: str) -> set[str]:
    """モックの語分割を覗く（教材用）。

    実 AWS の Knowledge Bases や基盤モデルの内部はこう見えません。ここでは
    「なぜ噛み合わなかったか」を数字で示すために、モックの内部関数を借ります。
    実務では、この位置に「検索クエリのログ」と「引用本文」を並べる作業が来ます。
    """
    return generation._keywords(text)  # noqa: SLF001


def shared_words(question: str, sources: list[str]) -> list[str]:
    """質問の語のうち、引用本文にも現れるもの。**0語なら根拠づけは成立しません。**"""
    source_words: set[str] = set()
    for text in sources:
        source_words |= keywords(text)
    return sorted(keywords(question) & source_words)


# ---------------------------------------------------------------------------
# 手順書の出力
# ---------------------------------------------------------------------------


def index_lines() -> list[str]:
    lines = ["=== 症状カタログ（症状コード -> 候補原因の数） ==="]
    for symptom in SYMPTOMS.values():
        lines.append(
            f"  {symptom.code} 「{symptom.reported}」候補{len(symptom.candidates)}件"
        )
    lines.append("使い方: python src/session19/diagnose.py S6-REFUSE-WITH-HITS")
    return lines


def playbook(code: str) -> list[str]:
    """症状コードから確認順序を組み立てる。"""
    symptom = SYMPTOMS[code]
    lines = [f"=== {symptom.code}: {symptom.reported} ===", f"  一次情報: {symptom.source}"]
    for order, candidate in enumerate(symptom.candidates, start=1):
        lines.append(f"  {order}. {candidate.cause} {CAUSES[candidate.cause]}")
        lines.append(f"     見る欄: {candidate.field}")
        lines.append(f"     決め手: {candidate.ruling}")
        lines.append(f"     打ち手: {candidate.fix}")
    lines.append("  候補が残ったまま打ち手を当てないこと（直ったのか隠れたのか分かりません）")
    return lines


def main() -> None:
    if len(sys.argv) > 1:
        code = sys.argv[1]
        if code not in SYMPTOMS:
            print(f"未知の症状コードです: {code}")
            print("\n".join(index_lines()))
            raise SystemExit(2)
        print("\n".join(playbook(code)))
        return
    print("\n".join(index_lines()))


if __name__ == "__main__":
    main()
