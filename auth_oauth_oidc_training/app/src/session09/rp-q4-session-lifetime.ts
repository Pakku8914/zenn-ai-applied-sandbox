// 問題 4 の解答。RP のセッションに 2 本の期限（アイドル・絶対）を効かせ、
// 時計を差し込んで進めることで、実時間を待たずに挙動を確かめます。
import { RpSessionStore } from "./rp-session-store.js";
import type { AuthenticatedUser, StoredTokens } from "./rp-session-store.js";

const USER: AuthenticatedUser = { sub: "alice-sub", username: "alice", name: "Alice" };
const TOKENS: StoredTokens = {
  accessToken: "（検証用のダミー）",
  refreshToken: "（検証用のダミー）",
  idToken: "（検証用のダミー）",
  accessTokenExpiresAt: 0,
};

export type LifetimeStep = { label: string; elapsedMinutes: number; alive: boolean };
export type Experiment = { name: string; steps: LifetimeStep[] };

/** ログイン済みのセッションを 1 つ作り、時計を進めながら生存を確かめる */
function runScenario(name: string, advances: number[], options: { idleMinutes: number; absoluteMinutes: number }): Experiment {
  let now = Date.UTC(2026, 8, 12, 0, 0, 0); // 固定の時刻から始める（結果を毎回同じにする）
  const store = new RpSessionStore({
    idleTimeoutMs: options.idleMinutes * 60_000,
    absoluteTimeoutMs: options.absoluteMinutes * 60_000,
    now: () => now,
  });
  const started = store.startLogin({ state: "s", nonce: "n", codeVerifier: "v" });
  const loggedIn = store.completeLogin(started.id, { user: USER, tokens: TOKENS });

  const steps: LifetimeStep[] = [];
  let elapsed = 0;
  for (const minutes of advances) {
    now += minutes * 60_000;
    elapsed += minutes;
    steps.push({
      label: `${minutes} 分あけてアクセス`,
      elapsedMinutes: elapsed,
      alive: store.get(loggedIn.id) !== undefined,
    });
  }
  return { name, steps };
}

export function runLifetimeExperiments(): Experiment[] {
  return [
    // アイドル 30 分・絶対 12 時間。使い続けている間は切れないが、31 分放置すると切れる
    runScenario("アイドル期限（30 分）", [20, 20, 31], { idleMinutes: 30, absoluteMinutes: 720 }),
    // アイドル 30 分・絶対 1 時間。20 分おきに使い続けても、1 時間を過ぎれば切れる
    runScenario("絶対期限（1 時間）", [20, 20, 20, 20], { idleMinutes: 30, absoluteMinutes: 60 }),
  ];
}
