"""セッション14の解答の検証。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session14
"""

from __future__ import annotations

from kondate.verifykit import check, eq, finish
from src.session14.solutions import (q1_usage_summary, q2_key_cases, q3_queue_size, q4_ask_cost, q5_warm_retry,
                                     q6_single_flight)


@check("S1 問題1：命中は記録せず、totals() は音声の秒数を混ぜる。種類ごとに数え直すと STT 6.31 秒・TTS 4.2 秒")
def _():
    eq(q1_usage_summary.run(), [
        'totals(u001): {"input_tokens": 1680, "output_tokens": 232, "audio_seconds": 10.51, "processing_seconds": 5.045}',
        'summarize(u001): {"llm": {"input_tokens": 1680, "output_tokens": 232}, "stt_seconds": 6.31, "tts_seconds": 4.2, '
        '"stt_processing_seconds": 3.155, "tts_processing_seconds": 1.89}',
        'summarize(u002): {"llm": {"input_tokens": 12, "output_tokens": 38}, "stt_seconds": 0.0, "tts_seconds": 0.0, '
        '"stt_processing_seconds": 0.0, "tts_processing_seconds": 0.0}',
        "記録した件数：6（命中の2件は記録しない）",
    ], "出力")
    return "totals の audio_seconds 10.51 ＝ STT 6.31＋TTS 4.2・記録 6 件"


@check("S2 問題2：8通りのうち命中は「もう一度」と「ファイル名だけ違う」の2つ。別解では PNG も命中")
def _():
    lines = q2_key_cases.run()
    eq([line.rsplit("：", 1)[1] for line in lines[:8]], ["命中", "命中"] + ["外れ"] * 6, "判定")
    eq(lines[8], "別解（前処理した後の JPEG でキーを作る）では 4 が命中になる", "別解")
    return "命中 2・外れ 6・別解で PNG が命中"


@check("S3 問題3：STT 待ち 2・TTS 待ち 3・同時 2 なら待ち 4。6件同時の受付と拒否が計算と CpuGate で一致")
def _():
    eq(q3_queue_size.run(), [
        "STT：1件 2.40 秒・待ってよい 5 秒・同時 1 件 → 待ち行列 2 件",
        "TTS：1件 1.65 秒・待ってよい 5 秒・同時 1 件 → 待ち行列 3 件",
        "STT：1件 2.40 秒・待ってよい 5 秒・同時 2 件 → 待ち行列 4 件",
        "6件同時（同時 1・待ち 2）：計算 受付 3・断る 3／CpuGate 受付 3・断る 3",
        "6件同時（同時 2・待ち 4）：計算 受付 6・断る 0／CpuGate 受付 6・断る 0",
    ], "出力")
    return "待ち 2・3・4／6件同時 3・3 と 6・0"


@check("S4 問題4：仮の値で (A) 15.23・(B) 12.19・(C) 5.02 USD/月")
def _():
    eq(q4_ask_cost.run(), [
        "1回あたりの入力（P_in 換算）：キャッシュなし 4888・作成 6107・読み出し 499.6（出力はどれも 38）",
        "(A) キャッシュなし：入力換算 14,664,000・出力 114,000 → 15.23 USD/月（仮の値での計算例）",
        "(B) 応答キャッシュだけ：入力換算 11,731,200・出力 91,200 → 12.19 USD/月（仮の値での計算例）",
        "(C) 応答キャッシュ＋プロンプトキャッシュ：入力換算 4,563,480・出力 91,200 → 5.02 USD/月（仮の値での計算例）",
    ], "出力")
    return "作成 6107・読み出し 499.6／15.23 → 12.19 → 5.02"


@check("S5 問題5：接続の失敗は2秒あけて最大3回、接続以外の失敗はすぐ諦める")
def _():
    eq(q5_warm_retry.run(), [
        "2回失敗して3回目で成功：state={'voicevox': 'ok'}・呼び出し 3 回・待った秒数 [2.0, 2.0]",
        "3回とも失敗：state={'voicevox': 'ng (ConnectError)'}・呼び出し 3 回・待った秒数 [2.0, 2.0]",
        "接続以外の失敗（RuntimeError）：state={'voicevox': 'ng (RuntimeError)'}・呼び出し 1 回・待った秒数 []",
    ], "出力")
    return "ok（3回）・ng (ConnectError)（3回）・ng (RuntimeError)（1回）"


@check("S6 問題6：同時の3件は計算1回にまとまり、失敗はキャッシュにも相乗りにも残らない")
def _():
    eq(q6_single_flight.run(), [
        "同時に3件：計算 1 回・miss／shared／shared・3件とも同じ結果=True",
        "後から1件：hit（計算は 1 回のまま）",
        "失敗：同時の2件とも RuntimeError・RuntimeError・キャッシュに残る=False → 次の1件は miss（計算は合計 3 回）",
    ], "出力")
    return "計算 1 回で 3 件・後から hit・失敗後は計算し直す"


finish("session14 solutions")
