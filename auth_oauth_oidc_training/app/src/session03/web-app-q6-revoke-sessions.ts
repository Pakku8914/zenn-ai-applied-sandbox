// 問題 6 の解答: 「全端末からログアウト」をセッション方式で実装します。
// 実行: docker compose exec app npx tsx src/session03/web-app-q6-revoke-sessions.ts
import { pathToFileURL } from "node:url";
import { SessionStore } from "./web-app-session-store.js";

export class RevocableSessionStore extends SessionStore {
  /** 指定した利用者のセッションをすべて失効させ、消した件数を返す */
  revokeAllOf(username: string): number {
    let revoked = 0;
    // Map は反復中の delete が許されている（削除済みの要素は以降の反復に現れない）
    for (const [id, record] of this.sessions) {
      if (record.username === username) {
        this.sessions.delete(id);
        revoked += 1;
      }
    }
    return revoked;
  }

  /** ある利用者が現在いくつの端末からログインしているか */
  countOf(username: string): number {
    let count = 0;
    for (const record of this.sessions.values()) {
      if (record.username === username) {
        count += 1;
      }
    }
    return count;
  }
}

function main(): void {
  const store = new RevocableSessionStore();
  // alice が PC・スマホ・タブレットの 3 端末からログインしている状態を作る
  const alicePc = store.create("alice");
  const alicePhone = store.create("alice");
  const aliceTablet = store.create("alice");
  const bobPc = store.create("bob");

  console.log("=== 全端末からログアウト ===");
  console.log(`失効前の alice のセッション数 : ${store.countOf("alice")}`);
  console.log(`失効させた件数 : ${store.revokeAllOf("alice")}`);
  console.log(`失効後の alice のセッション数 : ${store.countOf("alice")}`);
  console.log(`PC のセッションは使えるか : ${store.get(alicePc.id) !== undefined}`);
  console.log(`スマホのセッションは使えるか : ${store.get(alicePhone.id) !== undefined}`);
  console.log(`タブレットのセッションは使えるか : ${store.get(aliceTablet.id) !== undefined}`);
  console.log(`bob のセッションは残っているか : ${store.get(bobPc.id) !== undefined}`);
}

const invokedDirectly =
  process.argv[1] !== undefined && import.meta.url === pathToFileURL(process.argv[1]).href;
if (invokedDirectly) {
  main();
}
