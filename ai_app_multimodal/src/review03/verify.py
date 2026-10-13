"""復習3（セッション2〜11の横断復習）の解答コードの動作確認。各解答の main() の出力が、解答章に載せた
「期待される出力」と一致するかを見る。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/review03

問題2は VOICEVOX と Whisper（small・キャッシュ済み）、問題6は mockllm を使う。処理時間は出力にも合否にも使わない。
認識の結果は文字列で比べず、CER のしきい値を満たすか（はい／いいえ）で比べる。
"""

from __future__ import annotations

import contextlib
import io
import logging

from kondate.verifykit import check, eq, finish
from src.review03.solutions import (
    q1_two_windows, q2_loopback, q3_heard, q4_latency, q5_ws_log, q6_voice_answers, q7_after_barge_in,
)

logging.getLogger("pypdf").setLevel(logging.ERROR)

EXPECTED = {
    "q1": """\
receipt.png → uploads 201 image・画像 726 トークン ／ transcribe 415 unsupported_media
fridge.jpg → uploads 201 image・画像 1610 トークン ／ transcribe 415 unsupported_media
無地の JPEG（4000×3000） → uploads 201 image・画像 2352 トークン ／ transcribe 415 unsupported_media
receipt.pdf → uploads 201 pdf・文書 1600 トークン ／ transcribe 415 unsupported_media
WAV 24kHz・1秒 → uploads 415 unsupported_media ／ transcribe OK・16kHz 16000 サンプル（1.00 秒）
WAV 16kHz・60秒 → uploads 415 unsupported_media ／ transcribe OK・16kHz 960000 サンプル（60.00 秒）
WAV 16kHz・61秒 → uploads 415 unsupported_media ／ transcribe 413 too_large
WAV 48kHz・ステレオ・54秒 → uploads 415 unsupported_media ／ transcribe OK・16kHz 864000 サンプル（54.00 秒）
WAV 48kHz・ステレオ・55秒 → uploads 413 too_large ／ transcribe 413 too_large
WAV 16kHz・0.05秒 → uploads 415 unsupported_media ／ transcribe 422 invalid_request
WAV 8bit・1秒 → uploads 415 unsupported_media ／ transcribe 415 unsupported_media
uploads の固定文: 413「ファイルは 10MB 以下にしてください」・415「JPEG・PNG・WebP・GIF の画像か PDF を送ってください」
transcribe の固定文: 413「ファイルは 10MB 以下にしてください」・413「音声は 60 秒以下にしてください」・415「WAV（PCM 16bit）の音声を送ってください」・422「入力値が正しくありません：audio（0.1 秒以上の音声を送ってください）」
""",
    "q2": """\
鶏むね肉とキャベツで20分で作れる料理は？ → 24000Hz・1ch・16bit・SHA256 一致 → 16kHz のサンプル数 一致・16kHz と偽ると 1.50 倍 → ゆれ吸収 CER ≤ 0.10 はい・厳密 ≥ ゆれ吸収 はい
冷蔵庫に卵と牛乳とにんじんがあります。 → 24000Hz・1ch・16bit・SHA256 一致 → 16kHz のサンプル数 一致・16kHz と偽ると 1.50 倍 → ゆれ吸収 CER ≤ 0.10 はい・厳密 ≥ ゆれ吸収 はい
24kHz のまま渡すと: ValueError「サンプリングレートは 16000Hz にしてください（受け取ったのは 24000Hz）」
""",
    "q3": """\
文の数: 5（番号付きリストの「1.」「2.」「3.」と空行は読まない）
文ができた差分: 8・13・20・25・flush（差分は全 32 個）
送り終えた時刻: 0.8・1.3・2.0・2.5・3.2 秒
鳴り終わりの見積もり: 6.975・10.1・14.35・17.85・23.225 秒
0.5 秒に話しかける → listening → thinking → listening（barge_in）・interrupted 0・履歴 user 1行
5.0 秒に話しかける → listening → thinking → speaking → listening（barge_in）・interrupted 0・履歴 user 1行 ／ assistant 割り込みの印だけ
8.0 秒に話しかける → listening → thinking → speaking → listening（barge_in）・interrupted 1・履歴 user 1行 ／ assistant 1 文＋割り込みの印
12.0 秒に話しかける → listening → thinking → speaking → listening（barge_in）・interrupted 2・履歴 user 1行 ／ assistant 2 文＋割り込みの印
30.0 秒まで話しかけない → listening → thinking → speaking → listening（playback_done）・interrupted なし・履歴 user 1行 ／ assistant 5 文
""",
    "q4": """\
A: vad 600・stt 1650（待ち 30・RTF 0.43）・llm_first_sentence 50・tts_first 3400・その他 12 → tts_first が 59.5% → 最初の文を短くする
B: vad 600・stt 1650（待ち 30・RTF 0.43）・llm_first_sentence 1470・tts_first 3400・その他 12 → tts_first が 47.7% → 最初の文を短くする
C: vad 600・stt 3850（待ち 2200・RTF 0.43）・llm_first_sentence 50・tts_first 3400・その他 12 → stt が 48.7% → 認識の順番待ちを減らす
D: vad 600・stt 400（待ち 20・RTF 0.42）・返答なし → 内訳を比べない
文ごと（RTF 0.4）: 最初の音 3.4 秒・途切れ 0.0/0.0/0.0/0.0・鳴り終わり 33.9 秒 ／ 全文: 最初の音 12.2 秒・鳴り終わり 42.7 秒
文ごと（RTF 1.2）: 最初の音 10.2 秒・途切れ 0.0/0.0/0.0/3.4・鳴り終わり 44.1 秒 ／ 全文: 最初の音 36.6 秒・鳴り終わり 67.1 秒
""",
    "q5": """\
正常な1往復: listening → thinking → speaking ／ 違反なし
読み上げ中に割り込んで次のターン: listening → thinking → speaking → listening（barge_in） → thinking → speaking ／ 違反なし
送り終えたあとの再生中に割り込み: listening → thinking → speaking → listening（barge_in） ／ 違反なし
鳴り終えてから次の発話: listening → thinking → speaking → listening（playback_done） → thinking → speaking ／ 違反なし
聞き取れなかったターン: listening → thinking → listening（no_reply） → thinking → speaking ／ 違反なし
割り込みのあとに turn_end: listening → thinking → speaking → listening（barge_in） ／ 9 通目 turn_end: 開いていないターンを閉じている
返答中に VAD の出来事を流す: listening → thinking → speaking ／ 8 通目 vad:speech_end: speaking から thinking へは移れません（speech_end）
送っていない文の番号で止める: listening → thinking → speaking ／ 8 通目 interrupted:2: index が送った audio の数（1）を超えている
WAV の長さが違う: listening → thinking → speaking ／ 6 通目 wav: バイナリは audio の直後に、bytes と同じ長さで送る
クレジットのない ready: listening ／ 1 通目 ready: 1通目は credit「VOICEVOX:ずんだもん」付きの ready にする
""",
    "q6": """\
肉じゃがは何人分ですか？（かなの寄せ方: 両側） → pages [29]・200・usage 1688/38・LLM 1 回 → 読み上げ 2 文: 肉じゃがは4人分です。／根拠は29ページにあります。
肉ジャガは何人分ですか？（かなの寄せ方: なし） → pages なし・422・usage 0/0・LLM 0 回 → 読み上げ 2 文: どのレシピのことか分かりませんでした。／料理の名前を入れて、もう一度聞いてください。
肉ジャガは何人分ですか？（かなの寄せ方: 両側） → pages [29]・200・usage 1688/38・LLM 1 回 → 読み上げ 2 文: 肉じゃがは4人分です。／根拠は29ページにあります。
ハンバーグは何人分ですか？（かなの寄せ方: 質問だけ） → pages なし・422・usage 0/0・LLM 0 回 → 読み上げ 2 文: どのレシピのことか分かりませんでした。／料理の名前を入れて、もう一度聞いてください。
ハンバーグは何人分ですか？（かなの寄せ方: 両側） → pages [33]・502・usage 3378/76・LLM 2 回 → 読み上げ 2 文: 本の中で根拠を確かめられませんでした。／別の聞き方で試してください。
レシート（合計が合わない） → 要確認 1 件 → 読み上げ 3 文: 要確認が1件あります。／明細の金額の合計と、合計金額が一致しません。／金額を確かめてください。
冷蔵庫の食材（鶏ムネ肉・にんじん） → 要確認 2 件 → 読み上げ 5 文: 要確認が2件あります。／鶏ムネ肉は、食材辞書にない名前です。／名前が正しいか確かめてください。／にんじんは、読み取りの確からしさが低い食材です。／写真と合っているか確かめてください。
mockllm のシナリオ: recipe_pdf_ask×4
""",
    "q7": """\
読み上げ中（2文目の途中）に話しかける: ready → vad:speech_start → vad:speech_end → transcript → audio:0 → audio:1 → vad:speech_start → interrupted:1 → vad:speech_end → transcript → audio:0 → turn_end
  状態: listening → thinking → speaking → listening（barge_in） → thinking → speaking
  履歴: user 1行 ／ assistant 1 文＋割り込みの印 ／ user 1行・捨てた音 0
  利用量: stt ／ tts 9.0 秒 ／ stt ／ llm ／ tts 2.5 秒・ストリーム 途中で閉じた 1・最後まで 1
考えている間（返答の文字の途中）に話しかける: ready → vad:speech_start → vad:speech_end → transcript → vad:speech_start → interrupted:0 → vad:speech_end → transcript → audio:0 → turn_end
  状態: listening → thinking → listening（barge_in） → thinking → speaking
  履歴: user 2行・捨てた音 0
  利用量: stt ／ stt ／ llm ／ tts 2.5 秒・ストリーム 途中で閉じた 1・最後まで 1
咳をしただけで最後まで聞く: ready → vad:speech_start → vad:speech_end → transcript → audio:0 → audio:1 → turn_end
  状態: listening → thinking → speaking → listening（playback_done）
  履歴: user 1行 ／ assistant 2 文・捨てた音 1
  利用量: stt ／ llm ／ tts 1.75 秒・ストリーム 途中で閉じた 0・最後まで 1
""",
}

SOLUTIONS = {"q1": q1_two_windows, "q2": q2_loopback, "q3": q3_heard, "q4": q4_latency, "q5": q5_ws_log,
             "q6": q6_voice_answers, "q7": q7_after_barge_in}
TITLES = {
    "q1": "問題1 画像と音声の窓口に同じファイルを送る（上限・形式・次に渡す量）",
    "q2": "問題2 読み上げた 24kHz の声を受付から認識まで通す（閉ループ）",
    "q3": "問題3 Markdown の返答がどこまで伝わったかを計算する",
    "q4": "問題4 遅延の内訳から支配的な区間を見つけ、対策を選ぶ",
    "q5": "問題5 WebSocket の記録を取り決めと状態機械で検査する",
    "q6": "問題6 声の質問に、PDF の答えと要確認を読み上げで返す",
    "q7": "問題7 割り込みのあとに何が残るか（状態・履歴・利用量）",
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


finish("review03")
