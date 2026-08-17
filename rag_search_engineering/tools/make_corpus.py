#!/usr/bin/env python3
"""架空企業「みなと商事」の社内ヘルプデスク文書コーパスを生成する。

固定シード・固定基準日で動くため、何度実行しても同じ結果になる（決定的）。
後半セッションの演習が成立するよう、次の構造を意図的に埋め込んでいる。

  - 表記ゆれ・略語（S05・S10）：文書には正式名称だけを書き、略語はクエリ側にのみ出す
  - 時点性（S13・S16）：同一テーマで旧版と新版の規程を併存させる
  - 権限（S13）：visibility=manager の文書に一般社員に見せない情報を入れる
  - マルチホップ（S14）：文書Aが文書Bを参照し、両方読まないと答えられない質問を作る
  - 表（S15）：Markdown の表を含む文書
  - コード（S15）：Python コードを含む文書
  - 回答不能（S11・S12）：コーパスに答えが無いクエリ

出力:
  corpus/docs.jsonl      文書
  corpus/queries.jsonl   クエリ
  corpus/qrels.jsonl     判定データ（生成器が持つ真の対応から機械的に導出）
  corpus/query_log.jsonl 合成クエリログ（S17 用）
"""

from __future__ import annotations

import json
import random
from pathlib import Path

SEED = 20260815
BASE_DATE = "2026-08-15"  # 基準日（相対日付を使わない）
OUT = Path(__file__).resolve().parent.parent / "corpus"

# ---------------------------------------------------------------------------
# テーマ定義（36件）。terms は文書に出す正式名称、syn はクエリ側にだけ出す略語
# ---------------------------------------------------------------------------
THEMES: list[dict] = [
    # 勤怠
    dict(key="paid_leave", cat="勤怠", name="有給休暇の申請", terms=["有給休暇", "勤怠システム"],
         syn=["年休", "有休"], label="申請期限", fact="取得予定日の3営業日前", who="全社員", window="総務部"),
    dict(key="late_notice", cat="勤怠", name="遅刻・早退の届出", terms=["遅刻", "早退", "届出"],
         syn=[], label="連絡先", fact="始業30分前までに所属長へチャットで連絡", who="全社員", window="所属長"),
    dict(key="overtime", cat="勤怠", name="時間外労働の事前申請", terms=["時間外労働", "事前申請"],
         syn=["残業"], label="上限時間", fact="月45時間", who="全社員", window="所属長"),
    dict(key="compensatory", cat="勤怠", name="代休の取得", terms=["代休", "休日出勤"],
         syn=[], label="取得期限", fact="休日出勤日から2か月以内", who="全社員", window="総務部"),
    dict(key="punch_fix", cat="勤怠", name="打刻漏れの修正", terms=["打刻漏れ", "修正申請"],
         syn=[], label="締切", fact="当月末日", who="全社員", window="所属長"),
    dict(key="childcare", cat="勤怠", name="育児休業の申請", terms=["育児休業", "申出書"],
         syn=["育休"], label="申出期限", fact="開始予定日の1か月前", who="全社員", window="人事部"),
    # 経費
    dict(key="commute", cat="経費", name="通勤交通費の精算", terms=["通勤交通費", "精算"],
         syn=["定期代"], label="提出期限", fact="毎月5日", who="全社員", window="経理部"),
    dict(key="travel", cat="経費", name="出張旅費の精算", terms=["出張旅費", "精算書"],
         syn=[], label="提出期限", fact="帰着日から10日以内", who="全社員", window="経理部"),
    dict(key="entertain", cat="経費", name="接待交際費の申請", terms=["接待交際費", "事前承認"],
         syn=[], label="事前承認の基準", fact="1件5万円以上", who="管理職", window="経理部"),
    dict(key="supplies", cat="経費", name="備品の購入申請", terms=["備品", "購入申請"],
         syn=[], label="決裁区分", fact="3万円未満は所属長決裁", who="全社員", window="総務部"),
    dict(key="advance", cat="経費", name="立替金の返金", terms=["立替金", "返金"],
         syn=[], label="振込日", fact="申請月の翌月25日", who="全社員", window="経理部"),
    dict(key="allowance", cat="経費", name="各種手当の支給", terms=["手当", "支給"],
         syn=[], label="金額表", fact="下表のとおり", who="全社員", window="人事部", table="allowance"),
    # PC・端末
    dict(key="pc_setup", cat="PC・端末", name="貸与PCの初期設定", terms=["貸与PC", "初期設定"],
         syn=["パソコン"], label="所要時間", fact="約60分", who="入社者", window="情報システム部"),
    dict(key="pc_broken", cat="PC・端末", name="PCの故障対応", terms=["PC", "故障", "修理"],
         syn=[], label="代替機の貸出", fact="申請当日", who="全社員", window="情報システム部", code=True),
    dict(key="software", cat="PC・端末", name="ソフトウェアのインストール申請",
         terms=["ソフトウェア", "インストール申請"], syn=[], label="審査期間", fact="申請から3営業日",
         who="全社員", window="情報システム部"),
    dict(key="peripheral", cat="PC・端末", name="周辺機器の貸出", terms=["周辺機器", "貸出"],
         syn=[], label="貸出期間", fact="最長3か月", who="全社員", window="情報システム部", table="pc"),
    dict(key="pc_return", cat="PC・端末", name="PCの返却", terms=["PC", "返却", "データ消去"],
         syn=[], label="返却期限", fact="最終出社日の前日", who="退職者", window="情報システム部"),
    dict(key="mobile", cat="PC・端末", name="貸与スマートフォンの利用", terms=["貸与スマートフォン", "利用規則"],
         syn=["スマホ", "携帯"], label="通信費の上限", fact="月5,000円", who="対象者", window="情報システム部"),
    # アカウント
    dict(key="acct_new", cat="アカウント", name="入社時のアカウント発行", terms=["アカウント発行", "入社"],
         syn=[], label="発行日", fact="入社日の前営業日", who="入社者", window="情報システム部"),
    dict(key="pw_reset", cat="アカウント", name="パスワードの再設定", terms=["パスワード", "再設定"],
         syn=["パス", "PW"], label="ロック解除の待ち時間", fact="30分", who="全社員", window="情報システム部"),
    dict(key="mfa", cat="アカウント", name="多要素認証の登録", terms=["多要素認証", "認証アプリ"],
         syn=["MFA", "二要素認証", "2段階認証"], label="登録期限", fact="アカウント発行から5営業日以内",
         who="全社員", window="情報システム部"),
    dict(key="perm_change", cat="アカウント", name="権限変更の申請", terms=["権限変更", "申請"],
         syn=[], label="承認者", fact="所属長と情報システム部の二者承認", who="全社員", window="情報システム部"),
    dict(key="acct_stop", cat="アカウント", name="退職時のアカウント停止", terms=["アカウント停止", "退職"],
         syn=[], label="停止時刻", fact="最終出社日の18時", who="退職者", window="情報システム部"),
    dict(key="shared_acct", cat="アカウント", name="共有アカウントの取り扱い", terms=["共有アカウント", "管理台帳"],
         syn=[], label="棚卸頻度", fact="四半期ごと", who="管理者", window="情報システム部"),
    # オフィス
    dict(key="meeting_room", cat="オフィス", name="会議室の予約", terms=["会議室", "予約"],
         syn=[], label="連続利用の上限", fact="4時間", who="全社員", window="総務部", table="room"),
    dict(key="entry_card", cat="オフィス", name="入退館カードの発行", terms=["入退館カード", "発行"],
         syn=["社員証"], label="紛失時の対応", fact="即日停止のうえ再発行手数料1,000円", who="全社員", window="総務部"),
    dict(key="free_address", cat="オフィス", name="座席の利用ルール", terms=["座席", "利用ルール"],
         syn=["フリーアドレス"], label="私物の放置", fact="退勤時に持ち帰る", who="全社員", window="総務部"),
    dict(key="mail", cat="オフィス", name="郵便物の受け取り", terms=["郵便物", "受け取り"],
         syn=[], label="集配時刻", fact="平日15時", who="全社員", window="総務部"),
    dict(key="parking", cat="オフィス", name="駐車場の利用", terms=["駐車場", "利用申請"],
         syn=[], label="月額利用料", fact="8,000円", who="対象者", window="総務部"),
    dict(key="shared_goods", cat="オフィス", name="共用備品の利用", terms=["共用備品", "持ち出し"],
         syn=[], label="持ち出しの記録", fact="貸出簿への記入", who="全社員", window="総務部"),
    # セキュリティ
    dict(key="data_out", cat="セキュリティ", name="情報の持ち出し", terms=["情報", "持ち出し", "申請"],
         syn=[], label="申請の要否", fact="社外持ち出しは常に申請が必要", who="全社員", window="情報セキュリティ室"),
    dict(key="phishing", cat="セキュリティ", name="標的型メールの報告", terms=["標的型メール", "報告"],
         syn=["フィッシング", "不審メール"], label="報告先", fact="情報セキュリティ室の専用アドレス",
         who="全社員", window="情報セキュリティ室"),
    dict(key="usb", cat="セキュリティ", name="USBメモリの利用", terms=["USBメモリ", "利用申請"],
         syn=[], label="許可される機器", fact="会社が貸与した暗号化機器のみ", who="全社員", window="情報セキュリティ室"),
    dict(key="saas", cat="セキュリティ", name="外部サービスの利用申請", terms=["外部サービス", "利用申請"],
         syn=["SaaS", "クラウドサービス"], label="審査期間", fact="申請から10営業日",
         who="全社員", window="情報セキュリティ室"),
    dict(key="incident", cat="セキュリティ", name="セキュリティ事故の報告", terms=["セキュリティ事故", "初動報告"],
         syn=["インシデント"], label="報告期限", fact="発見から1時間以内", who="全社員", window="情報セキュリティ室",
         code=True),
    dict(key="dispose", cat="セキュリティ", name="機密文書の廃棄", terms=["機密文書", "廃棄"],
         syn=[], label="保管期間", fact="下表のとおり", who="全社員", window="情報セキュリティ室", table="retention"),
]

# 時点性（旧版・新版を併存させる）テーマ
TEMPORAL_KEYS = ["paid_leave", "overtime", "travel", "mfa", "meeting_room", "saas"]
OLD_FACTS = {
    "paid_leave": "取得予定日の前日",
    "overtime": "月60時間",
    "travel": "帰着日から30日以内",
    "mfa": "任意",
    "meeting_room": "8時間",
    "saas": "申請から5営業日",
}
# 管理職限定の文書を持つテーマ
MANAGER_KEYS = ["entertain", "perm_change", "incident", "overtime"]
# マルチホップ（参照する側 → 参照される側）
MULTIHOP = [("data_out", "usb"), ("saas", "incident"), ("pc_return", "acct_stop")]

TABLES = {
    "allowance": """| 手当の種類 | 対象者 | 月額 |
| :--- | :--- | :--- |
| 通勤手当 | 全社員 | 実費（上限30,000円） |
| 住宅手当 | 世帯主 | 15,000円 |
| 資格手当 | 対象資格の保有者 | 10,000円 |
| 役職手当 | 課長以上 | 40,000円 |
| 在宅勤務手当 | 在宅勤務者 | 4,000円 |""",
    "pc": """| 機種名 | 用途 | メモリ | 貸出期間 |
| :--- | :--- | :--- | :--- |
| MN-Book13 | 標準業務 | 16GB | 3年 |
| MN-Book15 | 開発業務 | 32GB | 3年 |
| MN-Tab10 | 現場確認 | 8GB | 1年 |
| 外付けモニタ MN-D24 | 常時利用 | — | 最長3か月 |""",
    "room": """| 会議室 | 定員 | 設備 | 連続利用の上限 |
| :--- | :--- | :--- | :--- |
| みなと | 12名 | プロジェクタ・電話会議 | 4時間 |
| うみかぜ | 6名 | モニタ | 4時間 |
| ふ頭 | 4名 | なし | 2時間 |
| 大会議室 | 40名 | 音響・配信設備 | 8時間 |""",
    "retention": """| 文書の種類 | 保管期間 | 廃棄方法 |
| :--- | :--- | :--- |
| 契約書 | 10年 | 溶解処理 |
| 稟議書 | 7年 | 溶解処理 |
| 個人情報を含む名簿 | 3年 | 溶解処理（記録を残す） |
| 会議メモ | 1年 | シュレッダー |""",
}

CODE_SNIPPETS = {
    "pc_broken": '''```python
# 資産管理台帳から貸与PCの状態を引く社内スクリプト
def find_asset(asset_tag: str) -> dict | None:
    for row in load_asset_ledger():
        if row["asset_tag"] == asset_tag:
            return row
    return None
```''',
    "incident": '''```python
# 初動報告の雛形を生成する社内スクリプト
def build_incident_report(reporter: str, detected_at: str, summary: str) -> str:
    return f"報告者: {reporter}\\n検知時刻: {detected_at}\\n概要: {summary}"
```''',
}


# 文書に厚みを持たせるための文の候補（seed 固定で選ぶ。文書ごとに差を作る）
PREP_POOL = [
    "申請の前に、社内ポータルの掲示板で最新の運用連絡を確認してください。",
    "前月分の未処理案件が残っている場合は、先にそちらを完了させてください。",
    "対象となる期間と金額をあらかじめ整理しておくと入力がスムーズです。",
    "所属長が不在の場合は、代理承認者をあらかじめ確認しておいてください。",
    "添付書類は PDF 形式で用意し、ファイル名に日付を含めてください。",
]
NOTE_POOL = [
    "申請内容に不備がある場合は差し戻しとなり、再申請から審査期間が再計算されます。",
    "締切を過ぎた申請は翌月分としての取り扱いになります。",
    "代理での申請は認められません。本人のアカウントから手続きしてください。",
    "個人情報を含む書類を添付する場合は、必要最小限の範囲に限ってください。",
    "運用が変更された場合は社内ポータルで周知します。過去の手順書は参照しないでください。",
]
EXAMPLE_POOL = [
    "記入例：申請区分は「新規」、備考欄には対象期間と概算金額を記載します。",
    "記入例：件名は「{name}（YYYY年MM月分）」の形式で入力します。",
    "記入例：添付欄には根拠資料を1件ずつ分けて登録します。",
]
BACKGROUND_POOL = [
    "近年の問い合わせ件数の増加を受け、手続きの標準化を進めています。",
    "監査での指摘を踏まえ、記録の残し方を明確にしました。",
    "在宅勤務の定着に伴い、電子申請を原則とする運用に切り替えています。",
]


def make_docs(rng: random.Random) -> list[dict]:
    docs: list[dict] = []
    n = 0

    def add(theme: dict, source_type: str, title: str, body: str, *,
            visibility: str = "all", updated_at: str = "2026-06-01", grade_hint: int = 2) -> None:
        nonlocal n
        n += 1
        docs.append(dict(
            doc_id=f"DOC-{n:04d}", title=title, body=body, category=theme["cat"],
            updated_at=updated_at, visibility=visibility,
            dept=theme["window"], source_type=source_type, theme=theme["key"],
            _grade=grade_hint,
        ))

    for theme in THEMES:
        t0 = theme["terms"][0]
        t1 = theme["terms"][1] if len(theme["terms"]) > 1 else t0
        who, window, label, fact = theme["who"], theme["window"], theme["label"], theme["fact"]
        table = TABLES.get(theme.get("table", ""), "")
        code = CODE_SNIPPETS.get(theme["key"], "") if theme.get("code") else ""

        # 手順書（2件）— 見出しを持つので chunk_heading が効く
        for i in (1, 2):
            steps = "\n".join(f"{j}. {s}" for j, s in enumerate([
                f"社内ポータルのメニューから「{theme['name']}」の申請フォームを開きます。",
                f"申請区分を選択し、{t1}に関する必要事項を入力します。",
                f"添付書類をアップロードし、宛先に{window}を指定します。",
                "内容を確認して所属長へ回付し、承認を待ちます。",
                f"承認後、{window}が内容を確認して受付処理を行います。",
                f"受付が完了すると、申請者と所属長の双方に{window}から完了通知が届きます。",
            ][: 5 + i], start=1))
            body = (
                f"## 対象者\n{who}が対象です。{t0}に関する手続きは本手順書に従ってください。"
                f"対象かどうか判断できない場合は、申請前に{window}へ確認してください。\n\n"
                f"## 事前準備\n{rng.choice(PREP_POOL)}{rng.choice(PREP_POOL)}"
                f"{rng.choice(PREP_POOL)}\n\n"
                f"## 手順\n{steps}\n\n"
                f"## {label}\n{t0}の{label}は{fact}です。"
                f"{label}は年度によって見直されることがあるため、申請の都度この手順書の最新版を確認してください。"
                f"{label}を過ぎた場合は{window}へ個別に相談し、事情を記録に残したうえで処理します。\n\n"
                f"## 記入例\n{rng.choice(EXAMPLE_POOL).format(name=theme['name'])}"
                f"入力内容は保存後も承認前であれば修正できます。\n\n"
                f"## 差し戻しになりやすい例\n"
                f"添付書類の解像度が不足している場合、{t1}に関する記載が空欄の場合、"
                f"承認経路に所属長が含まれていない場合は差し戻しになります。\n\n"
                f"## 注意事項\n{rng.choice(NOTE_POOL)}{rng.choice(NOTE_POOL)}"
                f"{rng.choice(NOTE_POOL)}\n\n"
                f"## 関連文書\n{theme['name']}規程、{theme['name']}チェックリスト、"
                f"および{window}が発行する運用連絡を併せて確認してください。\n"
            )
            if table and i == 1:
                body += f"\n## 一覧\n{table}\n"
            if code and i == 2:
                body += f"\n## 参考スクリプト\n{code}\n"
            add(theme, "procedure", f"{theme['name']}手順書（第{i}版）", body,
                updated_at=f"2026-0{2 + i}-01")

        # チェックリスト（1件）— 表を含むため S15 の題材にもなる
        add(theme, "procedure", f"{theme['name']}チェックリスト",
            f"## 使い方\n{theme['name']}の申請前に、以下の項目をすべて確認してください。"
            f"1つでも「いいえ」がある場合は申請せず、{window}へ相談してください。\n\n"
            f"## 確認項目\n"
            f"| # | 確認項目 | 判断の目安 |\n| :-- | :--- | :--- |\n"
            f"| 1 | 自分が{who}に該当するか | 該当しない場合は申請不可 |\n"
            f"| 2 | {label}を満たしているか | {fact} |\n"
            f"| 3 | 添付書類がそろっているか | PDF形式・日付入りのファイル名 |\n"
            f"| 4 | 承認経路に所属長が含まれているか | 代理承認者でも可 |\n"
            f"| 5 | 過去の同一申請が完了しているか | 未処理があれば先に完了させる |\n\n"
            f"## 提出後の流れ\n{window}が受付し、内容に不備がなければ完了通知が届きます。"
            f"不備がある場合は差し戻され、修正後に再申請が必要です。\n\n"
            f"## 相談先\n{window}\n",
            updated_at="2026-05-20", grade_hint=1)

        # FAQ（3件）
        qa_pool = [
            f"### Q. {t0}の{label}はいつですか\nA. {fact}です。{label}は運用連絡で変更される場合があるため、"
            f"申請の都度確認してください。",
            f"### Q. {t0}の窓口はどこですか\nA. {window}です。問い合わせは社内ポータルの問い合わせフォームから"
            f"お願いします。電話での問い合わせは記録が残らないため受け付けていません。",
            f"### Q. {who}以外も対象になりますか\nA. 対象は{who}です。個別の事情がある場合は{window}へ"
            f"相談してください。例外が認められた場合も記録は必要です。",
            f"### Q. 申請を取り消したい場合はどうしますか\nA. 承認前であれば申請者自身で取り下げできます。"
            f"承認後は{window}へ連絡してください。取り下げの理由は記録されます。",
            f"### Q. 承認が進まない場合はどうすればよいですか\nA. まず所属長へ直接確認してください。"
            f"3営業日以上動きがない場合は{window}へ連絡すると、代理承認の手配を行います。",
            f"### Q. {t1}の記録はどこで確認できますか\nA. 社内ポータルの申請履歴から確認できます。"
            f"過去2年分を保持しており、それより前の記録は{window}へ依頼して取り寄せます。",
            f"### Q. 申請内容を間違えて提出しました\nA. 承認前なら取り下げて再申請してください。"
            f"承認後に誤りが判明した場合は、速やかに{window}へ連絡し訂正の手続きを取ります。",
        ]
        for i in (1, 2, 3):
            picked = qa_pool[i - 1 : i - 1 + 4] if i < 3 else qa_pool[3:]
            add(theme, "faq", f"{theme['name']}に関するよくある質問（{i}）",
                f"## よくある質問\n{theme['name']}について、{window}に問い合わせの多い項目をまとめました。"
                f"手順の全体像は{theme['name']}手順書を参照してください。\n\n"
                + "\n\n".join(picked)
                + f"\n\n## 解決しない場合\n上記で解決しない場合は{window}へ問い合わせてください。"
                f"問い合わせの際は、申請番号と発生日時を添えてください。\n",
                updated_at="2026-05-10", grade_hint=1 if i == 1 else 0)

        # 規程（1件）。時点性テーマは旧版も作る
        policy_body = (
            f"## 目的\n本規程は、{theme['name']}に関する手続と責任の所在を定め、"
            f"業務の適正な遂行を確保することを目的とする。\n\n"
            f"## 適用範囲\n本規程は{who}に適用する。{t1}を伴う業務はすべて本規程の対象とする。\n\n"
            f"## 定義\n本規程において「{t0}」とは、{theme['name']}に係る一連の手続をいう。\n\n"
            f"## 原則\n{t0}は事前申請を原則とし、承認を得てから実施しなければならない。"
            f"承認を得ずに実施した場合は、事後の承認をもって有効とすることはできない。\n\n"
            f"## {label}\n{label}は{fact}とする。"
            f"{label}の算定にあたっては、社休日を含めない。\n\n"
            f"## 申請の経路\n申請者は所属長の承認を得たうえで{window}へ提出する。"
            f"所属長が申請者本人である場合は、上位の管理者の承認を得る。\n\n"
            f"## 例外\nやむを得ない事由により{label}を満たせない場合は、事後速やかに{window}へ届け出る。"
            f"届出の内容は{window}が審査し、認められない場合は当該手続を無効とする。\n\n"
            f"## 記録\n申請および承認の記録は電子的に保管し、監査の求めに応じて提示する。"
            f"保管期間は3年とし、期間経過後は所定の方法で廃棄する。\n\n"
            f"## 所管および改廃\n本規程は{window}が所管し、改廃は{window}長の決裁により行う。\n"
        )
        if theme["key"] in TEMPORAL_KEYS:
            add(theme, "policy", f"{theme['name']}規程（2026年度版）", policy_body,
                updated_at="2026-04-01", grade_hint=2)
            old = policy_body.replace(fact, OLD_FACTS[theme["key"]])
            add(theme, "policy", f"{theme['name']}規程（2023年度版・旧規程）",
                f"{old}\n## 注記\n本規程は2026年度版の施行に伴い失効している。\n",
                updated_at="2023-04-01", grade_hint=0)
        else:
            add(theme, "policy", f"{theme['name']}規程", policy_body, updated_at="2026-04-01")

        # お知らせ（1件）
        add(theme, "notice", f"【お知らせ】{theme['name']}の運用変更について",
            f"## 背景\n{rng.choice(BACKGROUND_POOL)}\n\n"
            f"## 変更内容\n{BASE_DATE}より、{theme['name']}の運用を一部変更します。"
            f"申請フォームの項目名を整理し、添付書類の形式を PDF に統一します。"
            f"また、承認状況の通知をチャットにも配信するようにします。\n\n"
            f"## 変更しない点\n{label}は{fact}のまま変更ありません。"
            f"承認の経路も従来どおり所属長経由です。対象者の範囲（{who}）も変わりません。\n\n"
            f"## 影響\n変更日より前に提出済みの申請は、従来の運用で処理します。"
            f"変更日以降に差し戻された申請は、新しいフォームで再提出してください。\n\n"
            f"## 準備のお願い\n添付書類を紙で保管している場合は、事前に電子化しておいてください。\n\n"
            f"## 問い合わせ\n{window}へお問い合わせください。\n",
            updated_at=BASE_DATE, grade_hint=0)

        # 管理職限定（該当テーマのみ）
        if theme["key"] in MANAGER_KEYS:
            add(theme, "policy", f"{theme['name']}の運用細則（管理職限定）",
                f"## 取扱区分\n本文書は管理職限定であり、部下および他部門へ共有してはならない。\n\n"
                f"## 例外承認の基準\n{window}長の判断により、{label}（{fact}）を超える取り扱いを"
                f"認める場合がある。認定の可否は個別事情と過去の申請状況を踏まえて判断する。\n\n"
                f"## 記録の取り扱い\n例外承認の記録は、当該社員の人事評価の参考情報として3年間保管する。\n\n"
                f"## 開示の制限\n本細則の内容および例外承認の有無は、対象社員本人へ開示しない。\n",
                visibility="manager", updated_at="2026-04-01", grade_hint=0)

    # マルチホップ（参照する側の文書に、参照先の表題だけを書く）
    for src_key, dst_key in MULTIHOP:
        src = next(t for t in THEMES if t["key"] == src_key)
        dst = next(t for t in THEMES if t["key"] == dst_key)
        add(src, "policy", f"{src['name']}に関する補則",
            f"## 趣旨\n本補則は、{src['name']}を実施する際の追加条件を定める。\n\n"
            f"## 参照\n{src['name']}のうち電子媒体または外部サービスを用いる場合の条件は、"
            f"本補則では定めず、別に定める「{dst['name']}規程」に従う。\n\n"
            f"## 手続\n{src['window']}へ申請したうえで、{dst['window']}の確認を受ける。"
            f"両方の要件を満たさない申請は受理しない。\n\n"
            f"## 責任\n条件の適合性の確認は申請者の責任とする。\n",
            updated_at="2026-04-01", grade_hint=1)

    return docs


def make_queries_and_qrels(docs: list[dict], rng: random.Random) -> tuple[list[dict], list[dict]]:
    by_theme: dict[str, list[dict]] = {}
    for d in docs:
        by_theme.setdefault(d["theme"], []).append(d)

    queries: list[dict] = []
    qrels: list[dict] = []
    qid = 0

    def add(text: str, qtype: str, rel: dict[str, int]) -> None:
        nonlocal qid
        qid += 1
        query_id = f"Q-{qid:03d}"
        queries.append(dict(query_id=query_id, text=text, type=qtype))
        for doc_id, grade in rel.items():
            qrels.append(dict(query_id=query_id, doc_id=doc_id, grade=grade))

    def rel_of(theme_key: str, *, exclude_old: bool = False, only_new: bool = False) -> dict[str, int]:
        out: dict[str, int] = {}
        for d in by_theme[theme_key]:
            grade = d["_grade"]
            if only_new and d["source_type"] == "policy" and "旧規程" in d["title"]:
                grade = 0
            if exclude_old and "旧規程" in d["title"]:
                continue
            if grade > 0:
                out[d["doc_id"]] = grade
        return out

    # 自然文（全テーマ）
    for t in THEMES:
        add(f"{t['terms'][0]}の{t['label']}を教えてください", "natural", rel_of(t["key"]))

    # キーワード（前半30テーマ）
    for t in THEMES[:30]:
        add(" ".join(t["terms"][:2] + [t["label"]]), "keyword", rel_of(t["key"]))

    # 略語（syn を持つテーマ。文書側には正式名称しか無いので語彙一致では引けない）
    #   あえて label を含めない汎用的な言い回しにする。label（例「上限時間」）は
    #   テーマ固有語として効いてしまい、略語の問題が見えなくなるため。
    for t in THEMES:
        for syn in t["syn"]:
            add(f"{syn}の手続きを知りたい", "abbrev", rel_of(t["key"]))

    # 複数条件（2テーマにまたがる）
    pairs = [("paid_leave", "compensatory"), ("travel", "advance"), ("pc_setup", "acct_new"),
             ("mfa", "pw_reset"), ("data_out", "usb"), ("saas", "incident"),
             ("meeting_room", "entry_card"), ("overtime", "late_notice"),
             ("supplies", "peripheral"), ("dispose", "data_out"),
             ("pc_return", "acct_stop"), ("commute", "parking")]
    for a, b in pairs:
        ta = next(t for t in THEMES if t["key"] == a)
        tb = next(t for t in THEMES if t["key"] == b)
        rel = {**rel_of(a), **rel_of(b)}
        add(f"{ta['terms'][0]}と{tb['terms'][0]}の手続きの違いを知りたい", "multi_condition", rel)

    # 時点性（現在有効な版だけが適合）
    for key in TEMPORAL_KEYS:
        t = next(x for x in THEMES if x["key"] == key)
        add(f"現在有効な{t['terms'][0]}の規程の{t['label']}は", "temporal", rel_of(key, only_new=True))
    for key in TEMPORAL_KEYS:
        t = next(x for x in THEMES if x["key"] == key)
        add(f"{t['terms'][0]}の{t['label']}は最新の規程では何と定められているか", "temporal",
            rel_of(key, only_new=True))

    # 回答不能（コーパスに答えが無い）
    for text in ["社員食堂の今週のメニューを教えてください",
                 "駐輪場の利用申請はどこに出しますか",
                 "健康診断の予約方法を教えてください",
                 "社内表彰制度の応募条件は何ですか",
                 "confluence の管理者は誰ですか",
                 "海外赴任時の住居手当はいくらですか",
                 "社宅の空室状況を知りたい",
                 "副業の届出は必要ですか",
                 "退職金の計算方法を教えてください",
                 "インフルエンザ予防接種の補助はありますか"]:
        add(text, "unanswerable", {})

    return queries, qrels


def make_query_log(queries: list[dict], rng: random.Random) -> list[dict]:
    """S17 用の合成クエリログ。頻出クエリとロングテールを作り分ける。"""
    log: list[dict] = []
    hour = 9
    for i, q in enumerate(queries):
        # 頻度は Zipf 的に偏らせる（先頭のクエリほど多く引かれる）
        count = max(1, int(60 / (i + 1)) + (3 if q["type"] == "natural" else 0))
        for j in range(count):
            zero_hit = q["type"] == "unanswerable" and j % 2 == 0
            log.append(dict(
                ts=f"2026-08-{(i % 28) + 1:02d}T{(hour + j) % 24:02d}:{(j * 7) % 60:02d}:00+09:00",
                query_id=q["query_id"], text=q["text"], query_type=q["type"],
                n_results=0 if zero_hit else rng.randint(3, 20),
                top_score=0.0 if zero_hit else round(rng.uniform(0.4, 0.9), 3),
                latency_ms=rng.randint(30, 480),
                clicked_rank=None if zero_hit or rng.random() < 0.35 else rng.randint(1, 5),
                user_role="manager" if i % 9 == 0 else "member",
            ))
    return log


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    rng = random.Random(SEED)
    docs = make_docs(rng)
    queries, qrels = make_queries_and_qrels(docs, rng)
    log = make_query_log(queries, rng)

    # _grade は判定データの導出にだけ使う内部フィールドなので書き出さない
    public_docs = [{k: v for k, v in d.items() if not k.startswith("_")} for d in docs]

    write_jsonl(OUT / "docs.jsonl", public_docs)
    write_jsonl(OUT / "queries.jsonl", queries)
    write_jsonl(OUT / "qrels.jsonl", qrels)
    write_jsonl(OUT / "query_log.jsonl", log)

    total_chars = sum(len(d["title"]) + len(d["body"]) for d in public_docs)
    answerable = len({r["query_id"] for r in qrels if r["grade"] >= 1})
    print(f"docs={len(public_docs)} chars={total_chars} "
          f"queries={len(queries)} (answerable={answerable}) "
          f"qrels={len(qrels)} log={len(log)}")


if __name__ == "__main__":
    main()
