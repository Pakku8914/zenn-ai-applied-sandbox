// 横断復習③ 問題 9: 外部 IdP から来た 1 回のログインを、注文台帳の持ち主 ID まで 1 本につなぎます。
// mapClaims()（S15 後半）・FederatedUserStore（S15 後半）・AccountLinks（mid01）は import するだけ。
// 足すのは 3 つをつなぐ翻訳と、「拒否したログインでは対応表に書かない」という 1 本の不変条件です。
import { AccountLinks } from "../mid01/mid01-accounts.js";
import { mapClaims } from "../session15/rp-attribute-mapping.js";
import type { ExternalClaims } from "../session15/rp-attribute-mapping.js";
import { FederatedUserStore } from "../session15/rp-jit-provisioning.js";
import type { FederatedKey } from "../session15/rp-jit-provisioning.js";

export type LoginContext = {
  readonly store: FederatedUserStore;
  readonly links: AccountLinks;
  /** 外部 IdP の (issuer, subject)。連携先が増えても衝突しない鍵 */
  readonly federatedKey: FederatedKey;
  /**
   * bookstore realm が発行したトークンの sub。ブローカー構成では web-app が受け取るトークンを
   * 署名・発行するのは bookstore realm なので、注文台帳との対応表の鍵はこちらです。
   */
  readonly tokenSub: string;
  readonly claims: ExternalClaims;
};

export type LoginError = "profile_incomplete" | "account_link_required" | "account_deactivated";

export type LoginResolution =
  | {
      readonly status: 200;
      readonly ownerId: string;
      readonly outcome: "created" | "reused" | "linked";
      /** マッピングで捨てた外部のグループ名。捨てた事実だけを記録します */
      readonly dropped: readonly string[];
    }
  | { readonly status: 422 | 409 | 403; readonly error: LoginError; readonly detail: string };

/** 成功したときだけ AccountLinks に書き、失敗したときは 1 行も書きません */
export function resolveFederatedLogin(context: LoginContext): LoginResolution {
  // 1. 相手のクレームを書店のプロフィールに写す。担当店舗とロールは定義が決めるので、
  //    相手が名乗った値をここで採ることはありません。
  const mapped = mapClaims(context.claims);
  if (!mapped.ok) {
    // 必須の属性が埋まらないログインでレコードを作ると、後から直すのが非常に困難になります
    return { status: 422, error: "profile_incomplete", detail: mapped.missing.join(" ") };
  }

  // 2. 連携鍵で台帳を引き、初回なら作る（JIT プロビジョニング）
  const result = context.store.provision(context.federatedKey, mapped.profile);
  if (result.outcome === "rejected") {
    // detail に返すのは衝突相手の利用者 ID だけ。
    // メールアドレスを返すと「そのメールの利用者がいるか」を確かめる道具になります
    return result.reason === "deactivated"
      ? { status: 403, error: "account_deactivated", detail: result.userId }
      : { status: 409, error: "account_link_required", detail: result.userId };
  }

  // 3. トークンの sub と書店の利用者 ID を結び付ける。
  //    link() はすでに結び付いていればそのときの値を返すので、何度ログインしても増えません
  const ownerId = context.links.link(context.tokenSub, result.user.userId);
  return { status: 200, ownerId, outcome: result.outcome, dropped: mapped.dropped };
}
