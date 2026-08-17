#!/usr/bin/env python3
"""セッション15の自己検証：表・コードの扱いが決定的に回ること。

  1. コーパスに実在する「テキストでない資産」の数（表40・行197・コード2・画像0）
  2. 表がチャンク方式によって壊れたり壊れなかったりすること
  3. 行文章化した仮想チャンクの中身と、行を単位にした検索が当たること
  4. 列に型を宣言してから数値化する仕組み（型を宣言しないと何が起きるか）
  5. 構造化ストア（sqlite3）が数値条件に正確に答えること
  6. 数値条件のクエリが語彙一致では解けない理由（文字列としての事実）
  7. コードのトークナイズと3段構えの検索
  8. 型別パイプラインのブロック分割・ルーティング

埋め込みモデルもリランカも使わない。APIキーも不要。
期待値と一致しなければ非0で終了する。
"""

from __future__ import annotations

import re
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ragkit.chunk import chunk_heading  # noqa: E402
from ragkit.corpus import load_docs  # noqa: E402
from ragkit.tokenize_ja import tokenize  # noqa: E402
from code_search import (  # noqa: E402
    code_tokens,
    code_units,
    identifiers,
    literal_search,
    search_code,
    split_identifier,
)
from pipeline import (  # noqa: E402
    false_headings,
    ingest,
    inventory,
    mask_fences,
    route,
    split_blocks,
)
from row_sentences import build_row_index  # noqa: E402
from table_break import report  # noqa: E402
from table_store import build_db, find_rows, stats, sum_of  # noqa: E402
from table_tools import COLUMN_TYPES, measure, naive_number, parse_tables  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def eq(label: str, got, want) -> None:
    check(label, got == want, f"got={got!r} want={want!r}")


docs = load_docs()
by_title = {d.title: d.doc_id for d in docs}
by_id = {d.doc_id: d for d in docs}

EXPECTED_IDS = {
    "各種手当の支給手順書（第1版）": "DOC-0094",
    "各種手当の支給チェックリスト": "DOC-0096",
    "PCの故障対応手順書（第2版）": "DOC-0111",
    "周辺機器の貸出手順書（第1版）": "DOC-0126",
    "会議室の予約手順書（第1版）": "DOC-0200",
    "セキュリティ事故の報告手順書（第2版）": "DOC-0283",
    "機密文書の廃棄手順書（第1版）": "DOC-0291",
}

# --- 0. 前提 -----------------------------------------------------------------
print("--- 0. 前提 ---")
eq("コーパスの文書数", len(docs), 301)
mismatched = {t: by_title.get(t, "（そのタイトルの文書が無い）")
              for t, i in EXPECTED_IDS.items() if by_title.get(t) != i}
check("章で名指しする文書の doc_id が期待どおり", not mismatched, f"ずれ {mismatched}")

# --- 1. 資産の棚卸し ----------------------------------------------------------
print("\n--- 1. 資産の棚卸し ---")
inv = inventory(docs)
eq("表を含む文書", inv["docs_with_table"], 40)
eq("表の数", inv["tables"], 40)
eq("表のデータ行", inv["table_rows"], 197)
eq("コードを含む文書", inv["docs_with_code"], 2)
eq("コード単位（関数）", inv["code_units"], 2)
eq("コードの行数", inv["code_lines"], 9)
eq("画像は1枚も無い", inv["images"], 0)
eq("フェンス内の「見出しに見える行」", inv["false_headings"], 2)
masked = sum(len(false_headings(replace(d, body=mask_fences(d.body)))) for d in docs)
eq("フェンスを伏せると誤検出が消える", masked, 0)

# --- 2. 表の取り出し ----------------------------------------------------------
print("\n--- 2. 表の取り出し ---")
allowance = parse_tables(by_id["DOC-0094"])
eq("手当の表は1つ", len(allowance), 1)
eq("見出し（caption）", allowance[0].caption, "一覧")
eq("列名", allowance[0].columns, ("手当の種類", "対象者", "月額"))
eq("データ行数", len(allowance[0].rows), 5)
eq("役職手当の行", allowance[0].rows[3], ("役職手当", "課長以上", "40,000円"))

checklist = parse_tables(by_id["DOC-0096"])
eq("チェックリストの列名", checklist[0].columns, ("#", "確認項目", "判断の目安"))
eq("チェックリストの見出し", checklist[0].caption, "確認項目")

restored = 0
for doc in docs:
    for t in parse_tables(doc):
        restored += int(t.header_line() in doc.body)
        restored += sum(int(t.row_line(r) in doc.body) for r in t.rows)
eq("復元したヘッダ行とデータ行が原文にそのままある", restored, 40 + 197)

# --- 3. チャンク分割で壊れるか ------------------------------------------------
print("\n--- 3. チャンク分割で壊れるか ---")
rep = {r["label"]: r for r in report(docs)}
for label in ("sentence(400)", "heading(600)"):
    r = rep[label]
    check(f"{label} は 40 表すべてを壊さない",
          r["intact"] == 40 and r["orphan"] == 0 and r["lost"] == 0,
          f"intact={r['intact']} orphan={r['orphan']} lost={r['lost']}")
f480 = rep["fixed(400/80)"]
check("fixed(400/80) は表を壊す（1つのチャンクに収まらない表がある）",
      f480["intact"] < 40, f"intact={f480['intact']}/40")
check("fixed(400/80) はヘッダと離れた孤児行を作る", f480["orphan"] >= 1,
      f"orphan={f480['orphan']} 行")
eq("fixed(400/80) は行そのものは割らない（80字の重なりのおかげ）", f480["lost"], 0)
check("fixed(200/0) は行そのものを割る", rep["fixed(200/0)"]["lost"] >= 1,
      f"lost={rep['fixed(200/0)']['lost']} 行")

# セッション4の既知の弱点：コードブロック内のコメントが見出しとして検出される
code_doc = by_id["DOC-0111"]
torn = [c for c in chunk_heading(code_doc, 600)
        if c.text[len(code_doc.title):].lstrip("\n").startswith("# 資産管理台帳")]
eq("見出し分割はコードブロックを分断する（セッション4の弱点）", len(torn), 1)
check("分断されたチャンクには開始フェンスが無い", "```python" not in torn[0].text)

# --- 4. 行文章化 --------------------------------------------------------------
print("\n--- 4. 行文章化 ---")
index, rows = build_row_index()
eq("行チャンクの数", len(rows), 197)
by_chunk = {c.chunk_id: c for c in rows}
eq("役職手当の行の文",
   by_chunk["DOC-0094#R04"].text,
   "各種手当の支給手順書（第1版）／一覧：手当の種類は役職手当、対象者は課長以上、月額は40,000円。")
eq("MN-Book15 の行の文",
   by_chunk["DOC-0126#R02"].text,
   "周辺機器の貸出手順書（第1版）／一覧：機種名はMN-Book15、用途は開発業務、メモリは32GB、貸出期間は3年。")
eq("空セル（—）は文に入れない",
   by_chunk["DOC-0126#R04"].text,
   "周辺機器の貸出手順書（第1版）／一覧：機種名は外付けモニタ MN-D24、用途は常時利用、貸出期間は最長3か月。")
eq("連番列（#）は文に入れない",
   by_chunk["DOC-0096#R02"].text,
   "各種手当の支給チェックリスト／確認項目：確認項目は金額表を満たしているか、判断の目安は下表のとおり。")
check("行チャンクの ID は本文チャンクと別系列（#R）",
      all("#R" in c.chunk_id for c in rows))
check("行チャンクは権限（visibility）を引き継ぐ",
      all(c.meta.get("visibility") for c in rows))
eq("「役職手当」を含む行は1つだけ",
   sum(1 for c in rows if "役職手当" in c.text), 1)

ROW_QUERIES = [
    ("役職手当の月額はいくらですか", "DOC-0094#R04"),
    ("MN-Book15のメモリは", "DOC-0126#R02"),
    ("大会議室の定員は", "DOC-0200#R04"),
]
for q, want in ROW_QUERIES:
    hits = index.search(q, k=3, filters={"visibility": "all"})
    eq(f"行索引「{q}」の1位", hits[0].chunk_id if hits else "（0件）", want)

# --- 5. 列に型を宣言してから数値化する ----------------------------------------
print("\n--- 5. 数値化 ---")
MEASURES = [
    ("yen", "40,000円", ("定額", 40000.0, "円")),
    ("yen", "実費（上限30,000円）", ("上限", 30000.0, "円")),
    ("yen", "取得予定日の3営業日前", ("不明", None, "")),
    ("gb", "32GB", ("定額", 32.0, "GB")),
    ("gb", "—", ("不明", None, "")),
    ("months", "3年", ("定額", 36.0, "か月")),
    ("months", "最長3か月", ("上限", 3.0, "か月")),
    ("hour", "4時間", ("定額", 4.0, "時間")),
    ("people", "40名", ("定額", 40.0, "名")),
    ("", "40,000円", ("不明", None, "")),
]
for col_type, text, want in MEASURES:
    m = measure(col_type, text)
    eq(f"measure({col_type!r}, {text!r})", (m.bound, m.value, m.unit), want)

NAIVE = [("取得予定日の3営業日前", 3), ("1件5万円以上", 1),
         ("実費（上限30,000円）", 30000), ("PDF形式・日付入りのファイル名", None)]
for text, want in NAIVE:
    eq(f"naive_number({text!r})", naive_number(text), want)

judge_cells = [row[2] for doc in docs for t in parse_tables(doc)
               if t.columns == ("#", "確認項目", "判断の目安") for row in t.rows]
eq("チェックリストの「判断の目安」セル", len(judge_cells), 180)
eq("型を宣言せずに数値を拾うと意味のない数が付くセル",
   sum(1 for c in judge_cells if naive_number(c) is not None), 23)
eq("「判断の目安」は型を宣言していない列", "判断の目安" in COLUMN_TYPES, False)

# --- 6. 構造化ストア ----------------------------------------------------------
print("\n--- 6. 構造化ストア（sqlite3）---")
conn = build_db(docs)
s = stats(conn)
eq("セルの総数", s["cells"], 599)
eq("型を宣言した列のセル", s["typed"], 25)
eq("数値にできたセル", s["numeric"], 24)
eq("上限として扱うセル", s["bounded"], 2)

hit = find_rows(conn, "月額", ">=", 30000.0)
eq("月額30,000円以上（定額のみ）", [(r["row_key"], r["value_text"]) for r in hit],
   [("役職手当", "40,000円")])
hit2 = find_rows(conn, "月額", ">=", 30000.0, bounds=("定額", "上限"))
eq("月額30,000円以上（上限も含める）", [r["row_key"] for r in hit2], ["役職手当", "通勤手当"])
eq("メモリ32GB以上", [r["row_key"] for r in find_rows(conn, "メモリ", ">=", 32.0)],
   ["MN-Book15"])
eq("定員10名以上", [r["row_key"] for r in find_rows(conn, "定員", ">=", 10.0)],
   ["大会議室", "みなと"])
eq("保管期間36か月以上", [r["row_key"] for r in find_rows(conn, "保管期間", ">=", 36.0)],
   ["契約書", "稟議書", "個人情報を含む名簿"])
eq("定額の手当の合計", sum_of(conn, "月額"), 69000.0)
eq("上限も足した場合", sum_of(conn, "月額", ("定額", "上限")), 99000.0)
try:
    find_rows(conn, "月額", "; DROP TABLE cells --", 0.0)
    check("許可していない演算子は拒否する", False, "例外が出なかった")
except ValueError:
    check("許可していない演算子は拒否する", True)

# --- 7. 数値条件が語彙一致で解けない理由 --------------------------------------
print("\n--- 7. 語彙一致では解けない理由 ---")
man = [d for d in docs if "3万円" in d.full_text]
eq("「3万円」を含む文書", len(man), 6)
check("その6件はすべて備品の購入申請（手当とは無関係）",
      {d.theme for d in man} == {"supplies"}, f"{sorted({d.theme for d in man})}")
yen40 = [d for d in docs if "40,000円" in d.full_text]
eq("「40,000円」を含む文書は1件", [d.doc_id for d in yen40], ["DOC-0094"])
eq("その文書に「3万円」は出てこない", "3万円" in by_id["DOC-0094"].full_text, False)

# --- 8. コード検索 ------------------------------------------------------------
print("\n--- 8. コード検索 ---")
units = [u for d in docs for u in code_units(d)]
eq("コード単位の ID と関数名",
   [(u.unit_id, u.name) for u in units],
   [("DOC-0111#C11", "find_asset"), ("DOC-0283#C11", "build_incident_report")])
eq("split_identifier(find_asset)", split_identifier("find_asset"), ["find", "asset"])
eq("split_identifier(buildIncidentReport)", split_identifier("buildIncidentReport"),
   ["build", "incident", "report"])
eq("split_identifier(HTTPServer)", split_identifier("HTTPServer"), ["http", "server"])

line = "def find_asset(asset_tag: str) -> dict | None:"
eq("識別子のみ", identifiers(line), ["find_asset", "asset_tag"])
eq("索引に載せる語", code_tokens(line),
   ["find_asset", "find", "asset", "asset_tag", "asset", "tag"])

morph_terms = set(tokenize("\n".join(u.text for u in units), "morph"))
check("識別子そのもの（find_asset）は形態素索引の語にならない",
      "find_asset" not in morph_terms)
# 「記号やアンダースコアは形態素解析が落としてくれる」は成り立たない（実測）。
# 落ちる／残るを仕様から推測せず、実際の出力で固定する。
check("アンダースコアを含む語は形態素索引に残る（落ちてはくれない）",
      any("_" in t for t in morph_terms),
      f"例 {sorted(t for t in morph_terms if '_' in t)[:3]}")
eq("記号だけのクエリでも語は残る（janome の実測）", tokenize("==", "morph"), ["=="])

eq("完全一致「find_asset」", [u.name for _, u in search_code(units, "find_asset")],
   ["find_asset"])
eq("部分語「asset」", [u.name for _, u in search_code(units, "asset")], ["find_asset"])
eq("部分語「report」", [u.name for _, u in search_code(units, "report")],
   ["build_incident_report"])
eq("呼び方が違う「buildIncidentReport」",
   [u.name for _, u in search_code(units, "buildIncidentReport")], ["build_incident_report"])
eq("記号は逐次一致で探す「==」", [u.name for u in literal_search(units, "==")],
   ["find_asset"])

# --- 9. 型別パイプライン ------------------------------------------------------
print("\n--- 9. 型別パイプライン ---")
blocks = [b for d in docs for b in split_blocks(d)]
kinds = {k: sum(1 for b in blocks if b.kind == k) for k in ("text", "table", "code")}
eq("表ブロック", kinds["table"], 40)
eq("コードブロック", kinds["code"], 2)
check("本文ブロックが最も多い", kinds["text"] > kinds["table"] + kinds["code"],
      f"text={kinds['text']}")
# 表とコードを挟んだ文書は本文が前後に分かれるので、文書数（301）より多くなる
eq("本文ブロック", kinds["text"], 337)

ing = [ingest(d) for d in docs]
eq("取り込み後の行チャンク", sum(len(i.row_chunks) for i in ing), 197)
eq("取り込み後のコード単位", sum(len(i.code_units) for i in ing), 2)
check("表とコードを抜いてもテキストチャンクは残る",
      sum(len(i.text_chunks) for i in ing) > 500,
      f"{sum(len(i.text_chunks) for i in ing)} 個")

ROUTES = [
    ("月額が3万円以上の手当は", "structured"),
    ("セキュリティの文書は何件ありますか", "structured"),
    ("find_asset は何をする関数ですか", "code"),
    ("役職手当の月額はいくらですか", "row"),
    ("有給休暇の申請期限を教えてください", "text"),
]
for q, want in ROUTES:
    eq(f"ルーティング「{q}」", route(q), want)

# --- 10. 練習問題の解答が引用する派生値 ----------------------------------------
print("\n--- 10. 練習問題の解答が引用する派生値 ---")
by_col: dict[str, list[str]] = {}
for doc in docs:
    for t in parse_tables(doc):
        for row in t.rows:
            for col, value in zip(t.columns, row):
                by_col.setdefault(col, []).append(value)
eq("セルを持つ列の種類", len(by_col), 17)
eq("「確認項目」列の異なり数", len(set(by_col["確認項目"])), 43)
eq("「判断の目安」列の異なり数", len(set(by_col["判断の目安"])), 39)
# 列の型を宣言するかどうかの判定に使う「単位付きの数値」の割合（練習問題5）
_UNIT = re.compile(r"^\D*?(\d[\d,]*)\s*(円|GB|名|時間|年|か月)")
eq("「判断の目安」で単位付きの数値になるセル",
   sum(1 for v in by_col["判断の目安"] if _UNIT.match(v)), 9)
# 文書タイトルと見出しの前置を外すと、行文章は一意でなくなる（練習問題3）
eq("前置を外した行文章の異なり数", len({c.text.split("：", 1)[1] for c in rows}), 62)

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション15の検証はすべて成功しました。")
