/**
 * 横断復習2 の共通題材 ― 社内お知らせ掲示板（データ層）
 *
 * 中間プロジェクト1「社内ドキュメント検索」の予行演習になるよう、
 * 「検索してヒットを参照で返す」「1 件の本文を URI で読む」の 2 つに絞っています。
 *
 * このファイルは全問題で共有します。問題を解くときは変更しないでください
 * （データ層を共有資産として扱う練習でもあります）。
 */

export type CategoryCode = "facility" | "general" | "hr" | "it";

export type Notice = {
  readonly slug: string;
  readonly title: string;
  readonly category: CategoryCode;
  /** YYYY-MM-DD。辞書順の比較がそのまま時系列の比較になる */
  readonly publishedOn: string;
  /** Markdown の本文（3 行） */
  readonly body: string;
};

/** URI に載るスラッグの許可リスト。これ以外は読み取りを拒否する */
export const SLUG_PATTERN = /^[a-z0-9][a-z0-9-]{0,39}$/;

/** 本文をレスポンスに埋め込んでよい上限（バイト）。超えたら参照だけ返す */
export const MAX_INLINE_BYTES = 1024;

/** 1 回の検索で返せる最大件数 */
export const MAX_LIMIT = 20;

/** 既定で返す件数 */
export const DEFAULT_LIMIT = 5;

export const CATEGORY_LABELS: Record<CategoryCode, string> = {
  facility: "設備",
  general: "総務",
  hr: "人事",
  it: "情報システム",
};

/** 分類フィルタの候補（補完でそのまま返せるように昇順で持つ）。all は絞り込みなし */
export const CATEGORY_CODES = ["all", "facility", "general", "hr", "it"] as const;

export type CategoryFilter = (typeof CATEGORY_CODES)[number];

/**
 * お知らせ 8 件。スラッグの昇順で持っています。
 * 順序を固定するのは、同じ入力なら同じ順序で返せるようにするためです
 * （検索結果・補完候補・テストの安定に効きます）。
 */
export const NOTICES: readonly Notice[] = [
  {
    slug: "badge-renewal",
    title: "入館証の更新手続きについて",
    category: "general",
    publishedOn: "2026-07-06",
    body: [
      "入館証の有効期限が 2026 年 9 月末で切れます。",
      "更新は総務ポータルから申請してください。写真の再提出は不要です。",
      "新しい入館証は 9 月 15 日から順次配布します。",
    ].join("\n"),
  },
  {
    slug: "desk-move",
    title: "7 月の座席移動のお知らせ",
    category: "facility",
    publishedOn: "2026-07-13",
    body: [
      "7 月 21 日に 3 階と 4 階の座席を入れ替えます。",
      "私物は前日までに各自のロッカーへ移してください。",
      "当日はネットワークの再配線を行うため、有線接続は使えません。",
    ].join("\n"),
  },
  {
    slug: "expense-deadline",
    title: "経費精算の締切変更",
    category: "general",
    publishedOn: "2026-07-21",
    body: [
      "8 月分の経費精算の締切を 8 月 25 日に前倒しします。",
      "締切を過ぎた申請は翌月扱いになります。",
      "領収書の原本提出は不要になりました。",
    ].join("\n"),
  },
  {
    slug: "laptop-refresh",
    title: "業務端末の入れ替え計画",
    category: "it",
    publishedOn: "2026-07-27",
    body: [
      "2026 年度の業務端末を 9 月から順次入れ替えます。",
      "対象者には情報システム部から個別に連絡します。",
      "旧端末のデータ移行は各自で行ってください。",
    ].join("\n"),
  },
  {
    slug: "network-maintenance",
    title: "社内ネットワークの定期メンテナンス",
    category: "it",
    publishedOn: "2026-08-03",
    body: [
      "8 月 15 日 22 時から翌 2 時まで社内ネットワークを停止します。",
      "停止中は勤怠システムと共有ファイルサーバーが使えません。",
      "緊急連絡は情報システム部の当番へお願いします。",
    ].join("\n"),
  },
  {
    slug: "office-cleaning",
    title: "オフィス清掃日の変更",
    category: "facility",
    publishedOn: "2026-08-04",
    body: [
      "毎週金曜の清掃を毎週水曜に変更します。",
      "清掃の時間帯は 18 時から 20 時です。",
      "机の上の書類は片付けてから退社してください。",
    ].join("\n"),
  },
  {
    slug: "security-training",
    title: "情報セキュリティ研修の受講案内",
    category: "hr",
    publishedOn: "2026-08-05",
    body: [
      "全社員を対象に情報セキュリティ研修を実施します。",
      "受講期限は 8 月 31 日です。未受講者には人事部から督促があります。",
      "研修の所要時間は約 40 分です。",
    ].join("\n"),
  },
  {
    slug: "summer-holiday",
    title: "夏季休暇の申請期限",
    category: "hr",
    publishedOn: "2026-08-06",
    body: [
      "夏季休暇は 8 月中に 3 日間を取得してください。",
      "申請期限は 8 月 20 日です。期限を過ぎた分は繰り越せません。",
      "取得日の変更は上長の承認が必要です。",
    ].join("\n"),
  },
];

export function listSlugs(): string[] {
  return NOTICES.map((notice) => notice.slug);
}

export function findNotice(slug: string): Notice | undefined {
  return NOTICES.find((notice) => notice.slug === slug);
}

export function labelOf(category: CategoryCode): string {
  return CATEGORY_LABELS[category];
}

/** 補完の候補（前方一致）。絞り込みはサーバー側の責務なのでここで行う */
export function completeSlugs(prefix: string): string[] {
  const needle = prefix.trim().toLowerCase();
  return listSlugs().filter((slug) => slug.startsWith(needle));
}

/** 分類フィルタの補完候補（前方一致） */
export function completeCategories(prefix: string): string[] {
  const needle = prefix.trim().toLowerCase();
  return CATEGORY_CODES.filter((code) => code.startsWith(needle));
}

/** 文字列を分類フィルタに変換する。候補に無ければ undefined（検証はサーバーの責務） */
export function toCategoryFilter(raw: string): CategoryFilter | undefined {
  return CATEGORY_CODES.find((code) => code === raw);
}

export type Hit = {
  slug: string;
  title: string;
  category: CategoryCode;
  publishedOn: string;
  /** 一致した場所。タイトル一致を優先して並べるために使う */
  matchedIn: "title" | "body";
};

/**
 * タイトルと本文の部分一致で検索する。
 * 並び順は「タイトル一致 → 本文一致」、その中ではスラッグ昇順で固定します。
 */
export function matchNotices(query: string, category: CategoryFilter): Hit[] {
  const needle = query.trim().toLowerCase();
  if (needle.length === 0) {
    // 空文字は includes() が常に true になり全件ヒットしてしまうので、ここで止める
    return [];
  }

  const scoped = category === "all" ? NOTICES : NOTICES.filter((n) => n.category === category);
  const hits: Hit[] = [];
  for (const notice of scoped) {
    const inTitle = notice.title.toLowerCase().includes(needle);
    const inBody = notice.body.toLowerCase().includes(needle);
    if (!inTitle && !inBody) {
      continue;
    }
    hits.push({
      slug: notice.slug,
      title: notice.title,
      category: notice.category,
      publishedOn: notice.publishedOn,
      matchedIn: inTitle ? "title" : "body",
    });
  }

  return hits.sort((a, b) => {
    if (a.matchedIn === b.matchedIn) {
      return a.slug.localeCompare(b.slug);
    }
    return a.matchedIn === "title" ? -1 : 1;
  });
}

/** お知らせ 1 件を Markdown にする（常に 9 行） */
export function renderNoticeMarkdown(notice: Notice): string {
  return [
    `# ${notice.title}`,
    "",
    `- スラッグ: ${notice.slug}`,
    `- 分類: ${labelOf(notice.category)}（${notice.category}）`,
    `- 掲載日: ${notice.publishedOn}`,
    "",
    notice.body,
  ].join("\n");
}

/** UTF-8 でのバイト数。文字数ではなくバイト数で上限を判断する */
export function byteSizeOf(text: string): number {
  return new TextEncoder().encode(text).length;
}
