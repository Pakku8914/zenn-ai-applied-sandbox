// セッション 13 問題 5: トークン文字列だけを盗んだ攻撃者がどこまで使えるかを並べます。
// 攻撃者が持つのは「トークンの文字列」だけで、被害者の秘密鍵は持っていません。
import { TOKEN_ENDPOINT } from "../session04/bookstore-endpoints.js";
import { createApiApp } from "../session10/api-service-app.js";
import { requestClientCredentials } from "./batch-worker-client.js";
import { createDpopKey } from "./bookstore-dpop.js";
import type { DpopKey } from "./bookstore-dpop.js";
import { apiUrl } from "./api-service-dpop-app.js";
import { createDpopApi } from "./api-q4-dpop-middleware.js";

export type Outcome =
  | "盗んだだけで通る"
  | "鍵が無いので通らない"
  | "サーバーが見ていないので通る"
  | "スキームが違うので通らない";

export type TheftRow = {
  readonly attempt: string;
  readonly status: number;
  readonly error: string;
  readonly outcome: Outcome;
};

/** bearerToken は制約の無いトークン、dpopToken は鍵に縛られたトークン */
export type VictimSession = {
  readonly bearerToken: string;
  readonly dpopToken: string;
  readonly dpopKey: DpopKey;
};

/** 被害者役の準備。2 種類のトークンを 1 本ずつ */
export async function prepareVictim(): Promise<VictimSession> {
  const key = await createDpopKey();
  const bearer = await requestClientCredentials();
  const bound = await requestClientCredentials({
    dpopProof: await key.createProof({ htm: "POST", htu: TOKEN_ENDPOINT }),
  });
  return { bearerToken: bearer.accessToken, dpopToken: bound.accessToken, dpopKey: key };
}

/** 結果を 1 語にまとめます。200 でも「なぜ通ったか」は別なので分けます */
export function classify(args: { status: number; error: string; bound: boolean }): Outcome {
  if (args.status < 400) return args.bound ? "サーバーが見ていないので通る" : "盗んだだけで通る";
  return args.error === "invalid_token" ? "スキームが違うので通らない" : "鍵が無いので通らない";
}

async function errorOf(res: Response): Promise<string> {
  if (res.status < 400) return "";
  const body = (await res.json()) as Record<string, unknown>;
  return typeof body["error"] === "string" ? body["error"] : "";
}

export async function simulateTheft(victim?: VictimSession): Promise<readonly TheftRow[]> {
  const session = victim ?? (await prepareVictim());
  const bearerApi = createApiApp(); // cnf を見ない（セッション 10）
  const dpopApi = createDpopApi(); // cnf と proof を見る（問題 4）
  const whoami = "http://api-service:4100/api/whoami";
  const summary = apiUrl("/api/summary");
  const orders = apiUrl("/api/orders");
  // 攻撃者も鍵は作れます。ただし被害者の鍵ではありません
  const attackerKey = await createDpopKey();

  const proofFor = async (signer: DpopKey, url: string): Promise<string> =>
    await signer.createProof({ htm: "GET", htu: url, accessToken: session.dpopToken });
  const bearerCall = async (token: string): Promise<Response> =>
    await bearerApi.request(whoami, { headers: { authorization: `Bearer ${token}` } });
  const dpopCall = async (url: string, authorization: string, proof?: string): Promise<Response> =>
    await dpopApi.request(url, {
      headers: proof === undefined ? { authorization } : { authorization, dpop: proof },
    });

  const attempts: ReadonlyArray<{ attempt: string; bound: boolean; run: () => Promise<Response> }> = [
    {
      attempt: "Bearer トークンをそのまま使う",
      bound: false,
      run: async () => await bearerCall(session.bearerToken),
    },
    {
      attempt: "DPoP トークンを cnf を見ない API に持ち込む",
      bound: true,
      run: async () => await bearerCall(session.dpopToken),
    },
    {
      attempt: "DPoP トークンを proof 無しで使う",
      bound: true,
      run: async () => await dpopCall(summary, `DPoP ${session.dpopToken}`),
    },
    {
      attempt: "攻撃者の鍵で proof を作る",
      bound: true,
      run: async () => await dpopCall(summary, `DPoP ${session.dpopToken}`, await proofFor(attackerKey, summary)),
    },
    {
      attempt: "DPoP トークンを Bearer スキームで出す",
      bound: true,
      run: async () => await dpopCall(summary, `Bearer ${session.dpopToken}`, await proofFor(session.dpopKey, summary)),
    },
    {
      attempt: "横取りした proof を別の URL に使い回す",
      bound: true,
      run: async () => await dpopCall(orders, `DPoP ${session.dpopToken}`, await proofFor(session.dpopKey, summary)),
    },
  ];

  const rows: TheftRow[] = [];
  for (const item of attempts) {
    const res = await item.run();
    const error = await errorOf(res);
    rows.push({
      attempt: item.attempt,
      status: res.status,
      error,
      outcome: classify({ status: res.status, error, bound: item.bound }),
    });
  }
  return rows;
}

/** 止まった件数。止まらなかった行は「なぜ」を読み分けます */
export function countStopped(rows: readonly TheftRow[]): number {
  return rows.filter((row) => row.status >= 400).length;
}

export function toMarkdown(rows: readonly TheftRow[]): string {
  const header = "| 試したこと | 応答 | エラー | 結果 |";
  const divider = "| :--- | :--- | :--- | :--- |";
  const body = rows.map((row) => `| ${row.attempt} | ${row.status} | ${row.error || "-"} | ${row.outcome} |`);
  return [header, divider, ...body].join("\n");
}
