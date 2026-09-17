// 実行: docker compose exec app npx tsx src/session04/api-service-demo-decode.ts
// 鍵を 1 つも使わずに、トークンの中身が読めることを確かめます。
import { fetchAccessToken } from "./bookstore-endpoints.js";
import { decodeParts } from "./api-service-jwt-parts.js";

const { header, payload } = decodeParts(await fetchAccessToken());
console.log(JSON.stringify(header, null, 2));
console.log(JSON.stringify(payload, null, 2));
