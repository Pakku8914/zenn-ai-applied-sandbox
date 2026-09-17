// 中間プロジェクト mid01: web-app が api-service を呼ぶための口。
// アクセストークンを外に出す場所をこのファイルだけに閉じ込めます（どこから漏れるかを 1 か所で追えるように）。

/** api-service の場所。同じコンテナの中で 2 つのサーバーを動かすので localhost で届きます */
export const API_BASE_URL = process.env["API_BASE_URL"] ?? "http://localhost:4100";

/**
 * api-service への問い合わせ口。
 * 既定は本物の HTTP ですが、検証では Hono の app.request を差し込みます
 * （実ポートを掴まずに、Authorization ヘッダが境界を越える様子をそのまま確かめられます）。
 */
export type ApiFetch = (path: string, init: { headers: Record<string, string> }) => Promise<Response>;

export const defaultApiFetch: ApiFetch = (path, init) => fetch(`${API_BASE_URL}${path}`, init);

/** api-service が返す注文 1 件の形（web-app 側から見た契約） */
export type ApiOrder = {
  orderId: string;
  title: string;
  amount: number;
  status: string;
  storeId: string;
};

export type ApiOrdersPayload = {
  owner: string;
  count: number;
  totalAmount: number;
  orders: ApiOrder[];
};

export type ApiOrderPayload = { order: ApiOrder };

export type ApiErrorPayload = { error?: string; reason?: string };

/**
 * アクセストークンを Authorization ヘッダに載せて api-service を呼びます。
 * 「Bearer」は持参人式の切符という意味で、持っている人を持ち主として扱うという宣言です。
 */
export async function callApi(apiFetch: ApiFetch, path: string, accessToken: string): Promise<Response> {
  return await apiFetch(path, {
    headers: {
      authorization: `Bearer ${accessToken}`,
      accept: "application/json",
    },
  });
}
