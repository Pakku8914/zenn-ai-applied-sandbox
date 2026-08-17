#!/usr/bin/env python3
"""セッション3の自己検証。

本文・練習問題・解答に書いた数値と挙動が、実際のコードの出力と一致することを確かめる。
期待値と一致しなければ非0で終了する（人が出力を読んで判断しない）。
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from clean import (  # noqa: E402
    REPLACEMENT_CHAR, ZERO_WIDTH_SPACE, clean_text, has_broken_chars, is_order_suspect,
    jaccard, join_wrapped_lines, shingles, to_nfkc,
)
from dirty_corpus import (  # noqa: E402
    COMMUTE_PDF, COMMUTE_PDF_ALT, DEVICE_LIST_XLSX, PAID_LEAVE_PDF, load_raw,
)
from ingest import compute_diff, load_state, run_ingest, write_output  # noqa: E402
from inspect_corpus import from_raw, from_records, inspect  # noqa: E402
from ragkit.tokenize_ja import normalize as index_normalize  # noqa: E402

failures: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"{'OK ' if ok else 'NG '} {label}: got={got!r} want={want!r}")
    if not ok:
        failures.append(label)


# --- 1. NFKC の効果と副作用（stdlib の挙動を固定する）------------------------
check("NFKC: 全角英数は半角になる", to_nfkc("Ｗｅｂ３"), "Web3")
check("NFKC: 半角カナは全角カナになる", to_nfkc(chr(0xFF77) + chr(0xFF9E) + chr(0xFF76)), "ギカ")
check("NFKC: 丸数字は数字になる（箇条の意味が消える）",
      to_nfkc(chr(0x2460) + chr(0x2461) + chr(0x2462)), "123")
check("NFKC: 囲み文字は展開される", to_nfkc(chr(0x3231)), "(株)")
check("NFKC: 単位記号は展開される", to_nfkc("10" + chr(0x33A1)), "10m2")
check("NFKC: 全角チルダは半角チルダになる", to_nfkc("10時" + chr(0xFF5E) + "12時"), "10時~12時")
check("NFKC: 同義語はそろわない（有給休暇と年休）", to_nfkc("年休") == to_nfkc("有給休暇"), False)

# --- 2. 取り込み用の正規化（構造を保つ）-------------------------------------
check("見えない文字は落ちる", ZERO_WIDTH_SPACE in clean_text(f"利用{ZERO_WIDTH_SPACE}できる"), False)
check("置換文字は残る（文字化けの証拠を消さない）",
      REPLACEMENT_CHAR in clean_text(f"情報の{REPLACEMENT_CHAR}と件数"), True)
check("制御文字は落ちる", clean_text("必要とする。\x0b"), "必要とする。")
check("改ページは改行になる", clean_text("1ページ目\f2ページ目"), "1ページ目\n2ページ目")
check("行末の空白は落ちる", clean_text("本規程は、　\n次のとおり。"), "本規程は、\n次のとおり。")
check("空行が2行以上続く箇所は1行にそろう", clean_text("A。\n\n\n\nB。"), "A。\n\nB。")
check("定型のフッターは落ちる", clean_text("本文です。\nみなと商事株式会社 社外秘\n- 1 -"), "本文です。")
check("ルビは落ちる", clean_text("無線（むせん）LANの接続"), "無線LANの接続")
check("改行と大文字小文字は保たれる", clean_text("Ａ\nＢ"), "A\nB")

# 索引用の正規化（ragkit）とは目的が違うことを固定する
check("索引用の正規化は小文字化して改行も潰す", index_normalize("Ａ\nＢ"), "a b")

# --- 3. ハードラップの連結（既定では使わない）-------------------------------
check("折り返された行は連結できる",
      join_wrapped_lines("全社員が対象です。入社6か月未満の社員につ\nいては、付与日数が異なります。"),
      "全社員が対象です。入社6か月未満の社員については、付与日数が異なります。")
check("見出しは連結しない",
      join_wrapped_lines("1. 対象者\n全社員が対象です。"), "1. 対象者\n全社員が対象です。")
check("表は連結すると壊れる（だから既定では使わない）",
      join_wrapped_lines("区分 宿泊 日当\n国内宿泊 実費 3,000円"),
      "区分 宿泊 日当国内宿泊 実費 3,000円")

# --- 4. 重複と順序崩れの判定 -------------------------------------------------
check("同一文書の Jaccard は 1.0",
      jaccard(shingles("有給休暇の申請期限は3営業日前です。"), shingles("有給休暇の申請期限は3営業日前です。")),
      1.0)
check("無関係な文書の Jaccard は 0.0",
      jaccard(shingles("あいうえお"), shingles("かきくけこ")), 0.0)
check("2段組の順序崩れを検出できる", is_order_suspect(COMMUTE_PDF, COMMUTE_PDF_ALT), True)
check("同じ出力どうしは順序崩れにならない", is_order_suspect(PAID_LEAVE_PDF, PAID_LEAVE_PDF), False)

# --- 5. 抽出直後の点検（本文の出力と一致すること）---------------------------
raw = load_raw()
check("抽出直後の件数", len(raw), 19)
raw_report = inspect(from_raw(raw))
expected_raw = {
    "文書数": 19,
    "実質空（10字未満）": 2,
    "完全重複（余剰）": 2,
    "近重複（余剰・Jaccard>=0.80）": 1,
    "ヘッダー・フッターの残存": 12,
    "全角英数・囲み文字を含む": 8,
    "3行以上の連続改行": 5,
    "置換文字・制御文字": 1,
    "抽出結果の不一致（順序崩れの疑い）": 1,
    "要レビュー": 0,
}
for key, want in expected_raw.items():
    check(f"raw 点検 / {key}", raw_report["stats"][key], want)
check("raw 文字数の分布", raw_report["buckets"],
      {"0-9": 2, "10-99": 0, "100-1999": 16, "2000-": 1})

# --- 6. 取り込みの結果 -------------------------------------------------------
result = run_ingest(raw)
check("取り込んだ件数", len(result.records), 13)
check("除外の内訳", result.dropped_counts(), {"empty": 3, "exact_dup": 2, "near_dup": 1})
check("doc_id の一覧", [r["doc_id"] for r in result.records], [
    "HD-account-mfa-faq",
    "HD-account-password-faq",
    "HD-account-permission-procedure",
    "HD-keihi-commute-procedure",
    "HD-keihi-travel-expense-procedure",
    "HD-kintai-paid-leave-procedure",
    "HD-office-entry-card-procedure",
    "HD-office-meeting-room-notice-0520",
    "HD-office-soumu-handbook",
    "HD-pc-device-list",
    "HD-pc-wifi-faq",
    "HD-security-data-out-policy",
    "HD-security-usb-policy",
])
check("要レビューの一覧",
      [(r["doc_id"], r["review_reasons"]) for r in result.review_items()],
      [("HD-account-permission-procedure", ["acl_unknown"]),
       ("HD-keihi-commute-procedure", ["order_suspect"]),
       ("HD-security-data-out-policy", ["mojibake"])])
check("警告は1件（doc_class の欠落）", len(result.warnings), 1)
check("推定した source_type",
      next(r["source_type"] for r in result.records if r["doc_id"] == "HD-pc-device-list"), "faq")
check("ACL 不明は最も狭い範囲に倒す",
      next(r["visibility"] for r in result.records
           if r["doc_id"] == "HD-account-permission-procedure"), "manager")
check("表題は日付サフィックスを落とす",
      next(r["title"] for r in result.records
           if r["doc_id"] == "HD-office-meeting-room-notice-0520"), "会議室予約の運用変更のお知らせ")

paid = next(r for r in result.records if r["doc_id"] == "HD-kintai-paid-leave-procedure")
check("本文からフッターが消えている", "社外秘" in paid["body"], False)
check("本文からページ番号が消えている", "- 1 -" in paid["body"], False)
check("全角英数が半角になっている", "Web申請フォーム" in paid["body"], True)
check("文字化けは本文に残っている（人が判断する）",
      has_broken_chars(next(r["body"] for r in result.records
                            if r["doc_id"] == "HD-security-data-out-policy")), True)

clean_report = inspect(from_records(result.records))
expected_clean = {
    "文書数": 13,
    "実質空（10字未満）": 0,
    "完全重複（余剰）": 0,
    "近重複（余剰・Jaccard>=0.80）": 0,
    "ヘッダー・フッターの残存": 0,
    "全角英数・囲み文字を含む": 0,
    "3行以上の連続改行": 0,
    "置換文字・制御文字": 1,
    "抽出結果の不一致（順序崩れの疑い）": 1,
    "要レビュー": 3,
}
for key, want in expected_clean.items():
    check(f"clean 点検 / {key}", clean_report["stats"][key], want)
check("clean 文字数の分布", clean_report["buckets"],
      {"0-9": 0, "10-99": 0, "100-1999": 12, "2000-": 1})

# --- 7. 冪等性と差分検出 -----------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp)
    first = run_ingest(raw, load_state(out / "state.json"))
    write_output(first, out)
    docs_1 = (out / "docs.jsonl").read_bytes()
    state_1 = (out / "state.json").read_bytes()
    check("初回は全件が追加になる", len(first.diff["added"]), 13)

    second = run_ingest(raw, load_state(out / "state.json"))
    write_output(second, out)
    check("2回目の出力はバイト単位で同じ", (out / "docs.jsonl").read_bytes() == docs_1, True)
    check("2回目の state もバイト単位で同じ", (out / "state.json").read_bytes() == state_1, True)
    check("2回目の差分（追加）", len(second.diff["added"]), 0)
    check("2回目の差分（更新）", len(second.diff["changed"]), 0)
    check("2回目の差分（変更なし）", len(second.diff["unchanged"]), 13)

    # 元文書を1件書き換えると「更新」になる（doc_id は変わらない）
    edited = [dict(r) for r in raw]
    for record in edited:
        if record["key"] == "security/usb-policy":
            record["text"] = record["text"] + "第6条（棚卸） 貸与した機器は四半期ごとに棚卸を行う。\n"
    third = run_ingest(edited, load_state(out / "state.json"))
    check("書き換えは更新として検出される", third.diff["changed"], ["HD-security-usb-policy"])
    check("書き換えても doc_id は変わらない", len(third.records), 13)

    # 元文書が1件消えると「削除」になる
    removed_input = [r for r in raw if r["key"] != "pc/wifi-faq"]
    fourth = run_ingest(removed_input, load_state(out / "state.json"))
    check("削除が検出される", fourth.diff["removed"], ["HD-pc-wifi-faq"])
    check("削除後の件数", len(fourth.records), 12)

    report = json.loads((out / "ingest_report.json").read_text(encoding="utf-8"))
    check("レポートに除外の内訳が残る", len(report["dropped"]), 6)

check("差分の計算（空の状態からは全件追加）",
      compute_diff([{"doc_id": "A", "content_hash": "x"}], {})["added"], ["A"])

# --- 8. 練習問題・解答に載せた数値 -------------------------------------------
storage = clean_text(PAID_LEAVE_PDF)
check("問3: 取り込み用の行数", len(storage.splitlines()), 18)
check("問3: 取り込み用の先頭行", storage.splitlines()[0], "有給休暇の申請手順書")
check("問3: 索引用は1行になる", len(index_normalize(PAID_LEAVE_PDF).splitlines()), 1)
check("問3: 索引用も表題で始まる",
      index_normalize(PAID_LEAVE_PDF).startswith("有給休暇の申請手順書"), True)

check("問2: ローマ数字は展開される", to_nfkc(chr(0x2163)), "IV")
symbol_re = re.compile(r"[^\w\s]")
check("問6: 記号除去で型番が変わる", symbol_re.sub("", "MN-Book13"), "MNBook13")
check("問6: 記号除去で句点が消える", symbol_re.sub("", "申請します。以上。"), "申請します以上")
check("問6: 連結で手順書は13行になる",
      len(join_wrapped_lines(storage).splitlines()), 13)
device = clean_text(DEVICE_LIST_XLSX)
check("問6: 機種一覧は7行", len(device.splitlines()), 7)
check("問6: 連結で機種一覧は1行に潰れる", len(join_wrapped_lines(device).splitlines()), 1)


def _has_repeated_lines(text: str, min_count: int = 2) -> bool:
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return any(c >= min_count for c in Counter(lines).values())


check("問8: raw で同じ行が2回以上出る文書",
      sum(1 for i in from_raw(raw) if _has_repeated_lines(i["text"])), 7)
check("問8: clean で同じ行が2回以上出る文書",
      sum(1 for i in from_records(result.records) if _has_repeated_lines(i["text"])), 1)

n = len(result.records)
check("問10: 完全重複の割合", f"{result.dropped_counts()['exact_dup'] / n * 100:.1f}", "15.4")
check("問10: 要レビューの割合", f"{len(result.review_items()) / n * 100:.1f}", "23.1")
check("問10: 推定に頼った割合", f"{len(result.warnings) / n * 100:.1f}", "7.7")
check("問5: 既定では正規フォルダの文書が残る",
      next(r["source_path"] for r in result.records
           if r["doc_id"] == "HD-kintai-paid-leave-procedure"),
      "pdf/2026/勤怠/有給休暇の申請手順書.pdf")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション3の検証はすべて成功しました。")
