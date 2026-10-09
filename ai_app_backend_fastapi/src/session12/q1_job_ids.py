"""練習問題1の解答：ジョブ ID の形を Redis に問い合わせる前に確かめ、ID から登録時刻を読む。"""

from __future__ import annotations

import re
from datetime import datetime

from ulid import ULID

from kondate.clock import JST

# ULID は Crockford の Base32（I・L・O・U を使わない）で26文字。先頭は 0〜7（48ビットの時刻が収まる範囲）
JOB_ID = re.compile(r"job_[0-7][0-9A-HJKMNP-TV-Z]{25}")


def parse_job_id(raw: str) -> str | None:
    """job_ + ULID の形なら ULID 部分を大文字に揃えて返し、違えば None。"""
    if not raw.startswith("job_"):
        return None
    candidate = "job_" + raw[4:].upper()  # Base32 は大文字・小文字を区別しない。保存しているのは大文字
    return candidate if JOB_ID.fullmatch(candidate) else None


def job_created_at(job_id: str) -> datetime:
    """ID に入っている登録時刻（ミリ秒まで）を JST で返す。"""
    return ULID.from_str(job_id[4:]).datetime.astimezone(JST)
