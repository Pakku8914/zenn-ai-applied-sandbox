// セッション 7 の練習問題の解答（問題 1〜7）の自己検証。
// realm の設定は一切書き換えません（設定を変える実験は admin-*-experiment.ts が担当）。
import { buildLifetimeRows, buildLifetimeTable } from "./rp-q1-lifetime-table.js";
import { buildRefreshReport } from "./rp-q2-refresh-report.js";
import { runExpiryDrill } from "./rp-q3-expiry-drill.js";
import { buildReuseReport } from "./rp-q4-reuse-report.js";
import { buildScopeDesignReport } from "./rp-q5-scope-design.js";
import { buildOfflineReport } from "./rp-q6-offline-report.js";
import { T0, TokenClient, expiredTokenSet, runConcurrencyDrill } from "./rp-q7-token-client.js";
import { toTokenSet } from "./rp-token-store.js";

let failures = 0;
function check(label: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`${ok ? "OK  " : "NG  "} ${label}`);
  if (!ok) {
    console.log(`     実際:   ${JSON.stringify(actual)}`);
    console.log(`     期待値: ${JSON.stringify(expected)}`);
    failures += 1;
  }
}

// 問題 1: 寿命の比較表
check(
  "問題 1 の計算結果",
  buildLifetimeRows().map((row) => [row.lifespanSeconds, row.refreshesPerShift]),
  [
    [60, 959],
    [300, 106],
    [900, 33],
    [3600, 8],
    [86_400, 0],
  ],
);
check("問題 1 のレポート", buildLifetimeTable(), [
  "=== アクセストークンの寿命の比較 ===",
  "寿命 60 秒: 失効が効くまで最大 60 秒 / 8 時間あたりのリフレッシュ 959 回",
  "寿命 300 秒: 失効が効くまで最大 300 秒 / 8 時間あたりのリフレッシュ 106 回",
  "寿命 900 秒: 失効が効くまで最大 900 秒 / 8 時間あたりのリフレッシュ 33 回",
  "寿命 3600 秒: 失効が効くまで最大 3600 秒 / 8 時間あたりのリフレッシュ 8 回",
  "寿命 86400 秒: 失効が効くまで最大 86400 秒 / 8 時間あたりのリフレッシュ 0 回",
  "本書の realm の accessTokenLifespan: 300 秒",
  "本書の realm の ssoSessionIdleTimeout: 1800 秒",
  "300 秒を選ぶ理由: 失効の遅れを 5 分に抑えつつ、リフレッシュは 8 時間で 106 回に収まる",
  "寿命を伸ばすと悪くなるもの: 失効の効き（取り消しても最大 1 日使われる）",
  "寿命を縮めると悪くなるもの: 認可サーバーへの通信量と、更新失敗の影響範囲",
]);

// 問題 2: リフレッシュの前後の点検
check("問題 2 のレポート", await buildRefreshReport(), [
  "=== リフレッシュトークンの点検 ===",
  "リフレッシュトークンの typ: Refresh",
  "クレームの数: 12",
  "クレームの一覧: aud, aud_x, azp, exp, iat, iss, jti, prov, scope, sid, sub, typ",
  "Keycloak 独自のクレーム: aud_x, prov",
  "アクセストークンの有効期間: 300 秒",
  "リフレッシュトークンの有効期間: 1800 秒",
  "更新後のアクセストークンの有効期間: 300 秒",
  "更新後のリフレッシュトークンの有効期間: 1800 秒",
  "jti は変わった: true",
  "sub は変わらない: true",
  "sid は変わらない: true",
  "scope は同じ集合: true",
  "Client Credentials で refresh_token が返るか: false",
]);

// 問題 3: 期限判定の境界値
check("問題 3 のドリル", runExpiryDrill(), [
  "=== 期限判定のドリル ===",
  "1. 受け取った直後: needsRefresh=false canRefresh=true 残り 300 秒",
  "2. 期限の 31 秒前: needsRefresh=false",
  "3. 期限の 30 秒前: needsRefresh=true",
  "4. 期限ちょうど: needsRefresh=true",
  "5. 期限の 1 秒後: needsRefresh=true 残り -1 秒",
  "6. 前倒しを 0 秒にして期限の 1 秒前: needsRefresh=false",
  "7. refresh の期限の 1 秒前: canRefresh=true",
  "8. refresh の期限ちょうど: canRefresh=false",
  "9. refresh_token が空: canRefresh=false",
  "10. expires_in をミリ秒と取り違えた: 残り 0 秒",
  "11. refresh_token が返らない応答: 手元の値を引き継ぐ=true",
]);

// 問題 4: 旧リフレッシュトークンの再利用
check("問題 4 のレポート", await buildReuseReport(), [
  "=== リフレッシュトークンの再利用を確かめる ===",
  "1 回目のリフレッシュ: 成功（新しい refresh_token を受け取った: true）",
  "新旧の jti は別物: true",
  "旧リフレッシュトークンの 2 回目の使用: 成功してしまう（HTTP 200 / expires_in=300）",
  "同じ旧トークンの 3 回目の使用: 成功してしまう（HTTP 200 / expires_in=300）",
  "いまの realm: ローテーションしていない（revokeRefreshToken が無効）",
  "ローテーションを有効にする設定: revokeRefreshToken=true / refreshTokenMaxReuse=0",
  "有効にしたときの想定: 旧トークンの再利用は HTTP 400 invalid_grant で拒否される",
  "再利用検知で分かること: 盗まれたトークンが使われた可能性（セッションを切るべき兆候）",
]);

// 問題 5: スコープ設計
check("問題 5 のレポート", await buildScopeDesignReport(), [
  "=== スコープ設計の点検 ===",
  "本の一覧を見る: （スコープ不要）",
  "自分の注文を見る: orders:read",
  "注文する: orders:write",
  "全員の注文を見る: orders:read:all",
  "在庫を書き換える: inventory:write",
  "画面が要求するスコープ: openid orders:read orders:write",
  "orders:read だけで「注文する」を呼ぶと足りないもの: orders:write",
  "機能の数: 5 / スコープの数: 4",
  "1 機能 1 スコープになっていない: true",
  "読み取りと書き込みが混ざったスコープ: 0 件",
  "書き込みを許すスコープ: orders:write inventory:write",
  "要求した文字列: openid profile email",
  "付与された文字列: openid email profile",
  "並び順は違うが集合としては同じ: true",
  "正規化するとどちらも: email openid profile",
  "設計した orders:* は realm にまだ無い（付与されていない）: true",
]);

// 問題 6: offline_access
check("問題 6 のレポート", await buildOfflineReport(), [
  "=== offline_access を確かめる ===",
  "offline_access を要求した結果: HTTP 400 not_allowed / Offline tokens not allowed for the user or client",
  "通常のリフレッシュトークンの typ: Refresh",
  "通常のリフレッシュトークンの有効期間: 1800 秒",
  "リフレッシュするとアイドル期限は延びる: true",
  "1800 秒のあいだ 1 度もリフレッシュしなければ: 使えなくなる（再ログインが必要）",
  "offline_access が必要な例: 利用者が居ない時間に動く定期処理（夜間バッチ・定期同期）",
  "offline_access を避ける例: 画面を操作している利用者のためのログイン",
  "有効化に必要なもの: 利用者に offline_access ロール（realm ロール）を割り当てる",
  "Client Credentials との違い: 利用者の許可を受けた権限かどうか",
]);

// 問題 7: 同時アクセスでもリフレッシュは 1 回
check("問題 7 のドリル", await runConcurrencyDrill(), [
  "=== 同時アクセス時のリフレッシュ回数 ===",
  "同時に 10 本が要求したときのリフレッシュ回数: 1",
  "10 本すべてが同じアクセストークンを受け取った: true",
  "受け取ったアクセストークン: access-1",
  "更新直後の要求でリフレッシュは増えない: true",
  "refresh も切れていたとき: リフレッシュトークンも使えません。もう一度ログインしてもらってください",
  "そのとき認可サーバーを呼んでいない: true",
]);

// 問題 7 の補足 1: 失敗は待ち合わせていた全員に伝わり、次の要求では新しい更新を始められる
const failing = new TokenClient(expiredTokenSet(), {
  refresh: async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
    throw new Error("認可サーバーに届きませんでした");
  },
});
const failures2 = await Promise.allSettled([
  failing.getAccessToken(T0 + 300_000),
  failing.getAccessToken(T0 + 300_000),
]);
check("問題 7: 失敗は 2 本ともに伝わる", failures2.map((r) => r.status), ["rejected", "rejected"]);
check("問題 7: 失敗しても呼んだ回数は 1 回", failing.refreshCount, 1);
const retried = await Promise.allSettled([failing.getAccessToken(T0 + 300_000)]);
check("問題 7: 失敗後も新しい更新を始められる", failing.refreshCount, 2);
check("問題 7: その結果も失敗する", retried[0]?.status, "rejected");

// 問題 7 の補足 2: 期限内なら認可サーバーを 1 度も呼ばない
const fresh = new TokenClient(
  toTokenSet(
    { access_token: "access-fresh", refresh_token: "refresh-fresh", expires_in: 300, refresh_expires_in: 1800 },
    { now: Date.now() },
  ),
  {
    refresh: () => {
      throw new Error("呼ばれてはいけません");
    },
  },
);
check("問題 7: 期限内は認可サーバーを呼ばない", await fresh.getAccessToken(), "access-fresh");
check("問題 7: そのときのリフレッシュ回数", fresh.refreshCount, 0);

console.log(
  failures === 0
    ? "\nセッション 7 の練習問題（1〜7）の検証にすべて成功しました。"
    : `\n${failures} 件の検証に失敗しました。`,
);
process.exit(failures === 0 ? 0 : 1);
