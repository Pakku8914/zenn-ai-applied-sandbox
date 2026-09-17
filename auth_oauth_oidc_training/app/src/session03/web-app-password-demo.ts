// Argon2id で作ったハッシュ文字列の中身を観察します。
// 実行: docker compose exec app npx tsx src/session03/web-app-password-demo.ts
import { hashPassword, verifyPassword } from "./web-app-password-store.js";

const hashString = await hashPassword("alice-pass");
// "$argon2id$v=19$m=19456,t=2,p=1$<salt>$<hash>" を "$" で分解する
const parts = hashString.split("$");

console.log(hashString.length); // 97
console.log(parts[1] ?? ""); // argon2id
console.log(parts[3] ?? ""); // m=19456,t=2,p=1
console.log((parts[4] ?? "").length); // 22（salt）
console.log((parts[5] ?? "").length); // 43（ハッシュ値）
console.log(await verifyPassword(hashString, "alice-pass")); // true
console.log(await verifyPassword(hashString, "alice-pas")); // false
console.log(hashString === (await hashPassword("alice-pass"))); // false（salt が毎回変わる）
