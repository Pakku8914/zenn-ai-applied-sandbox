// 最終プロジェクト final01: 夜間バッチ（batch-worker）。
// 利用者が 1 人も関わらない経路です（セッション 13 の Client Credentials）。
// ブラウザもログイン画面も出てきません。リフレッシュトークンも返りません。
import { callApi, defaultApiFetch } from "../mid01/mid01-api-client.js";
import type { ApiFetch } from "../mid01/mid01-api-client.js";
import { requestClientCredentials } from "../session13/batch-worker-client.js";

export type BatchOptions = {
  /** api-service への問い合わせ口。検証では Hono の app.request を差し込みます */
  apiFetch?: ApiFetch;
  log?: (line: string) => void;
};

export type BatchResult = {
  readonly tokenStatus: number;
  /** トークンレスポンスのキー（refresh_token が無いことを確かめるため） */
  readonly tokenKeys: readonly string[];
  readonly hasRefreshToken: boolean;
  readonly reportStatus: number;
  readonly totalAmount: number;
  readonly orderCount: number;
  readonly canceledCount: number;
};

type ReportPayload = {
  report?: {
    totalAmount?: number;
    orderCount?: number;
    canceledCount?: number;
    byStore?: Array<{ storeId: string; amount: number; orderCount: number }>;
  };
};

/**
 * 毎晩 1 回だけ動く集計。
 * 「誰の代理でもない」ので、自分の資格情報でトークンを取り、そのまま api-service を呼びます。
 * 利用者のトークンを借りて動かしてはいけません（利用者がログアウトすると止まり、
 * 止まらないようにすると利用者が辞めたあとも権限が生き続けます）。
 */
export async function runNightlyBatch(options: BatchOptions = {}): Promise<BatchResult> {
  const apiFetch = options.apiFetch ?? defaultApiFetch;
  const log = options.log ?? ((): void => undefined);

  // 1. 自分を名乗ってトークンを取る（秘密を Authorization ヘッダに置く client_secret_basic）
  const token = await requestClientCredentials({ method: "client_secret_basic" });
  log(`[batch-worker] トークンを取得しました（refresh_token: ${token.hasRefreshToken ? "あり" : "なし"}）`);

  // 2. 集計を取りに行く。付けるヘッダは利用者のときとまったく同じ Authorization: Bearer
  const res = await callApi(apiFetch, "/reports/daily", token.accessToken);
  const body: ReportPayload = res.status === 200 ? ((await res.json()) as ReportPayload) : {};
  const report = body.report;
  for (const store of report?.byStore ?? []) {
    log(`[batch-worker] ${store.storeId}: ${store.amount} 円 / ${store.orderCount} 件`);
  }

  // 3. トークンはここで捨てる（変数の寿命が尽きる）。ファイルにも DB にも書かない
  return {
    tokenStatus: token.status,
    tokenKeys: token.keys,
    hasRefreshToken: token.hasRefreshToken,
    reportStatus: res.status,
    totalAmount: report?.totalAmount ?? -1,
    orderCount: report?.orderCount ?? -1,
    canceledCount: report?.canceledCount ?? -1,
  };
}
