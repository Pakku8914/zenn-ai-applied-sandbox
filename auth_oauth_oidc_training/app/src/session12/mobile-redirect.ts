// セッション 12: モバイルアプリのリダイレクト先を評価します。
// セッション 6 で「リダイレクト URI は完全一致で照合される」ことを見ました。
// その照合が守るのは「認可サーバーがどこへ返すか」までで、
// 「その宛先を本当にそのアプリが受け取るか」は別の問題です。この 2 つを分けて考えます。

export type RedirectKind = "https-app-link" | "custom-scheme" | "loopback" | "unknown";

export type RedirectVerdict = {
  readonly uri: string;
  readonly kind: RedirectKind;
  /** 同じ宛先を名乗る別のアプリに横取りされうるか */
  readonly hijackable: boolean;
  /** その宛先が「そのアプリのもの」であることを OS が確かめる経路があるか */
  readonly ownershipVerified: boolean;
  /** 認可サーバーが完全一致で登録・照合できる形か（セッション 6） */
  readonly exactMatchable: boolean;
  readonly note: string;
};

type Rule = Omit<RedirectVerdict, "uri"> & { readonly test: (uri: string) => boolean };

/**
 * 上から順に当てはめます。順序が意味を持つので、判定を if の連なりではなく表にしてあります
 * （`https://` はカスタムスキームの形にも当てはまるため、必ず先に見る必要があります）。
 */
const RULES: readonly Rule[] = [
  {
    kind: "loopback",
    test: (uri) => /^http:\/\/(127\.0\.0\.1|\[::1\]|localhost)(:\d+)?(\/|$)/.test(uri),
    hijackable: false,
    ownershipVerified: false,
    exactMatchable: false,
    note: "端末の中だけで完結する。ポート番号を固定できないため完全一致では照合できない（RFC 8252）",
  },
  {
    kind: "unknown",
    test: (uri) => uri.startsWith("http://"),
    hijackable: true,
    ownershipVerified: false,
    exactMatchable: true,
    note: "ループバック以外の平文 http。経路上で認可コードを読まれるため宛先にしてはいけない",
  },
  {
    kind: "https-app-link",
    test: (uri) => /^https:\/\/[^/]+(\/.*)?$/.test(uri),
    hijackable: false,
    ownershipVerified: true,
    exactMatchable: true,
    note: "OS がドメイン上の設定ファイルを取得して所有関係を確かめる（Universal Links / App Links）",
  },
  {
    kind: "custom-scheme",
    test: (uri) => /^[a-z][a-z0-9+.-]*:\/\//i.test(uri),
    hijackable: true,
    ownershipVerified: false,
    exactMatchable: true,
    note: "スキーム名は先に宣言した者勝ち。同じ名前を名乗る別のアプリが受け取りうる",
  },
];

const UNKNOWN: Rule = {
  kind: "unknown",
  test: () => true,
  hijackable: true,
  ownershipVerified: false,
  exactMatchable: false,
  note: "形が判別できない。登録も照合もできない",
};

/** 1 つのリダイレクト先を、種類と「何が守られて何が守られないか」に分解します */
export function classifyRedirectUri(uri: string): RedirectVerdict {
  const rule = RULES.find((item) => item.test(uri)) ?? UNKNOWN;
  return {
    uri,
    kind: rule.kind,
    hijackable: rule.hijackable,
    ownershipVerified: rule.ownershipVerified,
    exactMatchable: rule.exactMatchable,
    note: rule.note,
  };
}

/**
 * 認可サーバーに登録した文字列と、クライアントが送ってきた文字列を照合します（セッション 6）。
 * 本書の realm は学習のために `http://localhost:3100/*` とワイルドカードで登録していますが、
 * OAuth 2.1 が求めるのは完全一致です。この関数は「ワイルドカードだと何が通ってしまうか」を
 * 自分の目で確かめるためにあります。
 */
export function matchesRegistration(registered: string, requested: string): boolean {
  if (registered.endsWith("/*")) {
    return requested.startsWith(registered.slice(0, -1));
  }
  return registered === requested;
}

/** ワイルドカード登録かどうか。true なら「照合が緩い」ことを前提に運用する必要があります */
export const isWildcardRegistration = (registered: string): boolean => registered.endsWith("/*");
