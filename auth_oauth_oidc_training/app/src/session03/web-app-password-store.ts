// パスワードの保存と検証。平文のパスワードは「受け取って検証する」瞬間しか存在させません。
// 学習用なので利用者一覧はメモリ上の Map ですが、置き場所が DB になっても考え方は同じです。
import { hash, verify } from "@node-rs/argon2";

export type StoredUser = {
  readonly username: string;
  readonly passwordHash: string;
  readonly roles: readonly string[];
};

export type UserStore = {
  find(username: string): StoredUser | undefined;
};

// アルゴリズムは既定の Argon2id に任せる。ライブラリが公開している Algorithm は
// 型定義が declare const enum のため、本書の tsconfig（verbatimModuleSyntax: true）
// では値として import できない。何が選ばれたかはハッシュ文字列の先頭が
// $argon2id$ であることで確認する（下の実行結果を参照）。
export async function hashPassword(plain: string): Promise<string> {
  return await hash(plain);
}

export async function verifyPassword(passwordHash: string, plain: string): Promise<boolean> {
  try {
    return await verify(passwordHash, plain);
  } catch {
    // ハッシュ文字列が壊れていた場合も「認証失敗」に寄せる（500 にして内部事情を漏らさない）
    return false;
  }
}

export async function createUserStore(): Promise<UserStore> {
  const alice = { username: "alice", passwordHash: await hashPassword("alice-pass"), roles: ["customer"] };
  const bob = { username: "bob", passwordHash: await hashPassword("bob-pass"), roles: ["customer", "staff"] };
  const users = new Map<string, StoredUser>([["alice", alice], ["bob", bob]]);
  return { find: (username) => users.get(username) };
}
