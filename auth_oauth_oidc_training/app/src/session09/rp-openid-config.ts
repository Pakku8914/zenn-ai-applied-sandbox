// RP（web-app）が認可サーバーをどう見るかの設定。
// openid-client の Configuration を 1 つ作って使い回します。
// 定数はセッション 6 の bookstore-client.ts をそのまま再利用します（別名を作らない）。
import * as client from "openid-client";
import { CLIENT_ID, ISSUER_INTERNAL, ISSUER_PUBLIC, REDIRECT_URI, SCOPE } from "../session06/bookstore-client.js";

export { CLIENT_ID, ISSUER_INTERNAL, ISSUER_PUBLIC, REDIRECT_URI, SCOPE };

/** RP 自身が公開されている URL。ブラウザが RP に戻ってくるときに使う名前 */
export const RP_BASE_URL = process.env["RP_BASE_URL"] ?? "http://localhost:3100";
/** ログアウト後にブラウザを戻す先。realm の post.logout.redirect.uris に含まれていること */
export const POST_LOGOUT_REDIRECT_URI = `${RP_BASE_URL}/`;

const INTERNAL_ORIGIN = new URL(ISSUER_INTERNAL).origin; // http://keycloak:8080
const PUBLIC_ORIGIN = new URL(ISSUER_PUBLIC).origin; // http://localhost:8080

let cached: client.Configuration | undefined;

/**
 * discovery で認可サーバーの設定を取得します（1 プロセスにつき 1 回だけ）。
 * ここは「サーバーからサーバー」への通信なので、必ず ISSUER_INTERNAL を使います。
 */
export async function getOpenIdConfig(): Promise<client.Configuration> {
  if (cached !== undefined) {
    return cached;
  }
  cached = await client.discovery(
    new URL(ISSUER_INTERNAL),
    CLIENT_ID,
    undefined, // client_secret は無い（web-app は公開クライアント）
    client.None(), // token_endpoint_auth_method = none
    // 学習用サンドボックスの Keycloak は http で動いているため、既定の HTTPS 必須を外す。
    // 本番では絶対に付けない（付けると平文でトークンが飛ぶ経路を許すことになる）。
    { execute: [client.allowInsecureRequests] },
  );
  return cached;
}

/** コンテナ内向けの URL を、ホスト OS のブラウザが開ける URL に書き換えます（ブラウザは keycloak を知らない） */
export function toBrowserUrl(url: URL): string {
  return url.origin === INTERNAL_ORIGIN ? url.toString().replace(INTERNAL_ORIGIN, PUBLIC_ORIGIN) : url.toString();
}

/**
 * コールバックの URL を「RP が公開されている URL ＋ 受け取ったクエリ」として組み立て直します。
 * openid-client はこの URL から redirect_uri（クエリを除いた部分）を作るため、
 * コンテナやプロキシの内側では、リクエストの URL をそのまま渡してはいけません。
 * iss の付け替えはサンドボックス固有の都合です（ブラウザ経由だと ISSUER_PUBLIC で返るが、同じ認可サーバーの別名）。
 * 本番では認可サーバーのホスト名を 1 つに固定するため、この処理は不要になります（不要にすべきです）。
 */
export function callbackUrl(search: string): URL {
  const url = new URL(`${RP_BASE_URL}/callback`);
  url.search = search;
  if (url.searchParams.get("iss") === ISSUER_PUBLIC) {
    url.searchParams.set("iss", ISSUER_INTERNAL);
  }
  return url;
}
