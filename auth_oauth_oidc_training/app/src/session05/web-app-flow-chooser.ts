// 用途からフローを選ぶ判断表を、そのまま実行できる形にしたものです。
// 「いまなら何を選ぶか（chooseFlow）」と「2012 年ごろなら何を選んでいたか（legacyChoice）」を
// 並べられるようにして、既存コードを読み替えられる状態にします。

/** いま選んでよいフロー。none は「この条件では使えるフローが無い」という答え */
export type FlowId = "authorization-code+pkce" | "client-credentials" | "device-code" | "none";

/** OAuth 2.0 の時代に選ばれていたフロー */
export type LegacyFlowId =
  | "authorization-code"
  | "implicit"
  | "ropc"
  | "client-credentials"
  | "none";

export type Situation = {
  readonly label: string;
  /** 利用者がその場にいて、自分で操作できるか */
  readonly userPresent: boolean;
  /** ブラウザ（または OS の外部ブラウザ）を開いてログイン画面を見せられるか */
  readonly hasBrowser: boolean;
  /** client_secret を誰にも見られない場所に置けるか */
  readonly canKeepSecret: boolean;
};

export type Choice = { readonly flow: FlowId; readonly reason: string };

export type LegacyChoice = {
  readonly flow: LegacyFlowId;
  /** OAuth 2.1 で削除されたフローかどうか */
  readonly removed: boolean;
  readonly note: string;
};

/** 3 つの質問に答えるだけでフローが決まります。これが本章の判断表の本体です */
export function chooseFlow(s: Situation): Choice {
  if (!s.userPresent) {
    return s.canKeepSecret
      ? {
          flow: "client-credentials",
          reason: "許可する利用者がいないので、クライアント自身の資格情報でトークンを取る",
        }
      : {
          flow: "none",
          reason: "秘密を守れないクライアントに、利用者不在で使える権限は渡せない",
        };
  }
  if (s.hasBrowser) {
    return {
      flow: "authorization-code+pkce",
      reason: "利用者に認可サーバーのログイン画面を見せられるので、認可コードを PKCE 付きで交換する",
    };
  }
  return {
    flow: "device-code",
    reason: "ログイン画面を出せないので、別の端末でコードを入力してもらう",
  };
}

/** 同じ状況を 2012 年ごろの常識で選び直すとどうなるか（既存コードを読むための対応表） */
export function legacyChoice(s: Situation): LegacyChoice {
  if (!s.userPresent) {
    return s.canKeepSecret
      ? {
          flow: "client-credentials",
          removed: false,
          note: "利用者が登場しないフローなので、2.1 でもそのまま使える",
        }
      : {
          flow: "none",
          removed: false,
          note: "当時も、秘密を守れないクライアントに渡せる手段は無かった",
        };
  }
  if (!s.hasBrowser) {
    return {
      flow: "ropc",
      removed: true,
      note: "クライアントがパスワードを受け取ってしまうため 2.1 で削除された",
    };
  }
  return s.canKeepSecret
    ? {
        flow: "authorization-code",
        removed: false,
        note: "当時から正解。2.1 では PKCE が必須になった",
      }
    : {
        flow: "implicit",
        removed: true,
        note: "アクセストークンが URL に載るため 2.1 で削除された",
      };
}

/** 本書のサンドボックスに出てくる 4 つの状況 */
export const SITUATIONS: readonly Situation[] = [
  {
    label: "書店のフロント（ブラウザで動く web-app）",
    userPresent: true,
    hasBrowser: true,
    canKeepSecret: false,
  },
  {
    label: "書店の管理画面（サーバー側で動く Web アプリ）",
    userPresent: true,
    hasBrowser: true,
    canKeepSecret: true,
  },
  {
    label: "店頭のテレビ端末（文字入力が難しくブラウザを開けない）",
    userPresent: true,
    hasBrowser: false,
    canKeepSecret: true,
  },
  {
    label: "夜間バッチ（batch-worker）",
    userPresent: false,
    hasBrowser: false,
    canKeepSecret: true,
  },
];
