"""横断復習2 問題7 ― 社内お知らせ掲示板（Python 版データ層）

node/src/review02/board.ts と同じデータ・同じ Markdown になるように書いています。
プロトコルに出る値（タイトル・本文・分類・掲載日）は 1 文字も変えていません。
移植の合格条件は「resources/read の本文が完全一致すること」です。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote

#: URI に載るスラッグの許可リスト
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")

MAX_LIMIT = 20
DEFAULT_LIMIT = 5

CATEGORY_LABELS = {
    "facility": "設備",
    "general": "総務",
    "hr": "人事",
    "it": "情報システム",
}
CATEGORY_CODES = ["all", "facility", "general", "hr", "it"]


@dataclass(frozen=True, slots=True)
class Notice:
    slug: str
    title: str
    category: str
    published_on: str
    body: str


#: スラッグ昇順で持つ（補完候補と検索結果の順序が安定する）
NOTICES: list[Notice] = [
    Notice(
        "badge-renewal",
        "入館証の更新手続きについて",
        "general",
        "2026-07-06",
        "入館証の有効期限が 2026 年 9 月末で切れます。\n"
        "更新は総務ポータルから申請してください。写真の再提出は不要です。\n"
        "新しい入館証は 9 月 15 日から順次配布します。",
    ),
    Notice(
        "desk-move",
        "7 月の座席移動のお知らせ",
        "facility",
        "2026-07-13",
        "7 月 21 日に 3 階と 4 階の座席を入れ替えます。\n"
        "私物は前日までに各自のロッカーへ移してください。\n"
        "当日はネットワークの再配線を行うため、有線接続は使えません。",
    ),
    Notice(
        "expense-deadline",
        "経費精算の締切変更",
        "general",
        "2026-07-21",
        "8 月分の経費精算の締切を 8 月 25 日に前倒しします。\n"
        "締切を過ぎた申請は翌月扱いになります。\n"
        "領収書の原本提出は不要になりました。",
    ),
    Notice(
        "laptop-refresh",
        "業務端末の入れ替え計画",
        "it",
        "2026-07-27",
        "2026 年度の業務端末を 9 月から順次入れ替えます。\n"
        "対象者には情報システム部から個別に連絡します。\n"
        "旧端末のデータ移行は各自で行ってください。",
    ),
    Notice(
        "network-maintenance",
        "社内ネットワークの定期メンテナンス",
        "it",
        "2026-08-03",
        "8 月 15 日 22 時から翌 2 時まで社内ネットワークを停止します。\n"
        "停止中は勤怠システムと共有ファイルサーバーが使えません。\n"
        "緊急連絡は情報システム部の当番へお願いします。",
    ),
    Notice(
        "office-cleaning",
        "オフィス清掃日の変更",
        "facility",
        "2026-08-04",
        "毎週金曜の清掃を毎週水曜に変更します。\n"
        "清掃の時間帯は 18 時から 20 時です。\n"
        "机の上の書類は片付けてから退社してください。",
    ),
    Notice(
        "security-training",
        "情報セキュリティ研修の受講案内",
        "hr",
        "2026-08-05",
        "全社員を対象に情報セキュリティ研修を実施します。\n"
        "受講期限は 8 月 31 日です。未受講者には人事部から督促があります。\n"
        "研修の所要時間は約 40 分です。",
    ),
    Notice(
        "summer-holiday",
        "夏季休暇の申請期限",
        "hr",
        "2026-08-06",
        "夏季休暇は 8 月中に 3 日間を取得してください。\n"
        "申請期限は 8 月 20 日です。期限を過ぎた分は繰り越せません。\n"
        "取得日の変更は上長の承認が必要です。",
    ),
]


def list_slugs() -> list[str]:
    return [notice.slug for notice in NOTICES]


def find_notice(slug: str) -> Notice | None:
    return next((notice for notice in NOTICES if notice.slug == slug), None)


def complete_slugs(prefix: str) -> list[str]:
    """補完の候補。絞り込みはサーバー側の責務"""
    needle = prefix.strip().lower()
    return [slug for slug in list_slugs() if slug.startswith(needle)]


def label_of(category: str) -> str:
    return CATEGORY_LABELS.get(category, category)


def normalize_slug(raw: str) -> str | None:
    """パーセントデコードを 1 回だけ行い、許可リストに照合する"""
    decoded = unquote(raw)
    return decoded if SLUG_PATTERN.match(decoded) else None


def match_notices(query: str, category: str) -> list[dict[str, str]]:
    """TypeScript 版の matchNotices と同じ順序で返す"""
    needle = query.strip().lower()
    if not needle:
        return []

    scoped = NOTICES if category == "all" else [n for n in NOTICES if n.category == category]
    hits: list[dict[str, str]] = []
    for notice in scoped:
        in_title = needle in notice.title.lower()
        in_body = needle in notice.body.lower()
        if not in_title and not in_body:
            continue
        hits.append(
            {
                "slug": notice.slug,
                "title": notice.title,
                "category": notice.category,
                "publishedOn": notice.published_on,
                "matchedIn": "title" if in_title else "body",
            }
        )

    # タイトル一致を先に、その中ではスラッグ昇順
    return sorted(hits, key=lambda hit: (0 if hit["matchedIn"] == "title" else 1, hit["slug"]))


def render_notice_markdown(notice: Notice) -> str:
    """お知らせ 1 件を Markdown にする（TypeScript 版と同じ 9 行）"""
    return "\n".join(
        [
            f"# {notice.title}",
            "",
            f"- スラッグ: {notice.slug}",
            f"- 分類: {label_of(notice.category)}（{notice.category}）",
            f"- 掲載日: {notice.published_on}",
            "",
            notice.body,
        ]
    )
