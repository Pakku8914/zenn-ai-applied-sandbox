"""セッション8 練習問題の解答の検証。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session08

問題3 の解答は本文の src/session08/app.py そのもの（verify.py の V4・V5 で確かめている）。
ここでは音声認識を動かさない（計算だけで決まる値を確かめる）。
"""

from __future__ import annotations

from kondate.metrics import cer
from kondate.verifykit import check, eq, finish
from src.session08.loopback_check import CASES, judge
from src.session08.solutions.q1_describe_wav import describe_wav
from src.session08.solutions.q4_variants import table
from src.session08.solutions.q5_choose import MEASURED, choose, utterances_per_minute
from src.session08.solutions.q6_baseline import regressions, to_baseline
from src.session08.solutions.q7_alias import experiment
from src.session08.testaudio import tone_wav


@check("S1 48kHz・ステレオ・16bit・2.5 秒の WAV の諸元と、16kHz モノラルにしたときの大きさ")
def _():
    info = describe_wav(tone_wav(48000, 2.5, channels=2))
    eq(info, {"sample_rate": 48000, "channels": 2, "bits": 16, "frames": 120000, "seconds": 2.5,
              "file_bytes": 480044, "bytes_per_second": 192000, "pcm_bytes_16k_mono": 80000}, "諸元")
    return "192,000 バイト/秒・ファイル 480,044 バイト → 16kHz モノラルの PCM 80,000 バイト（1/6）"


@check("S2 CER の手計算（わかめ・和食・全角と記号・挿入・1 を超える例）")
def _():
    got = [
        round(cer("買い物リストに豆腐とわかめを追加して。", "買い物リストに豆腐と若目を追加して"), 4),
        round(cer("今日は30分以内で作れる和食がいいな。", "今日は30分以内で作れるは食がいいな"), 4),
        round(cer("２０分で作れる？", "20分で作れる"), 4),
        round(cer("タイマーを5分にセットして。", "タイマーを5分にセットしてください"), 4),
        round(cer("はい。", "はいはいはいはい"), 4),
    ]
    eq(got, [0.1667, 0.0556, 0.0, 0.3077, 3.0], "CER")
    return "0.1667・0.0556・0.0・0.3077・3.0"


@check("S4 表記ゆれの吸収を広げても、読み違い（番模範・は食）は残る")
def _():
    eq([(s, r) for _, s, r in table()],
       [(0.2222, 0.0), (0.1, 0.0), (0.1333, 0.0), (0.2667, 0.2667), (0.0556, 0.0556), (0.1538, 0.0), (0.0435, 0.0)],
       "厳密・ゆれ吸収")
    return "7 組のうち 5 組が 0.0 に・番模範 0.2667 と は食 0.0556 は残る"


@check("S5 条件を満たすいちばん軽い設定を選び、1 分あたりの処理量を見積もる")
def _():
    best = choose(MEASURED, max_cer=0.15, max_rtf=0.8, max_rss_mib=1024)
    eq((best.model, best.beam), ("small", 1), "CER 0.15・RTF 0.8・1024MiB")
    eq(choose(MEASURED, max_cer=0.15, max_rtf=0.5, max_rss_mib=1024), None, "RTF 0.5 以下が必要なとき")
    eq(choose(MEASURED, max_cer=0.35, max_rtf=0.8, max_rss_mib=1024).model, "tiny", "CER 0.35 まで許すとき")
    eq(choose(MEASURED, max_cer=0.15, max_rtf=0.8, max_rss_mib=512), None, "メモリ 512MiB のとき")
    eq(round(utterances_per_minute(0.578, 4.0), 1), 26.0, "4 秒の発話の処理量")
    return "small・beam 1 を選ぶ・4 秒の発話なら 1 分に 26.0 件まで"


@check("S6 基準との比較：上限内でも基準より悪くなれば回帰として見つける")
def _():
    same = [judge(CASES[0], "鶏むね肉とキャベツで20分で作れる料理は"), judge(CASES[1], "冷蔵庫に卵と牛乳とニンジンがあります。")]
    baseline = to_baseline(same)
    eq(list(baseline.values()), [0.0, 0.0], "基準")
    eq(regressions(same, baseline), [], "同じ結果")
    worse = [same[0], judge(CASES[1], "冷蔵庫に卵と牛入とニンジンがあります。")]
    eq(worse[1].passed, True, "上限（0.10）には収まっている")
    eq(regressions(worse, baseline), ["基準より悪化：冷蔵庫に卵と牛乳とにんじんがあります。（0.0 → 0.0556）"], "1 文字の悪化")
    nodict = [judge(CASES[0], "ニワトリ胸肉とキャベツで20分で作れる料理は"), same[1]]
    eq(len(regressions(nodict, baseline)), 2, "辞書なし（上限超え＋悪化）")
    return "同じ結果 0 件・1 文字の悪化 1 件・辞書なし 2 件"


@check("S7 間引く前のローパスで、10kHz が 6kHz に化ける音が 30dB 以上小さくなり、3kHz の音は 1dB 以内しか変わらない")
def _():
    r = experiment()
    assert r["alias_naive"] - r["alias_filtered"] >= 30, r
    assert abs(r["keep_naive"] - r["keep_filtered"]) <= 1, r
    assert r["keep_naive"] - r["alias_naive"] <= 10, r     # フィルタなしでは、化けた音が残したい音と大差ない大きさ
    return "折り返し 30dB 以上減・3kHz の差 1dB 以内"


finish("session08-solutions")
