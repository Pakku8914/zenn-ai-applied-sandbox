// 問題 1 の解答: alice と bob のハッシュを作り、パスワードを総当たりで突き合わせます。
// 実行: docker compose exec app npx tsx src/session03/web-app-q1-hash-matrix.ts
import { pathToFileURL } from "node:url";
import { hashPassword, verifyPassword } from "./web-app-password-store.js";

export type MatrixRow = {
  readonly hashOwner: string;
  readonly passwordOwner: string;
  readonly verified: boolean;
};

export type MatrixResult = {
  readonly rows: readonly MatrixRow[];
  /** 同じ 2 人の salt が違う値になっているか */
  readonly saltsDiffer: boolean;
  /** ハッシュ文字列の長さ（既定パラメータなら 97） */
  readonly hashLength: number;
};

export async function buildMatrix(): Promise<MatrixResult> {
  const credentials = [
    { username: "alice", password: "alice-pass" },
    { username: "bob", password: "bob-pass" },
  ] as const;

  // 利用者ごとにハッシュを 1 つ作る（salt は自動で生成され、ハッシュ文字列に埋め込まれる）
  const hashes = new Map<string, string>();
  for (const credential of credentials) {
    hashes.set(credential.username, await hashPassword(credential.password));
  }

  const rows: MatrixRow[] = [];
  for (const owner of credentials) {
    const passwordHash = hashes.get(owner.username) ?? "";
    for (const attempt of credentials) {
      rows.push({
        hashOwner: owner.username,
        passwordOwner: attempt.username,
        verified: await verifyPassword(passwordHash, attempt.password),
      });
    }
  }

  const aliceHash = hashes.get("alice") ?? "";
  const bobHash = hashes.get("bob") ?? "";
  const saltOf = (hashString: string): string => hashString.split("$")[4] ?? "";

  return {
    rows,
    saltsDiffer: saltOf(aliceHash) !== saltOf(bobHash),
    hashLength: aliceHash.length,
  };
}

async function main(): Promise<void> {
  const result = await buildMatrix();
  console.log("=== ハッシュとパスワードの突き合わせ ===");
  for (const row of result.rows) {
    console.log(`${row.hashOwner} のハッシュ × ${row.passwordOwner} のパスワード → ${row.verified}`);
  }
  console.log(`2 人の salt は異なるか : ${result.saltsDiffer}`);
  console.log(`ハッシュ文字列の長さ : ${result.hashLength}`);
}

// このファイルを直接実行したときだけ結果を表示する（他のファイルから import されたときは何もしない）
const invokedDirectly =
  process.argv[1] !== undefined && import.meta.url === pathToFileURL(process.argv[1]).href;
if (invokedDirectly) {
  await main();
}
