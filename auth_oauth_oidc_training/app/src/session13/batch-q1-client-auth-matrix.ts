// セッション 13 問題 1: クライアント認証の 4 方式を表にして、実際に試せる 2 方式を比べます。
import { buildTokenRequest, requestClientCredentials } from "./batch-worker-client.js";
import type { ClientAuthMethod } from "./batch-worker-client.js";

/** 秘密（または鍵）がどこを通るか */
export type SecretLocation = "Authorization ヘッダ" | "リクエストボディ" | "署名（秘密は送らない）" | "TLS の通信路";

export type AuthMethodFact = {
  readonly method: string;
  readonly secretLocation: SecretLocation;
  /** 秘密そのものがクライアントの外に出るか */
  readonly secretLeavesTheClient: boolean;
  readonly needsKeyPair: boolean;
  /** 本書のサンドボックス（HTTP の start-dev）で試せるか */
  readonly worksInSandbox: boolean;
  readonly note: string;
};

// secretLeavesTheClient と needsKeyPair の 2 列だけで、4 方式が 3 グループに分かれます
export const AUTH_METHOD_FACTS: readonly AuthMethodFact[] = [
  { method: "client_secret_basic", secretLocation: "Authorization ヘッダ", secretLeavesTheClient: true, needsKeyPair: false, worksInSandbox: true, note: "秘密をヘッダに入れて送る。OAuth 2.1 が既定とする形" },
  { method: "client_secret_post", secretLocation: "リクエストボディ", secretLeavesTheClient: true, needsKeyPair: false, worksInSandbox: true, note: "置き場所がボディになるだけ。強さは basic と同じ" },
  { method: "private_key_jwt", secretLocation: "署名（秘密は送らない）", secretLeavesTheClient: false, needsKeyPair: true, worksInSandbox: true, note: "秘密鍵で assertion に署名し、認可サーバーには公開鍵だけを渡す" },
  { method: "tls_client_auth", secretLocation: "TLS の通信路", secretLeavesTheClient: false, needsKeyPair: true, worksInSandbox: false, note: "クライアント証明書で接続そのものを証明する。HTTPS が前提" },
];

/** 表の 1 行目が見出し、2 行目が区切り。行数は 2 + 方式の数になります */
export function toMarkdown(facts: readonly AuthMethodFact[] = AUTH_METHOD_FACTS): string {
  const header = "| 方式 | 秘密の置き場所 | 秘密が外に出るか | 鍵ペアが要るか | サンドボックスで試せるか |";
  const divider = "| :--- | :--- | :--- | :--- | :--- |";
  const rows = facts.map(
    (fact) =>
      `| \`${fact.method}\` | ${fact.secretLocation} | ${fact.secretLeavesTheClient ? "出る" : "出ない"} | ${
        fact.needsKeyPair ? "要る" : "要らない"
      } | ${fact.worksInSandbox ? "試せる" : "試せない"} |`,
  );
  return [header, divider, ...rows].join("\n");
}

export type ProbeRow = {
  readonly method: ClientAuthMethod;
  readonly status: number;
  readonly tokenType: string;
  /** 秘密が Authorization ヘッダに載ったか */
  readonly sentInHeader: boolean;
  /** 秘密がリクエストボディに載ったか */
  readonly sentInBody: boolean;
};

/** 方式を 1 つ選んでトークンを取り、「何が返ったか」と「秘密がどこを通ったか」を記録します */
export async function probe(method: ClientAuthMethod): Promise<ProbeRow> {
  const request = buildTokenRequest({ method });
  const result = await requestClientCredentials({ method });
  return {
    method,
    status: result.status,
    tokenType: result.tokenType,
    sentInHeader: request.headers["authorization"] !== undefined,
    sentInBody: request.body.has("client_secret"),
  };
}

export async function probeAll(): Promise<readonly ProbeRow[]> {
  // 同時に投げると Keycloak 側のログが混ざって読みにくいので、順に実行します
  const basic = await probe("client_secret_basic");
  const post = await probe("client_secret_post");
  return [basic, post];
}
