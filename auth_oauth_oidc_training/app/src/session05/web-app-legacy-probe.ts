// 廃止されたフローを、いまの認可サーバーに実際に投げてみるための探針（プローブ）です。
// 正しい認可リクエストの組み立ては次章のテーマなので、ここでは「拒否されること」を
// 確かめるために必要な最小限のパラメータしか付けていません。
// realm の設定は一切変更しません（読み取りと、拒否されることの確認だけです）。

const ISSUER = process.env["ISSUER_INTERNAL"] ?? "http://keycloak:8080/realms/bookstore";

export const AUTHORIZE_ENDPOINT = `${ISSUER}/protocol/openid-connect/auth`;
export const TOKEN_ENDPOINT = `${ISSUER}/protocol/openid-connect/token`;
/** realm に登録済みのリダイレクト URI（http://localhost:3100/* に一致する） */
export const REDIRECT_URI = "http://localhost:3100/callback";

/**
 * implicit を塞いだときに返る error_description の先頭。
 * Keycloak のバージョンによって後ろに一文が足されることがあるため、先頭一致で確かめます。
 */
export const IMPLICIT_ERROR_PREFIX =
  "Client is not allowed to initiate browser login with given response_type";

/** 拒否された応答を、機械で読める形にそろえたもの */
export type ErrorProbe = {
  readonly status: number;
  readonly error: string;
  readonly errorDescription: string;
  /** エラーが URL のフラグメント（#）に載って返ってきたか */
  readonly inFragment: boolean;
};

/** トークンエンドポイントの応答を、機械で読める形にそろえたもの */
export type TokenProbe = {
  readonly status: number;
  /** 返ってきた JSON のキー（並びを固定するため辞書順にそろえる） */
  readonly keys: readonly string[];
  readonly tokenType: string;
  readonly expiresIn: number;
  readonly scope: string;
  readonly hasRefreshToken: boolean;
  readonly error: string;
};

/** JSON が返らない応答でも落ちないように、本文を自分で読んでから解析します */
async function readJson(res: Response): Promise<Record<string, unknown>> {
  const raw = await res.text();
  if (!raw.startsWith("{")) {
    return {};
  }
  return JSON.parse(raw) as Record<string, unknown>;
}

function str(body: Record<string, unknown>, key: string): string {
  const value = body[key];
  return typeof value === "string" ? value : "";
}

/** OAuth 2.1 で削除された implicit フロー（response_type=token）を投げてみる */
export async function probeImplicit(): Promise<ErrorProbe> {
  const query = new URLSearchParams({
    response_type: "token", // ここが implicit の目印。トークンを直接くれと要求している
    client_id: "web-app",
    redirect_uri: REDIRECT_URI,
    scope: "openid",
  });
  // redirect: "manual" を付けないと fetch が 302 を自動で追ってしまい、エラーを観察できません
  const res = await fetch(`${AUTHORIZE_ENDPOINT}?${query.toString()}`, { redirect: "manual" });
  await res.text(); // 本文は使いませんが読み切っておきます
  const location = res.headers.get("location") ?? "";
  const hash = location.indexOf("#");
  const mark = hash >= 0 ? hash : location.indexOf("?");
  const params = new URLSearchParams(mark >= 0 ? location.slice(mark + 1) : "");
  return {
    status: res.status,
    error: params.get("error") ?? "",
    errorDescription: params.get("error_description") ?? "",
    inFragment: hash >= 0,
  };
}

/** OAuth 2.1 で削除された ROPC（grant_type=password）を投げてみる */
export async function probeRopc(): Promise<ErrorProbe> {
  const res = await fetch(TOKEN_ENDPOINT, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "password", // ここが ROPC の目印
      client_id: "web-app",
      username: "alice",
      password: "alice-pass", // クライアントがパスワードを受け取っている。これが問題の本体
      scope: "openid",
    }),
  });
  const body = await readJson(res);
  return {
    status: res.status,
    error: str(body, "error"),
    errorDescription: str(body, "error_description"),
    inFragment: false,
  };
}

/**
 * Client Credentials フローを投げてみる。
 * clientSecret を渡さなければ公開クライアントとしての試行になります。
 */
export async function probeClientCredentials(
  clientId: string,
  clientSecret?: string,
): Promise<TokenProbe> {
  const form = new URLSearchParams({ grant_type: "client_credentials", client_id: clientId });
  if (clientSecret !== undefined) {
    form.set("client_secret", clientSecret);
  }
  const res = await fetch(TOKEN_ENDPOINT, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: form,
  });
  const body = await readJson(res);
  const expiresIn = body["expires_in"];
  return {
    status: res.status,
    keys: Object.keys(body).sort(),
    tokenType: str(body, "token_type"),
    expiresIn: typeof expiresIn === "number" ? expiresIn : 0,
    scope: str(body, "scope"),
    hasRefreshToken: body["refresh_token"] !== undefined,
    error: str(body, "error"),
  };
}
