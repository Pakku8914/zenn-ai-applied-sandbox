// 練習問題 4: コールバックを 4 通りに判定する。判定の順序が守られていることを確かめる。
import type { CallbackFailureReason } from "./rp-authorize.js";
import { CallbackError, PendingLoginStore } from "./rp-authorize.js";

export type CallbackJudgement = {
  kind: "受理" | "認可サーバーのエラー" | "state 不一致" | "認可コードなし";
  detail: string;
};

/** 失敗の理由をそのまま日本語のラベルに移します（メッセージの文面では分岐しません） */
const KIND_BY_REASON: Record<CallbackFailureReason, CallbackJudgement["kind"]> = {
  authorization_error: "認可サーバーのエラー",
  state_mismatch: "state 不一致",
  missing_code: "認可コードなし",
};

export function judgeCallback(store: PendingLoginStore, params: URLSearchParams): CallbackJudgement {
  try {
    const { code } = store.consumeCallback(params);
    return { kind: "受理", detail: `認可コード ${code.length} 文字` };
  } catch (err) {
    // 想定していない例外を「判定結果」に化けさせないため、型で絞ってから扱います
    if (!(err instanceof CallbackError)) throw err;
    return { kind: KIND_BY_REASON[err.reason], detail: err.message };
  }
}

export function runCallbackDrill(): string[] {
  const lines = ["=== コールバックの判定ドリル ==="];
  const store = new PendingLoginStore();

  const mine = store.start();
  const myCallback = new URLSearchParams({ state: mine.state, code: "code-aaaa" });
  lines.push(`1. 自分が始めたログイン: ${judgeCallback(store, myCallback).kind}`);
  lines.push(`2. 同じコールバックの 2 回目: ${judgeCallback(store, myCallback).kind}`);
  lines.push(
    `3. state が無い: ${judgeCallback(store, new URLSearchParams({ code: "code-bbbb" })).kind}`,
  );
  lines.push(
    `4. 知らない state: ${
      judgeCallback(store, new URLSearchParams({ state: "attacker-state", code: "code-cccc" })).kind
    }`,
  );

  const noCode = store.start();
  lines.push(
    `5. state は一致するが code が無い: ${
      judgeCallback(store, new URLSearchParams({ state: noCode.state })).kind
    }`,
  );

  const denied = store.start();
  lines.push(
    `6. error 付きで戻ってきた: ${
      judgeCallback(
        store,
        new URLSearchParams({
          state: denied.state,
          error: "access_denied",
          error_description: "利用者が拒否しました",
        }),
      ).kind
    }`,
  );

  // 6 はエラーを見た時点で戻るので state を消していません（期限切れで掃除する必要がある）
  lines.push(`保管に残っている未完了ログイン: ${store.size} 件`);
  return lines;
}

// 直接実行したときだけ表示します（verify から import しても二重に走らせないためのガード）
if (process.argv.some((arg) => arg.includes("rp-q4-callback-guard"))) {
  for (const line of runCallbackDrill()) console.log(line);
}
