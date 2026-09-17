// 問題5 の確認用ドライバ。Bad な /me と Good な /orders の差を 4 通りの叩き方で見ます。
import { createApiService } from "./api-service-q5-login-check.js";
import { fetchAccessToken } from "../session04/bookstore-endpoints.js";

const api = createApiService();
// 機械（batch-worker）のトークン。人間の alice のものではない
const token = await fetchAccessToken();
const bearer = { authorization: `Bearer ${token}` };

const me = await api.request("/me", { headers: bearer });
console.log("[1] Bad な /me         :", me.status, await me.text());

const anonymous = await api.request("/me");
console.log("[2] トークンなしの /me :", anonymous.status);

const order = await api.request("/orders/order-1001", { headers: bearer });
console.log("[3] Good な /orders    :", order.status, await order.text());

const missing = await api.request("/orders/order-0000", { headers: bearer });
console.log("[4] 存在しない注文     :", missing.status);
