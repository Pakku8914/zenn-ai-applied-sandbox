"""復習4（セッション2〜14の横断復習）の解答コードの動作確認。各解答の main() の出力が、解答章に載せた
「期待される出力」と一致するかを見る。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/review04

問題1・5は mockllm に投げる（課金なし）。ほかは FakeProvider 相当の差し替えか計算だけで動く。
"""

from __future__ import annotations

import contextlib
import io
import logging

from kondate.verifykit import check, eq, finish
from src.review04.solutions import (
    q1_same_photo, q2_monthly_cost, q3_log_lines, q4_eval_cache, q5_delete_all, q6_busy_turns, q7_change_impact,
)

logging.getLogger("pypdf").setLevel(logging.ERROR)

EXPECTED = {
    "q1": """\
t+0分 u001 → miss・usage 1668/194・送った画像 EXIF なし・預けた原本 GPS あり・LLM 累計 1 回
t+10分 u001 → hit・usage 0/0・送った画像 送っていない・預けた原本 GPS あり・LLM 累計 1 回
t+10分 u002 → miss・usage 1668/194・送った画像 EXIF なし・預けた原本 GPS あり・LLM 累計 2 回
t+24時間 u001 → miss・usage 1668/194・送った画像 EXIF なし・預けた原本 GPS あり・LLM 累計 3 回
u001 の原本：預けた 3 件・取り出せる 2 件 → 掃除で 1 件を削除
GET /api/usage（u001） → llm 3336/388・応答キャッシュ 命中 1／外れ 2
GET /api/usage（u002） → llm 1668/194・応答キャッシュ 命中 0／外れ 1
応答キャッシュの件数：2
""",
    "q2": """\
1回あたり（入力/出力）：写真 4000×3000 そのまま 4842/194・1568×1176 に縮めて 2410/194・質問 120ページ全部 192088/38・[29] だけ 1688/38
[29] のプロンプトキャッシュ（接頭辞 1676）：作成 2107・読み出し 179.6（P_in 換算）
(A) 縮めない写真＋120ページ全部：入力 605,316,000・出力 1,278,000 → 611.71 USD/月（仮の値での計算例）
(B) 縮めた写真＋[29] だけ：入力 19,524,000・出力 1,278,000 → 25.91 USD/月（仮の値での計算例）
(C) (B)＋プロンプトキャッシュ：入力 16,444,350・出力 1,278,000 → 22.83 USD/月（仮の値での計算例）
(D) (C)＋応答キャッシュ（命中率 20%）：入力 13,155,480・出力 1,022,400 → 18.27 USD/月（仮の値での計算例）
""",
    "q3": """\
1. INFO app.uploads upload_saved user_id=u001 upload_id=up_01M4RX5Q8J3T9W2B7KDN6CFGHA kind=image bytes=89080 sha12=9f2c4e1a7b30 → 漏れなし
2. INFO app.receipts receipt_imported user_id=u001 receipt_id=rcp_01M4RX5Q8J3T9W2B7KDN6CFGHB store=<text chars=7 sha=…> total=1072 needs_review=False issues=<list> → 漏れなし
3. WARNING app.receipts receipt: 検証に失敗しました（1回目）: <list> → 漏れなし
4. INFO app.voice transcribed user_id=u001 audio_seconds=3.81 text=<text chars=21 sha=…> → 漏れなし
5. INFO app.uploads upload_saved user_id=u001 kind=山田家の冷蔵庫.jpg → 漏れあり（山田家の冷蔵庫）
6. ERROR app.voice transcribe_failed user_id=u001 request_id=req_01M4RX5Q8J3T9W2B7KDN6CFGHC error=ValueError → 漏れなし
7. INFO app.usage usage_recorded user_id=u001 kind=llm input_tokens=1668 output_tokens=194 x_cache=<text chars=4 sha=…> → 漏れなし
""",
    "q4": """\
基準（指示文 v1・直接） → 適合率 1.0・再現率 1.0・項目一致率 1.0・完全一致率 1.0
(a) 直接（キャッシュを通さない） → 読み取り・LLM 1 回 → 適合率 1.0・再現率 1.0・項目一致率 0.9091・完全一致率 0.0 → 回帰 2 件
(b) 応答キャッシュ（S14 のキー） → miss・LLM 1 回 → 適合率 1.0・再現率 1.0・項目一致率 0.9091・完全一致率 0.0 → 回帰 2 件
(c) 応答キャッシュ（中身の SHA256 だけのキー） → hit・LLM 0 回 → 適合率 1.0・再現率 1.0・項目一致率 1.0・完全一致率 1.0 → 回帰なし
(d) 取り込みの窓口（S7） → 409 duplicate「このレシートはすでに取り込み済みです」・LLM 0 回 → 適合率 1.0・再現率 0.0・項目一致率 0.0・完全一致率 0.0 → 回帰 3 件
(a) の回帰：extraction.field_accuracy：1.0 → 0.9091（悪化。許容幅 0.0）
(a) の回帰：extraction.exact_match_rate：1.0 → 0.0（悪化。許容幅 0.0）
(a) の誤り：牛乳 の price：282 ≠ 228
""",
    "q5": """\
(1) セッション13のままの削除 → uploads 3・documents 0・receipts 0・voice 0・usage 2
(1) 削除の直後の GET /api/usage（u001） → llm 0/0・応答キャッシュ 命中 1／外れ 2
(1) 同じ写真をもう一度 → hit・LLM 0 回
(2) 応答キャッシュと帳簿まで消す削除 → uploads 3・documents 0・receipts 0・voice 0・usage 2 ／ 応答キャッシュから 1 件
(2) もう一度削除 → uploads 0・documents 0・receipts 0・voice 0・usage 0 ／ 応答キャッシュから 0 件
(2) 削除の直後の GET /api/usage（u001） → llm 0/0・応答キャッシュ 命中 0／外れ 0
(2) 同じ写真をもう一度 → miss・LLM 1 回
(2) u002 の結果 → 応答キャッシュ 残っている・GET /api/usage（u002） → llm 1668/194・応答キャッシュ 命中 0／外れ 1
""",
    "q6": """\
1. 4人が同時に話し終える：A 受付（前に 0 件）・B 受付（前に 1 件）・C 受付（前に 2 件）・D 503 stt_busy
2. D が Retry-After の 2 秒後に話し直す：503 stt_busy
3. A の認識が終わり、返答の読み上げが始まる
4. B・C の認識が終わる前に、A が割り込んで話し直す：受付（前に 2 件）
STT の待ち＋処理（いちばん長い場合・1件 2.4 秒）：A 2.4 秒・B 4.8 秒・C 7.2 秒・A の2回目 7.2 秒
A: listening → thinking(speech_end) → speaking(first_audio) → listening(barge_in) → thinking(speech_end) → speaking(first_audio) → listening(playback_done)
B: listening → thinking(speech_end) → speaking(first_audio) → listening(playback_done)
C: listening → thinking(speech_end) → speaking(first_audio) → listening(playback_done)
D: listening → thinking(speech_end) → listening(no_reply) → thinking(speech_end) → listening(no_reply)
D に送ったもの：vad(speech_end)・error(stt_busy)・vad(speech_end)・error(stt_busy)
入口の統計：認識した 4 件・断った 2 件・同時に動いた最大 1 件
A の返答：4 文（鶏むね肉とキャベツの塩炒め／キャベツをざく切りにします。／鶏むね肉を一口大に切って炒めます。／塩で味を調えたら完成です！）
TTS の入口（同時 1・待ち 3）：4 文を一度に頼むと 4/4 枠を1人で使う・1文ずつ頼めば 1/4 枠
""",
    "q7": """\
基準 → 入力 1668・STT 待ち行列 2
1. モデルを LLM_MODEL_LIGHT に替える → キャッシュ 外れる・入力 1668・評価 抽出をやり直す・保持期限 OK・単価表 見直す・STT 待ち行列 2
2. 縮小の上限を 1092 にする → キャッシュ 外れる・入力 1228・評価 抽出をやり直す・保持期限 OK・単価表 そのまま・STT 待ち行列 2
3. 指示文に「調味料は除いてください。」を足す → キャッシュ 外れる・入力 1680・評価 抽出をやり直す・保持期限 OK・単価表 そのまま・STT 待ち行列 2
4. 応答キャッシュの保持時間を 48 時間にする → キャッシュ そのまま・入力 1668・評価 不要・保持期限 NG・単価表 そのまま・STT 待ち行列 2
5. Whisper のモデルを base にする → キャッシュ そのまま・入力 1668・評価 CER 0.115 → 0.321（回帰 2 件）・保持期限 OK・単価表 そのまま・STT 待ち行列 6
""",
}

SOLUTIONS = {"q1": q1_same_photo, "q2": q2_monthly_cost, "q3": q3_log_lines, "q4": q4_eval_cache,
             "q5": q5_delete_all, "q6": q6_busy_turns, "q7": q7_change_impact}
TITLES = {
    "q1": "問題1 同じ冷蔵庫の写真を2回送る（応答キャッシュ・利用量・原本の保持期限・EXIF）",
    "q2": "問題2 画像トークン・PDF のページ・2つのキャッシュで月の費用を見積もる（仮の値）",
    "q3": "問題3 受付・レシート・音声認識・利用量のログ行をマスクに通す",
    "q4": "問題4 指示文を変えたあとの回帰テストを、どの経路で回すか",
    "q5": "問題5 DELETE /api/me/data に応答キャッシュと帳簿の消去を足す",
    "q6": "問題6 混んだ音声認識の入口と、割り込み・ターンの状態・遅延の内訳",
    "q7": "問題7 設定を1つ変えたときの影響を洗い出す",
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


finish("review04")
