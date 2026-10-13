"""セッション2の練習問題の解答（src/session02/solutions/）の動作確認。api コンテナの中で実行する：

    docker compose exec api python src/session02/verify_solutions.py

各解答の run() が返す行が、解答章に載せた「期待される出力」と一字一句同じであることを確かめる。
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from kondate.verifykit import check, eq, finish
from src.session02.solutions import p2_sniff, p3_read_capped, p4_bomb, p5_paths, p6_body_limit

logging.getLogger("pypdf").setLevel(logging.ERROR)
shutil.rmtree(Path("out/s02/solutions"), ignore_errors=True)


@check("S2 describe() が受け付ける5形式と、受け付けない形式（WAV・HEIC・ZIP・不明）を見分ける")
def _():
    eq(p2_sniff.run(), [
        "JPEG の画像 → JPEG（受け付ける）",
        "PNG の画像 → PNG（受け付ける）",
        "GIF の画像 → GIF（受け付ける）",
        "WebP の画像 → WEBP（受け付ける）",
        "PDF → PDF（受け付ける）",
        "WAV の音声 → WAV（受け付けない）",
        "HEIC の写真（先頭だけ） → HEIC（受け付けない）",
        "ZIP → ZIP（受け付けない）",
        "テキスト → 不明（受け付けない）",
    ], "出力")
    return "9 件"


@check("S3 read_capped() は上限+1バイトまでしか読まず、全部読む版は送られた分だけ読む")
def _():
    eq(p3_read_capped.run(), [
        "ちょうど上限／全部読んでから測る → 受け付け（読んだ 1,048,576 バイト）",
        "ちょうど上限／上限+1だけ読む → 受け付け（読んだ 1,048,576 バイト）",
        "上限+1バイト／全部読んでから測る → TooLarge（読んだ 1,048,577 バイト）",
        "上限+1バイト／上限+1だけ読む → TooLarge（読んだ 1,048,577 バイト）",
        "5MiB／全部読んでから測る → TooLarge（読んだ 5,242,880 バイト）",
        "5MiB／上限+1だけ読む → TooLarge（読んだ 1,048,577 バイト）",
    ], "出力")
    return "5MiB でも 1,048,577 バイトで止まる"


@check("S4 Pillow は上限の2倍までは警告だけ／PDF は 200 ページまで受け付ける")
def _():
    eq(p4_bomb.run(), [
        "8000×5000（40,000,000 画素）：既定＝開ける／警告を例外に＝開ける",
        "8000×6000（48,000,000 画素）：既定＝開ける（DecompressionBombWarning）／警告を例外に＝DecompressionBombWarning で拒否",
        "10000×9000（90,000,000 画素）：既定＝DecompressionBombError で拒否／警告を例外に＝DecompressionBombError で拒否",
        "200 ページの PDF → HTTP 201 kind=pdf",
        "201 ページの PDF → 413 too_large「PDF は 200 ページ以下にしてください」",
    ], "出力")
    return "4800万画素は既定では開けてしまう"


@check("S5 利用者のファイル名をつなぐと外に出られる／採番した名前は衝突しない")
def _():
    eq(p5_paths.run(), [
        "receipt.png → out/uploads/receipt.png（外に出る：いいえ）",
        "../../kondate/main.py → out/uploads/../../kondate/main.py（外に出る：はい）",
        "/etc/passwd → /etc/passwd（外に出る：はい）",
        "..\\..\\kondate\\main.py → out/uploads/..\\..\\kondate\\main.py（外に出る：いいえ）",
        "Windows のサーバーでは ..\\..\\kondate\\main.py → kondate\\main.py（外に出る：はい）",
        "u001 と u002 が同じ IMG_0001.jpg を送る → 同じパス：はい（後から来た方が上書きする）",
        "採番した名前 1000 件 → すべて異なる：はい・33 文字（up_＋ULID 26文字＋.png）",
    ], "出力")
    return "7 行"


@check("S6 Content-Length が上限を超えると、アプリ本体を呼ばずに 413 を返す")
def _():
    eq(p6_body_limit.run(), [
        "12MiB のファイル → 413 too_large（アプリ本体の呼び出し 0 回）",
        "10MiB＋1バイトのファイル → 413 too_large（アプリ本体の呼び出し 1 回）",
        "4×4 の PNG → 201（アプリ本体の呼び出し 1 回）",
    ], "出力")
    return "12MiB は入口で拒否・10MiB＋1バイトはエンドポイントで拒否"


finish("session02-solutions")
