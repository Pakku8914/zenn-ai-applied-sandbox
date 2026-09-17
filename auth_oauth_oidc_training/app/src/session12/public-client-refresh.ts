// セッション 12: 公開クライアントにリフレッシュトークンを渡すときの条件。
// セッション 7 で「既定では旧リフレッシュトークンが再利用できてしまう」ことを実測しました。
// クライアント認証ができない相手に渡すなら、その既定のままでは使えません。

export type Placement = "server-side" | "spa-with-bff" | "spa-token-in-browser" | "mobile-app";

export const ALL_PLACEMENTS: readonly Placement[] = [
  "server-side",
  "spa-with-bff",
  "spa-token-in-browser",
  "mobile-app",
];

export type RefreshPolicy = {
  readonly placement: Placement;
  readonly label: string;
  /** クライアント認証（client_secret など）ができるか */
  readonly confidential: boolean;
  /** リフレッシュトークンがブラウザ・端末の上に置かれるか */
  readonly tokenOnClient: boolean;
  /** ローテーション（使ったら旧トークンを無効にする）が必須か */
  readonly rotationRequired: boolean;
  /** 再利用検知（旧トークンが使われたらセッションごと落とす）が必須か */
  readonly reuseDetectionRequired: boolean;
  readonly note: string;
};

const LABELS: Record<Placement, string> = {
  "server-side": "サーバーサイドのクライアント（機密クライアント）",
  "spa-with-bff": "SPA ＋ BFF（トークンは BFF のサーバー側）",
  "spa-token-in-browser": "SPA でトークンをブラウザに置く",
  "mobile-app": "モバイルアプリ",
};

const NOTES: Record<Placement, string> = {
  "server-side": "client_secret を添えてリフレッシュするので、認可サーバーは呼び出し元を確かめられる",
  "spa-with-bff": "リフレッシュするのは BFF（サーバー）。ブラウザ側の事情はリフレッシュに影響しない",
  "spa-token-in-browser": "XSS で持ち去られた 1 本が長期間の足がかりになる。ローテーションと検知が最低条件",
  "mobile-app": "端末のバックアップ・別アプリからの読み出しを完全には防げない。ローテーションが前提",
};

/**
 * 配置形態から、リフレッシュトークンの取り扱いの条件を導きます。
 * 表を引くのではなく「クライアント認証ができるか」から計算するのが要点です。
 */
export function refreshPolicyFor(placement: Placement): RefreshPolicy {
  // 秘密を安全に持てるのはサーバーだけ。BFF は「サーバー」なので機密クライアントになれる
  const confidential = placement === "server-side" || placement === "spa-with-bff";
  const tokenOnClient = placement === "spa-token-in-browser" || placement === "mobile-app";
  // クライアント認証ができないと、認可サーバーは「正しいクライアントが使っているのか」を確かめられない。
  // 代わりに「1 回しか使えない」ことで、盗まれたトークンが使われ続けるのを防ぐ
  const rotationRequired = !confidential;
  return {
    placement,
    label: LABELS[placement],
    confidential,
    tokenOnClient,
    rotationRequired,
    // ローテーションだけでは「盗んだ側が先に使った」場合に気づけないので、検知まで必要になる
    reuseDetectionRequired: rotationRequired,
    note: NOTES[placement],
  };
}

/** ローテーションを有効にする realm の設定（セッション 7 で一度だけ切り替えて戻した項目） */
export const ROTATION_SETTINGS = {
  revokeRefreshToken: true, // 使ったリフレッシュトークンを無効にする
  refreshTokenMaxReuse: 0, // 再利用は 1 回も許さない
} as const;
