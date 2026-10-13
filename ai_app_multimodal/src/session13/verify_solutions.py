"""セッション13：練習問題の解答の検証。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session13

問題4はコードのない問題なので検証しない。Whisper・VOICEVOX・mockllm は使わない。
"""

from __future__ import annotations

import asyncio

from kondate.verifykit import check, eq, finish
from src.session13.solutions import q1_inventory, q2_boundaries, q3_mask_cases, q5_consent_cases, q6_delete_check, q7_orphans


@check("V1 問題1：付帯情報の棚卸し")
def _():
    eq(q1_inventory.report(), [
        "fridge.jpg: EXIF=あり GPS=あり 機種=あり 撮影日時=あり",
        "fridge.jpg（前処理後）: EXIF=なし GPS=なし 機種=なし 撮影日時=なし",
        "receipt.png: EXIF=なし GPS=なし 機種=なし 撮影日時=なし",
        "receipt.pdf: タイトル=あり 作成者=なし 作成ソフト=あり",
    ], "表示")
    return "4 行が期待どおり"


@check("V2 問題2：保持期限の境界")
def _():
    eq(q2_boundaries.report(), [
        "upload   期限 24時間：1秒前=見える ちょうど=見えない 掃除=1件",
        "document 期限 30日：1秒前=見える ちょうど=見えない 掃除=1件",
        "receipt  期限 30日：1秒前=見える ちょうど=見えない 掃除=1件",
        "voice    期限 7日：1秒前=見える ちょうど=見えない 掃除=1件",
    ], "表示")
    return "4 種別とも、1秒前は見え、ちょうどで見えなくなる"


@check("V3 問題3：ログのマスクの7通り")
def _():
    eq(q3_mask_cases.run(), [
        "INFO q3 transcript user_id=u001 transcript=<text chars=21 sha=…>",
        "INFO q3 認識結果 <text chars=21 sha=…>",
        "INFO q3 upload_saved upload_id=up_test filename=<text chars=11 sha=…> bytes=89080",
        "INFO q3 voice_saved voice_id=vc_test pcm=<bytes len=640 sha=…>",
        "INFO q3 odd bytes=<bytes len=3 sha=…>",
        "INFO q3 receipt_read receipt=<dict>",
        "ERROR q3 turn_failed request_id=req_test error=ValueError",
    ], "表示")
    return "7 行が期待どおり"


@check("V4 問題5：store_audio の5通り")
def _():
    eq(asyncio.run(q5_consent_cases.run()), [
        "store_audio なし → ready.store_audio=False・保存 0 件",
        "store_audio=false → ready.store_audio=False・保存 0 件",
        'store_audio="true" → ready.store_audio=False・保存 0 件',
        "store_audio=1 → ready.store_audio=False・保存 0 件",
        "store_audio=true → ready.store_audio=True・保存 1 件",
    ], "表示")
    return "JSON の true だけが保存になる"


@check("V5 問題6：2人の利用者での削除")
def _():
    eq(asyncio.run(q6_delete_check.run()), [
        "1回目 u001: uploads=1 documents=1 receipts=0 voice=1 usage=3",
        "2回目 u001: uploads=0 documents=0 receipts=0 voice=0 usage=0",
        "u002 の残り: uploads=1 documents=0 receipts=0 voice=1 usage=3／ファイル 2 件",
        "ログにファイル名・文字起こし: なし",
    ], "表示")
    return "u001 だけが消え、2回目は 0 件"


@check("V6 問題7：孤児ファイルの掃除")
def _():
    eq(q7_orphans.run(), [
        "削除（uploads）: ['up_old.jpg']",
        "削除（voice）: ['vc_old.wav']",
        "残す: ['up_known.jpg', 'up_new.jpg']",
    ], "表示")
    return "期限切れの孤児だけを消し、台帳にあるファイルと期限内の孤児は残す"


finish("session13 solutions")
