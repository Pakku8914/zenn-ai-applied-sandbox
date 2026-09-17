/**
 * 計測と検証のための材料
 *
 *   createBulkyStore() : 現実によくある「かさばるデータ」を再現したストア
 *   createBudgetApi()  : 会計システムの予算照会 API を模した外部依存（障害を注入できる）
 *
 * どちらも決定的です（何度実行しても同じ結果になります）。
 * ランダム性を入れると計測値が毎回変わり、Bad / Good の比較ができなくなります。
 */
import {
  createStore,
  type Category,
  type Status,
  type Store,
  type WorkflowRequest,
} from "../session10/data.js";

const CATEGORY_CYCLE: readonly Category[] = ["expense", "purchase", "leave", "travel"];
const STATUS_CYCLE: readonly Status[] = ["draft", "in_review", "approved", "rejected"];
const APPLICANTS: readonly string[] = ["佐藤 花子", "鈴木 一郎", "田中 実"];

const PARAGRAPHS: readonly string[] = [
  "研修の内容は提案書作成の演習が中心で、初日は現状分析の手法、二日目はロールプレイと相互レビューを行います。",
  "参加によって提案書のレビュー工数を月あたり 8 時間削減できる見込みで、投資回収は 3 か月と見積もっています。",
  "見積書は添付のとおりです。早期申込割引の適用期限が今月末なので、それまでに決裁をいただきたいです。",
  "受講後は社内共有会を 1 回開催し、資料を全社のドキュメント基盤に登録して横展開します。",
];

/** 1,000 文字前後の本文を決定的に組み立てる */
function longBody(): string {
  const lines: string[] = [];
  for (let index = 0; index < 18; index++) {
    lines.push(`${index + 1}. ${PARAGRAPHS[index % PARAGRAPHS.length] ?? ""}`);
  }
  return lines.join("\n");
}

/**
 * かさばるストアを作る。
 *   ① req-1003 を「本文が長く、コメントと履歴が積み上がった申請」にする
 *   ② 一覧が上限に当たるように 25 件を追加する（合計 30 件）
 */
export function createBulkyStore(): Store {
  const store = createStore();

  const target = store.requests.get("req-1003");
  if (target !== undefined) {
    target.body = longBody();
    for (let index = target.comments.length; index < 24; index++) {
      target.comments.push({
        id: `c-${String(index + 1).padStart(2, "0")}`,
        authorId: index % 2 === 0 ? "u-900" : "u-001",
        body: `補足 ${index + 1}: 見積の内訳と受講日程について確認しました。`,
        postedAt: `2026-08-18T${String(9 + (index % 10)).padStart(2, "0")}:00:00.000Z`,
      });
    }
    for (let index = target.history.length; index < 30; index++) {
      target.history.push({
        at: `2026-08-18T${String(9 + (index % 10)).padStart(2, "0")}:30:00.000Z`,
        actorId: index % 2 === 0 ? "u-001" : "u-900",
        action: "commented",
        note: "",
      });
    }
    for (let index = target.attachments.length; index < 4; index++) {
      target.attachments.push({
        id: `a-${String(index + 1).padStart(2, "0")}`,
        fileName: `estimate-${index + 1}.pdf`,
        sizeBytes: 84_213 + index * 1_024,
        uri: `https://intra.example.com/files/a-${String(index + 1).padStart(2, "0")}`,
      });
    }
  }

  for (let index = 0; index < 25; index++) {
    const id = `req-${1010 + index}`;
    const category = CATEGORY_CYCLE[index % CATEGORY_CYCLE.length] ?? "expense";
    const status = STATUS_CYCLE[index % STATUS_CYCLE.length] ?? "draft";
    const amountYen = 3_000 + index * 1_500;
    const request: WorkflowRequest = {
      id,
      title: `${category} の定例申請（${index + 1} 件目）`,
      category,
      amountYen,
      applicantId: `u-00${(index % 3) + 1}`,
      applicantName: APPLICANTS[index % APPLICANTS.length] ?? "佐藤 花子",
      department: index % 2 === 0 ? "営業部" : "開発部",
      status,
      body: `定例の申請です。内訳は明細のとおりで、金額は ${amountYen} 円です。`,
      createdAt: "2026-08-15T00:00:00.000Z",
      updatedAt: `2026-08-15T0${index % 10}:00:00.000Z`,
      approvals: [
        {
          order: 1,
          approverId: "u-900",
          approverName: "山田 課長",
          state:
            status === "approved" ? "approved" : status === "rejected" ? "rejected" : "pending",
          decidedAt: status === "draft" || status === "in_review" ? null : "2026-08-16T00:00:00.000Z",
        },
      ],
      comments: [],
      attachments: [],
      history: [{ at: "2026-08-15T00:00:00.000Z", actorId: "u-001", action: "created", note: "" }],
    };
    store.requests.set(id, request);
  }
  store.nextNumber = 1040;
  return store;
}

export type BudgetCheck = { remainingYen: number };
export type BudgetApi = {
  check: (category: Category, amountYen: number) => Promise<BudgetCheck>;
};

/**
 * 予算照会 API（擬似）。failures 回だけ接続エラーを起こしてから成功します。
 *
 * 例外メッセージに内部ホスト名・内部パス・トークンの断片を入れてあります。
 * 「これをそのまま返すと何が漏れるか」を実験するためです（本文 4 節）。
 */
export function createBudgetApi(options: { failures?: number } = {}): BudgetApi {
  let remainingFailures = options.failures ?? 0;
  return {
    async check(_category, amountYen) {
      if (remainingFailures > 0) {
        remainingFailures -= 1;
        throw new Error(
          "connect ECONNREFUSED 10.0.12.4:8443 (POST /internal/budget/v2/check, token=svc_budget_9f2a...)",
        );
      }
      return { remainingYen: Math.max(0, 300_000 - amountYen) };
    },
  };
}
