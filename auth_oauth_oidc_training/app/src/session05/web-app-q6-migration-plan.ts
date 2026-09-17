// 練習問題 6 の解答。
// 実行: docker compose exec app npx tsx src/session05/web-app-q6-migration-plan.ts
// 既存コードで見つけた「古いフロー」を、移行先と最初の一手に対応づけて表示します。
import { chooseFlow } from "./web-app-flow-chooser.js";
import type { LegacyFlowId, Situation } from "./web-app-flow-chooser.js";

/** OAuth 2.1 で削除されたフロー */
const REMOVED_FLOWS: readonly LegacyFlowId[] = ["implicit", "ropc"];

type Finding = {
  /** 既存コードで見つけた記述 */
  readonly found: string;
  /** その正体 */
  readonly legacyFlow: LegacyFlowId;
  /** 当時なぜそう書かれたのか */
  readonly whyThen: string;
  /** そのアプリの今の条件 */
  readonly situation: Situation;
  /** 移行の最初の一手 */
  readonly firstStep: string;
};

const FINDINGS: readonly Finding[] = [
  {
    found: "SPA が response_type=token で認可リクエストを投げ、location.hash からトークンを拾っている",
    legacyFlow: "implicit",
    whyThen: "ブラウザから別ドメインの POST が難しく、トークンエンドポイントを直接叩けなかった",
    situation: {
      label: "書店のフロント（ブラウザで動く web-app）",
      userPresent: true,
      hasBrowser: true,
      canKeepSecret: false,
    },
    firstStep: "response_type を code に変え、PKCE（S256）を付ける",
  },
  {
    found: "モバイルアプリが入力されたユーザー名とパスワードを自社 API に POST している",
    legacyFlow: "ropc",
    whyThen: "アプリ内でログイン画面を作れるので、ブラウザに切り替えずに済ませたかった",
    situation: {
      label: "書店のスマートフォンアプリ（OS の外部ブラウザを開ける）",
      userPresent: true,
      hasBrowser: true,
      canKeepSecret: false,
    },
    firstStep: "OS の外部ブラウザでログイン画面を開き、認可コード + PKCE に置き換える",
  },
  {
    found: "夜間バッチが管理者アカウントのパスワードを設定ファイルに書いてログインしている",
    legacyFlow: "ropc",
    whyThen: "「人間のアカウントを使い回す」以外の方法を知らなかった",
    situation: {
      label: "夜間バッチ（batch-worker）",
      userPresent: false,
      hasBrowser: false,
      canKeepSecret: true,
    },
    firstStep: "バッチ専用の機密クライアントを登録し、Client Credentials に置き換える",
  },
];

console.log("=== 既存コードの棚卸しと移行計画 ===");
for (const finding of FINDINGS) {
  const removed = REMOVED_FLOWS.includes(finding.legacyFlow);
  console.log(`■ ${finding.found}`);
  console.log(`  正体: ${finding.legacyFlow}（${removed ? "OAuth 2.1 で削除" : "現役"}）`);
  console.log(`  当時の事情: ${finding.whyThen}`);
  console.log(`  移行先: ${chooseFlow(finding.situation).flow}`);
  console.log(`  最初の一手: ${finding.firstStep}`);
}
