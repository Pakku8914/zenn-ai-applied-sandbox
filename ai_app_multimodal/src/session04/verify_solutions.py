"""セッション4の解答コードの動作確認。各解答の main() の出力が、解答章に載せた「期待される出力」と一致するかを見る。

    docker compose exec api python src/session04/verify_solutions.py
"""

from __future__ import annotations

import contextlib
import io
import logging

from kondate.verifykit import check, eq, finish
from src.session04.solutions import q1_request, q2_revalidate, q3_review, q4_retry, q5_suggest, q6_lenient

logging.getLogger("src.session04").setLevel(logging.ERROR)

EXPECTED = {
    "q1": """\
必須の項目: name, amount, unit, confidence
additionalProperties: False
confidence の範囲（変換前）: minimum=0・maximum=1
confidence の範囲（変換後）: 外された
キャベツ 0.5玉（0.94）
鶏むね肉 1枚（0.88）
卵 4個（0.97）
にんじん 1本（0.81）
牛乳 1本（0.9）
input_tokens=1668
""",
    "q2": """\
正常: OK（食材 1 件）
confidence が 1.2: NG ingredients.0.confidence: less_than_equal（値の誤り：構造化出力では防げない）
amount が 0: NG ingredients.0.amount: greater_than（値の誤り：構造化出力では防げない）
name が空: NG ingredients.0.name: string_too_short（値の誤り：構造化出力では防げない）
unit が無い: NG ingredients.0.unit: missing（形の誤り：構造化出力で防げる）
confidence が文字列: NG ingredients.0.confidence: float_parsing（形の誤り：構造化出力で防げる）
途中で切れた JSON: NG (全体): json_invalid（形の誤り：構造化出力でも max_tokens で切れると起きる）
""",
    "q3": """\
しきい値 0.6: 要確認 3 件
  鶏ムネ肉: 辞書にない
  にんじん: 確からしさが低い（0.42）
  ズッキーニ: 確からしさが低い（0.35）・辞書にない
しきい値 0.85: 要確認 5 件
  鶏ムネ肉: 辞書にない
  にんじん: 確からしさが低い（0.42）
  ズッキーニ: 確からしさが低い（0.35）・辞書にない
  卵: 確からしさが低い（0.6）
  牛乳: 確からしさが低い（0.81）
""",
    "q4": """\
A 正常な JSON → 200（LLM を呼んだ回数 1）
B 範囲外の confidence → 正常 → 200（LLM を呼んだ回数 2）
C 範囲外の confidence が2回続く → 502 invalid_output（LLM を呼んだ回数 2）
D max_tokens で切れた JSON → 502 invalid_output（LLM を呼んだ回数 1）
E 上流が 529 を返し続ける → 503 upstream_unavailable（アプリの呼び出し 1・mockllm が受けた回数 3）
""",
    "q5": """\
写真の読み取り結果から:
  渡す食材: キャベツ、鶏むね肉、卵、にんじん、牛乳（除いた食材: なし）
  R064 にんじんしりしり（5分）
  R067 コールスロー（5分）
  R001 鶏むね肉とキャベツの塩炒め（15分）
  R025 鶏むね肉とブロッコリーのクリーム煮（20分）
  R095 あさりのクラムチャウダー（20分）
にんじんが要確認の応答から:
  渡す食材: キャベツ、鶏むね肉、卵、牛乳（除いた食材: にんじん）
  R001 鶏むね肉とキャベツの塩炒め（15分）
  R025 鶏むね肉とブロッコリーのクリーム煮（20分）
  R064 にんじんしりしり（5分）
  R067 コールスロー（5分）
  R046 トマトと卵の炒め物（10分）
""",
    "q6": """\
2件が壊れている: 使える 3 件（キャベツ、にんじん、牛乳）／要確認に回した 2 件（鶏むね肉、卵）
3件が壊れている: 502（使える項目が 2/5 件で、半分に届かない）
JSON ではない: 502（JSON として読めない）
""",
}

SOLUTIONS = {"q1": q1_request, "q2": q2_revalidate, "q3": q3_review, "q4": q4_retry, "q5": q5_suggest, "q6": q6_lenient}
TITLES = {
    "q1": "問題1 自分のモデルから作ったスキーマで fridge.jpg を送れる",
    "q2": "問題2 形の誤りと値の誤りを再検証で仕分けられる",
    "q3": "問題3 しきい値と食材辞書で要確認を振り分けられる",
    "q4": "問題4 失敗の種類ごとに再試行・502・503 を選び分ける",
    "q5": "問題5 要確認を除いた食材を search_recipes につなげる",
    "q6": "問題6 壊れた項目だけを要確認に回し、使える項目が半分に届かなければ全体を失敗にする",
}


def run(key: str) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        SOLUTIONS[key].main()
    return buf.getvalue()


for n, key in enumerate(SOLUTIONS, start=1):
    @check(f"V{n} {TITLES[key]}")
    def _(key: str = key) -> str:
        eq(run(key), EXPECTED[key], f"{key} の出力")
        return f"{len(EXPECTED[key].splitlines())} 行が一致"


finish("session04 solutions")
