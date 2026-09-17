// 問題 1 の解答: Authorization ヘッダの 10 パターンを実際に送り、応答を表にします。
import type { Hono } from "hono";
import type { ApiEnv } from "./api-service-claims.js";

export type AuthorizationCase = {
  label: string;
  /** そのまま送るヘッダ値。省略するとヘッダを付けない */
  header?: string;
  /** 本物のトークンを使う場合のスキーム名（大文字小文字の違いを試すため） */
  scheme?: string;
};

export const AUTHORIZATION_CASES: readonly AuthorizationCase[] = [
  { label: "ヘッダを付けない" },
  { label: "空文字だけ", header: "" },
  { label: "空白だけ", header: "   " },
  { label: "Basic を送る", header: "Basic YWxpY2U6YWxpY2UtcGFzcw==" },
  { label: "スキームだけ", header: "Bearer" },
  { label: "スキームの後ろが空白だけ", header: "Bearer " },
  { label: "トークンに空白が混ざる", header: "Bearer a.b c.d" },
  // 日本語はヘッダ値に入れられない（送る前に fetch が例外を投げる）ので、ASCII の使えない文字で試します
  { label: "使えない文字（@）が混ざる", header: "Bearer a@b" },
  { label: "小文字の bearer ＋ 本物のトークン", scheme: "bearer" },
  { label: "Bearer ＋ 本物のトークン", scheme: "Bearer" },
];

export type AuthorizationRow = {
  label: string;
  status: number;
  /** WWW-Authenticate の error パラメータ（無ければ null） */
  challengeError: string | null;
  hasChallenge: boolean;
  /** 応答本文の error（200 のときは null） */
  bodyError: string | null;
};

/** WWW-Authenticate の値から scheme・realm・error を取り出します */
export function parseChallenge(value: string | null): {
  scheme: string | null;
  realm: string | null;
  error: string | null;
} {
  if (value === null) return { scheme: null, realm: null, error: null };
  return {
    scheme: value.split(" ")[0] ?? null,
    realm: /realm="([^"]*)"/.exec(value)?.[1] ?? null,
    error: /error="([^"]*)"/.exec(value)?.[1] ?? null,
  };
}

export async function reportAuthorizationHandling(
  app: Hono<ApiEnv>,
  accessToken: string,
  cases: readonly AuthorizationCase[] = AUTHORIZATION_CASES,
): Promise<AuthorizationRow[]> {
  const rows: AuthorizationRow[] = [];
  for (const testCase of cases) {
    const header = testCase.scheme === undefined ? testCase.header : `${testCase.scheme} ${accessToken}`;
    const res = await app.request("/api/whoami", header === undefined ? undefined : { headers: { authorization: header } });
    const challenge = res.headers.get("www-authenticate");
    const body = (await res.json()) as { error?: string };
    rows.push({
      label: testCase.label,
      status: res.status,
      challengeError: parseChallenge(challenge).error,
      hasChallenge: challenge !== null,
      bodyError: res.status === 200 ? null : (body.error ?? null),
    });
  }
  return rows;
}

/** 表として読める形に整えます（Markdown の表にそのまま貼れます） */
export function toMarkdownTable(rows: readonly AuthorizationRow[]): string {
  const head = "| 送ったヘッダ | status | WWW-Authenticate の error | 本文の error |\n| :--- | :--- | :--- | :--- |";
  const body = rows
    .map(
      (row) =>
        `| ${row.label} | ${row.status} | ${row.challengeError ?? (row.hasChallenge ? "(なし)" : "(ヘッダなし)")} | ${row.bodyError ?? "-"} |`,
    )
    .join("\n");
  return `${head}\n${body}`;
}
