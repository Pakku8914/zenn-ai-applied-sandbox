#!/usr/bin/env python3
"""ログの取り込み口でかけるマスキング（個人情報の落とし方）。

  python src/session17/masking.py

方針:
  - 落とす（drop）  : 検索の改善に使わないのに危ないもの（IP・UA・生成文）
  - 戻せなくする（hash）: 同一性だけ要るもの（利用者ID・セッションID）
  - マスクする（mask）: 失敗を読むのに要るが PII が混ざりうるもの（クエリ本文）
  - そのまま残す（keep）: 権限コンテキストや件数など、集計と再現に要るもの

「あとで消す」は運用では実行されない。**取り込み口で落とす**のが唯一守られる設計。
"""

from __future__ import annotations

import hashlib
import re

# 落とすフィールド / ハッシュ化するフィールド / 本文として扱うフィールド
DROP_FIELDS: tuple[str, ...] = ("raw_ip", "user_agent", "answer_text")
HASH_FIELDS: tuple[str, ...] = ("session_id", "user_id")
TEXT_FIELDS: tuple[str, ...] = ("query_text", "text")

# 置換は上から順にかける。プレースホルダ自身はどのパターンにも当たらない形にしてある
# （当たると2回かけたときに結果が変わり、冪等でなくなる）。
PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<EMAIL>"),
    ("phone", re.compile(r"0\d{1,4}-\d{1,4}-\d{4}"), "<PHONE>"),
    ("employee_id", re.compile(r"EMP-\d{4,6}"), "<EMPLOYEE_ID>"),
    ("ip", re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])"), "<IP>"),
    ("long_digits", re.compile(r"(?<!\d)\d{12,}(?!\d)"), "<DIGITS>"),
)


def mask_text(text: str) -> str:
    """クエリ本文から機械的に判別できる PII を落とす。

    氏名は正規表現では落とせない。だからこそ「本文を残すかどうか」を
    先に決める必要がある（sanitize の text_policy を参照）。
    """
    out = text
    for _, pattern, placeholder in PATTERNS:
        out = pattern.sub(placeholder, out)
    return out


def pii_hits(text: str) -> list[str]:
    """当たった PII パターンの名前を返す（監査用）。"""
    return [name for name, pattern, _ in PATTERNS if pattern.search(text)]


def hash_value(value: str, salt: str) -> str:
    """ソルト付きハッシュ。元の値には戻せない（が、同一性は判定できる）。"""
    digest = hashlib.sha256(f"{salt}|{value}".encode("utf-8")).hexdigest()
    return digest[:16]


def is_sanitized(record: dict) -> bool:
    return record.get("pii_state") == "sanitized"


def sanitize(record: dict, *, salt: str, text_policy: str = "mask") -> dict:
    """1行を保存してよい形にする。**冪等**（2回かけても結果が変わらない）。

    text_policy:
      "mask" 本文を残す（PII はマスク）。失敗クラスタを読める
      "hash" 本文を残さない。同じクエリかどうかだけ分かる
      "drop" 本文を捨てる。頻度も追えなくなる
    """
    if text_policy not in ("mask", "hash", "drop"):
        raise ValueError(f"未知の text_policy です: {text_policy}")
    if is_sanitized(record):
        return dict(record)  # 再処理されても同じ結果になる

    out: dict = {}
    for key, value in record.items():
        if key in DROP_FIELDS:
            continue
        if key in HASH_FIELDS:
            out[key] = None if value is None else hash_value(str(value), salt)
            continue
        if key in TEXT_FIELDS:
            masked = mask_text(str(value))
            if text_policy == "mask":
                out[key] = masked
            elif text_policy == "hash":
                out[key] = f"qhash:{hash_value(masked, salt)}"
            continue
        out[key] = value
    out["pii_state"] = "sanitized"
    return out


def sanitize_log(rows: list[dict], *, salt: str, text_policy: str = "mask") -> list[dict]:
    return [sanitize(r, salt=salt, text_policy=text_policy) for r in rows]


DIRTY_SAMPLE: dict = {
    "ts": "2026-08-15T09:12:00+09:00",
    "request_id": "req-0001",
    "session_id": "sess-77",
    "user_id": "u-1043",
    "user_role": "member",
    "user_dept": "経理部",
    "query_text": "yamada.taro@minato.example.co.jp の立替金 090-1234-5678 EMP-10432",
    "n_results": 4,
    "raw_ip": "10.20.30.40",
    "user_agent": "Mozilla/5.0 (Windows NT 10.0)",
    "answer_text": "山田太郎さんの立替金は……",
}


def main() -> None:
    print("=== 生のログ行（このまま保存してはいけない）===")
    for key, value in DIRTY_SAMPLE.items():
        print(f"  {key}: {value}")

    print(f"\n当たった PII パターン: {pii_hits(DIRTY_SAMPLE['query_text'])}")

    cleaned = sanitize(DIRTY_SAMPLE, salt="2026-08-15", text_policy="mask")
    print("\n=== 保存してよい形（text_policy=mask）===")
    for key, value in cleaned.items():
        print(f"  {key}: {value}")

    twice = sanitize(cleaned, salt="2026-08-15", text_policy="mask")
    print(f"\n2回かけても同じ（冪等）: {twice == cleaned}")

    hashed = sanitize(DIRTY_SAMPLE, salt="2026-08-15", text_policy="hash")
    print(f"本文を残さない場合の query_text: {hashed['query_text']}")


if __name__ == "__main__":
    main()
