// 練習問題 3: 認可リクエストを間違えたときに認可サーバーが返すものを表にする。
import { ISSUER_INTERNAL } from "./bookstore-client.js";
import { buildAuthorizationUrl, probeAuthorizationRequest } from "./rp-authorize.js";
import { createPkcePair } from "./rp-pkce.js";

export type MatrixRow = {
  label: string;
  status: number;
  result: string;
  error: string;
  place: string;
};

export async function collectErrorMatrix(): Promise<MatrixRow[]> {
  const pair = createPkcePair();
  const base = { issuer: ISSUER_INTERNAL, codeChallenge: pair.codeChallenge };

  const cases: Array<{ label: string; url: string }> = [
    {
      label: "正しいリクエスト",
      url: buildAuthorizationUrl({ ...base, state: "ok" }),
    },
    {
      label: "code_challenge_method=plain",
      // plain では challenge をハッシュしないので、verifier と同じ値を送ります
      url: buildAuthorizationUrl({
        ...base,
        state: "plain",
        codeChallenge: pair.codeVerifier,
        override: { code_challenge_method: "plain" },
      }),
    },
    {
      label: "PKCE のパラメータなし",
      url: buildAuthorizationUrl({
        ...base,
        state: "no-pkce",
        override: { code_challenge: null, code_challenge_method: null },
      }),
    },
    {
      label: "未登録の redirect_uri",
      url: buildAuthorizationUrl({
        ...base,
        state: "bad-redirect",
        redirectUri: "http://evil.example.com/callback",
      }),
    },
    {
      label: "response_type=token（implicit）",
      url: buildAuthorizationUrl({ ...base, state: "implicit", override: { response_type: "token" } }),
    },
  ];

  const rows: MatrixRow[] = [];
  for (const item of cases) {
    const outcome = await probeAuthorizationRequest(item.url);
    rows.push({
      label: item.label,
      status: outcome.status,
      result: outcome.result,
      error: outcome.error ?? "-",
      place: outcome.place,
    });
  }
  return rows;
}

export function formatMatrix(rows: MatrixRow[]): string[] {
  return [
    "| 試したこと | status | 結果 | error | 返った場所 |",
    "| :--- | :--- | :--- | :--- | :--- |",
    ...rows.map((r) => `| ${r.label} | ${r.status} | ${r.result} | ${r.error} | ${r.place} |`),
  ];
}

// 直接実行したときだけ表示します（verify から import しても二重に走らせないためのガード）
if (process.argv.some((arg) => arg.includes("rp-q3-error-matrix"))) {
  for (const line of formatMatrix(await collectErrorMatrix())) console.log(line);
}
