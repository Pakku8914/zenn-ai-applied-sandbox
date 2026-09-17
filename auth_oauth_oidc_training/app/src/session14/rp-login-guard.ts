// セッション 14: コールバックの受け口を 2 つ並べたファイル。
// 前半は state も iss も確かめない Bad、後半はセッション 6 の PendingLoginStore に
// RFC 9207 の iss の照合を足した Good（HardenedPendingLoginStore）です。
// 複数の認可サーバーを受け付ける RP が「どの認可サーバーからの応答か」を確かめられないと、
// 混乱した代理（confused deputy）が成立するためです。

/**
 * state も iss も確かめずにコールバックのコードをそのまま信じる受け口（Bad）。
 * 「誰が始めたログインか」を問わないので、他人（攻撃者）のコードでもログインが成立します。
 */
export function consumeWithoutChecks(params: URLSearchParams): { code: string } {
  return { code: params.get("code") ?? "" };
}

/** 失敗の理由。文面ではなくこの値で分岐します（セッション 6 の CallbackError に issuer_mismatch を足した形） */
export type HardenedFailureReason =
  | "authorization_error"
  | "state_mismatch"
  | "issuer_mismatch"
  | "missing_code";

export class HardenedCallbackError extends Error {
  readonly reason: HardenedFailureReason;

  constructor(reason: HardenedFailureReason, message: string) {
    super(message);
    this.reason = reason;
  }
}

export type HardenedPendingLogin = {
  state: string;
  codeVerifier: string;
  /** このログインを始めた相手（認可サーバー）の iss。コールバックの iss と突き合わせます */
  expectedIssuer: string;
};

/**
 * 始めたけれどまだ終わっていないログインを覚えておく入れ物です。
 * セッション 6 の PendingLoginStore との違いは、start でも remember でも expectedIssuer を必ず持つことと、
 * consumeCallback が state のあとに iss も照合することです。
 */
export class HardenedPendingLoginStore {
  private readonly pending = new Map<string, HardenedPendingLogin>();

  /** 別の手段で始めたログインを預けます（検証でブラウザ役のヘルパーと合流するために使う） */
  remember(entry: HardenedPendingLogin): void {
    this.pending.set(entry.state, entry);
  }

  /** state → iss → code の順に確かめます。1 つでも合わなければ例外にします */
  consumeCallback(params: URLSearchParams): { code: string; codeVerifier: string } {
    // 1. エラーで戻ってきた場合はここで終わり
    const error = params.get("error");
    if (error !== null) {
      throw new HardenedCallbackError(
        "authorization_error",
        `認可サーバーがエラーを返しました: ${error} / ${params.get("error_description") ?? ""}`,
      );
    }
    // 2. state の突き合わせ（自分が始めたログインか）
    const state = params.get("state") ?? "";
    const entry = this.pending.get(state);
    if (entry === undefined) {
      throw new HardenedCallbackError("state_mismatch", "state が一致しません（自分が始めたログインではありません）");
    }
    // 3. iss の突き合わせ（どの認可サーバーからの応答か）。RFC 9207 が付けてくれる iss を使います
    const iss = params.get("iss");
    if (iss !== entry.expectedIssuer) {
      this.pending.delete(state); // 取り違えた応答は途中の状態ごと捨てる
      throw new HardenedCallbackError(
        "issuer_mismatch",
        `iss が一致しません（期待: ${entry.expectedIssuer} / 実際: ${iss ?? "なし"}）`,
      );
    }
    this.pending.delete(state); // 1 度使った state は捨てる
    // 4. ここまで通ってから認可コードを取り出す
    const code = params.get("code");
    if (code === null) {
      throw new HardenedCallbackError("missing_code", "認可コードがありません");
    }
    return { code, codeVerifier: entry.codeVerifier };
  }

  get size(): number {
    return this.pending.size;
  }
}
