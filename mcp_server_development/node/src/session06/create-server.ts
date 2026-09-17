/**
 * チーム稼働ダッシュボード ― サーバー定義（セッション6 版）
 *
 * 公開するもの
 *   リソース    : dashboard://summary/current（静的・購読可能）
 *   テンプレート: glossary://{term} / report://weekly/{period}.csv / report://excel/{period}.csv
 *   プロンプト  : weekly_report_draft
 *   ツール      : export_report（セッション5 から改修）/ add_work_log（新規）
 *
 * トランスポートへの接続はここでは行いません（server.ts の責務）。
 */
import { completable } from "@modelcontextprotocol/sdk/server/completable.js";
import { McpServer, ResourceTemplate } from "@modelcontextprotocol/sdk/server/mcp.js";
import {
  ErrorCode,
  McpError,
  SubscribeRequestSchema,
  UnsubscribeRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";

import {
  DASHBOARD_FROM,
  DASHBOARD_TO,
  MAX_INLINE_BYTES,
  MAX_RANGE_DAYS,
  TERM_SLUG_PATTERN,
  addWorkLog,
  buildReportRows,
  byteSizeOf,
  completeTermSlugs,
  daysBetween,
  findMember,
  findProject,
  findTerm,
  formatPeriod,
  getDashboardSnapshot,
  listExportedPeriods,
  listWeekStarts,
  parsePeriod,
  recordExportedPeriod,
  renderTermMarkdown,
  sumHours,
  toCsv,
  toExcelCsv,
  toUtf16Base64,
  weekEndOf,
} from "./data.js";

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const MEMBER_ID_PATTERN = /^m-\d{3}$/;
const PROJECT_ID_PATTERN = /^p-[a-z-]{2,32}$/;

/** 購読できる URI。ここに載っていない URI の購読は拒否します */
export const SUMMARY_URI = "dashboard://summary/current";
const GLOSSARY_TEMPLATE = "glossary://{term}";
const WEEKLY_TEMPLATE = "report://weekly/{period}.csv";
const EXCEL_TEMPLATE = "report://excel/{period}.csv";

export function createDashboardServer(): McpServer {
  // 購読（resources/subscribe）に対応するには、ケイパビリティを自分で宣言する必要があります。
  // registerResource() が自動で宣言してくれるのは listChanged までです。
  const server = new McpServer(
    { name: "team-dashboard", version: "0.3.0" },
    { capabilities: { resources: { subscribe: true, listChanged: true } } },
  );

  // 購読しているクライアントの URI 集合。
  // stdio では「1 プロセス = 1 接続」なのでクロージャに持って問題ありません。
  // HTTP で 1 プロセスが複数セッションを持つ場合はセッション単位に持ちます（セッション7）。
  const subscribedUris = new Set<string>();

  registerSummaryResource(server);
  registerGlossaryResource(server);
  registerReportResources(server);
  registerWeeklyReportPrompt(server);
  registerTools(server, subscribedUris);
  registerSubscriptionHandlers(server, subscribedUris);

  return server;
}

/**
 * 静的リソース ―― URI が 1 つに固定されているリソース。
 *
 * registerResource の 4 引数は次の意味です。
 *   ① name    : 機械的な識別子（ツールの name と同じ考え方。変えない前提で決める）
 *   ② uri     : このリソースを指す URI
 *   ③ metadata: title / description / mimeType など、一覧に載る情報
 *   ④ callback: resources/read が来たときに中身を組み立てる関数
 */
function registerSummaryResource(server: McpServer): void {
  server.registerResource(
    "dashboard_summary",
    SUMMARY_URI,
    {
      title: "チーム稼働サマリー（最新）",
      description:
        "チーム全体の稼働時間の集計結果です。" +
        `対象期間は ${DASHBOARD_FROM} 〜 ${DASHBOARD_TO} に固定しています。` +
        "稼働記録が追加されると内容が変わるため、resources/subscribe で更新通知を受け取れます。",
      mimeType: "application/json",
    },
    async (uri) => {
      const snapshot = getDashboardSnapshot();
      return {
        contents: [
          {
            // どの URI の内容かを必ず添える（複数件返す場合の対応付けに使われます）
            uri: uri.href,
            mimeType: "application/json",
            text: JSON.stringify(snapshot, null, 2),
          },
        ],
      };
    },
  );
}

/**
 * リソーステンプレート ―― URI の「作り方」を公開する。
 *
 * ResourceTemplate の第 2 引数で、テンプレート固有の 2 つの振る舞いを決めます。
 *   list    : resources/list に具体的な URI を並べるか（undefined なら並べない）
 *   complete: 変数ごとの補完候補を返す関数（completion/complete で呼ばれる）
 */
function registerGlossaryResource(server: McpServer): void {
  server.registerResource(
    "glossary_term",
    new ResourceTemplate(GLOSSARY_TEMPLATE, {
      // 用語が増えても一覧が膨らまないように、あえて列挙しません。
      // 候補は補完（下の complete）で見つけてもらう設計です。
      list: undefined,
      complete: {
        // 変数名がキー。値は「ユーザーが入力途中の文字列」を受け取って候補を返す関数
        term: (value) => completeTermSlugs(value),
      },
    }),
    {
      title: "社内用語辞書",
      description:
        "社内用語 1 件の定義を Markdown で返します。" +
        "term には英小文字・数字・ハイフンからなるスラッグを指定します（例: sprint）。" +
        "指定できる値は completion/complete で取得できます。",
      mimeType: "text/markdown",
    },
    async (_uri, variables) => {
      // ① 変数を取り出して正規化・検証する（テンプレートに一致しただけでは安全ではない）
      const slug = normalizeSlug(firstValue(variables["term"]));
      const entry = slug === undefined ? undefined : findTerm(slug);
      if (entry === undefined) {
        // ② リソースの失敗は JSON-RPC エラー。isError はツールだけの仕組みです
        throw new McpError(
          ErrorCode.InvalidParams,
          "指定された用語は辞書にありません。" +
            `有効なスラッグ: ${completeTermSlugs("").join(", ")}`,
        );
      }
      // ③ 返す uri は「受け取った uri」ではなく「自分で組み立てた正規形」にする
      return {
        contents: [
          {
            uri: `glossary://${entry.slug}`,
            mimeType: "text/markdown",
            text: renderTermMarkdown(entry),
          },
        ],
      };
    },
  );
}

/**
 * テンプレート変数は string | string[] で届きます（RFC 6570 のリスト展開があるため）。
 * 単純展開しか使わない本書では先頭の 1 つだけを見ます。
 */
function firstValue(value: string | string[] | undefined): string {
  if (Array.isArray(value)) {
    return value[0] ?? "";
  }
  return value ?? "";
}

/**
 * 用語スラッグを正規化して検証する。許可リストに載らない値は undefined を返す。
 *
 * デコードを 1 回だけ行うのが要点です。何度もデコードすると、
 * %252f（%2f を二重にエンコードしたもの）のような入力を通してしまいます。
 */
function normalizeSlug(raw: string): string | undefined {
  let decoded: string;
  try {
    decoded = decodeURIComponent(raw);
  } catch {
    // 壊れたパーセントエンコード（例: "%zz"）はここで落ちる
    return undefined;
  }
  return TERM_SLUG_PATTERN.test(decoded) ? decoded : undefined;
}

/**
 * 週次レポートのテンプレートを 2 つ登録する。
 *
 * weekly（UTF-8・text）は list を実装し、export_report で書き出した期間を
 * resources/list に並べます。excel（UTF-16LE・blob）は list を持ちません
 * ―― 同じ内容が 2 通りの URI で一覧に並ぶと、どちらを読むべきか分からなくなるためです。
 */
function registerReportResources(server: McpServer): void {
  server.registerResource(
    "weekly_report_csv",
    new ResourceTemplate(WEEKLY_TEMPLATE, {
      // 書き出し済みの期間だけを一覧に並べる。
      // テンプレート自体はどの期間でも読めるので、「一覧」と「読める範囲」は別物です。
      list: async () => ({
        resources: listExportedPeriods().map((period) => ({
          uri: `report://weekly/${period}.csv`,
          name: `${period}.csv`,
        })),
      }),
      complete: {
        period: (value) => listExportedPeriods().filter((period) => period.startsWith(value)),
      },
    }),
    {
      title: "週次稼働レポート（CSV / UTF-8）",
      description:
        "指定期間の稼働記録を CSV（UTF-8）で返します。" +
        "period は 2026-08-03_2026-08-07 のように「開始日_終了日」で指定します。" +
        `期間は最長 ${MAX_RANGE_DAYS} 日です。`,
      mimeType: "text/csv",
    },
    async (_uri, variables) => {
      const { period, from, to } = resolvePeriod(firstValue(variables["period"]));
      const csv = toCsv(buildReportRows(from, to));
      return {
        contents: [{ uri: `report://weekly/${period}.csv`, mimeType: "text/csv", text: csv }],
      };
    },
  );

  server.registerResource(
    "weekly_report_excel_csv",
    new ResourceTemplate(EXCEL_TEMPLATE, { list: undefined }),
    {
      title: "週次稼働レポート（CSV / UTF-16LE・Excel 向け）",
      description:
        "同じ内容を BOM 付き UTF-16LE の CSV として base64 で返します。" +
        "Excel でそのまま開ける形式です。プログラムから処理する場合は report://weekly/ を読んでください。",
      mimeType: "text/csv; charset=utf-16le",
    },
    async (_uri, variables) => {
      const { period, from, to } = resolvePeriod(firstValue(variables["period"]));
      const csv = toExcelCsv(buildReportRows(from, to));
      return {
        contents: [
          {
            uri: `report://excel/${period}.csv`,
            mimeType: "text/csv; charset=utf-16le",
            // text ではなく blob。両方入れてはいけません
            blob: toUtf16Base64(csv),
          },
        ],
      };
    },
  );
}

/**
 * period を検証して from / to に分解する。
 * 期間の上限をここでも効かせるのが要点です ―― リソースはツールと違って
 * JSON Schema による事前検証が無いため、ハンドラが唯一の防衛線になります。
 */
function resolvePeriod(raw: string): { period: string; from: string; to: string } {
  let decoded: string;
  try {
    decoded = decodeURIComponent(raw);
  } catch {
    throw new McpError(ErrorCode.InvalidParams, "period のエンコードが不正です。");
  }
  const parsed = parsePeriod(decoded);
  if (parsed === undefined) {
    throw new McpError(
      ErrorCode.InvalidParams,
      "period は 2026-08-03_2026-08-07 の形式（開始日_終了日）で指定してください。",
    );
  }
  const span = daysBetween(parsed.from, parsed.to);
  if (Number.isNaN(span) || span <= 0) {
    throw new McpError(
      ErrorCode.InvalidParams,
      "period には実在する日付を、開始日 ≦ 終了日の順で指定してください。",
    );
  }
  if (span > MAX_RANGE_DAYS) {
    throw new McpError(
      ErrorCode.InvalidParams,
      `period の期間は最長 ${MAX_RANGE_DAYS} 日です（指定された期間は ${span} 日）。`,
    );
  }
  return { period: decoded, from: parsed.from, to: parsed.to };
}

/** 購読を許すのはこの URI だけ（テンプレートの URI は対象外にしています） */
const SUBSCRIBABLE_URIS = new Set<string>([SUMMARY_URI]);

/**
 * 購読・購読解除のハンドラを登録する。
 *
 * McpServer には registerResource のような専用 API が無いため、
 * 低水準の Server（server.server）に直接ハンドラを付けます。
 * ケイパビリティを宣言していないメソッドのハンドラは登録できない
 * （SDK が例外を投げる）ので、宣言と実装は必ずセットにします。
 */
function registerSubscriptionHandlers(server: McpServer, subscribedUris: Set<string>): void {
  server.server.setRequestHandler(SubscribeRequestSchema, async (request) => {
    const uri = request.params.uri;
    if (!SUBSCRIBABLE_URIS.has(uri)) {
      // 何でも購読させると「更新を検知できない URI を購読したまま待ち続けるクライアント」が生まれます
      throw new McpError(
        ErrorCode.InvalidParams,
        `${uri} は購読に対応していません。購読できる URI: ${[...SUBSCRIBABLE_URIS].join(", ")}`,
      );
    }
    subscribedUris.add(uri);
    console.error(`[subscribe] ${uri} / 購読中の URI 数=${subscribedUris.size}`);
    return {}; // 成功時の結果は空オブジェクト
  });

  server.server.setRequestHandler(UnsubscribeRequestSchema, async (request) => {
    subscribedUris.delete(request.params.uri);
    console.error(`[unsubscribe] ${request.params.uri} / 購読中の URI 数=${subscribedUris.size}`);
    return {};
  });
}

/**
 * ツールを 2 本登録する。
 *
 *   export_report : セッション5 からの改修。書き出した期間を台帳に載せ、
 *                   一覧が変わったときだけ resources/list_changed を送る
 *   add_work_log  : 新規。集計を変え、購読者にだけ resources/updated を送る
 */
function registerTools(server: McpServer, subscribedUris: Set<string>): void {
  server.registerTool(
    "export_report",
    {
      title: "稼働レポートの書き出し（CSV）",
      description:
        "指定期間の稼働記録を CSV に書き出し、リソースへの参照（resource_link）を返します。" +
        "CSV の本文はレスポンスに含めません。中身が必要な場合は返された URI を resources/read で読み取ってください。" +
        "書き出した期間はリソース一覧（resources/list）にも並びます。" +
        `1 回で書き出せるのは最長 ${MAX_RANGE_DAYS} 日です。`,
      inputSchema: {
        from: z
          .string()
          .regex(DATE_PATTERN, "YYYY-MM-DD 形式で指定してください")
          .describe("書き出す期間の開始日（YYYY-MM-DD、この日を含む）"),
        to: z
          .string()
          .regex(DATE_PATTERN, "YYYY-MM-DD 形式で指定してください")
          .describe("書き出す期間の終了日（YYYY-MM-DD、この日を含む）"),
      },
      outputSchema: {
        uri: z.string().describe("生成した CSV リソースの URI"),
        rows: z.number().int().describe("CSV のデータ行数（ヘッダー行を除く）"),
        totalHours: z.number().describe("期間内の合計稼働時間"),
        byteSize: z.number().int().describe("CSV 本文のバイト数（UTF-8）"),
        newlyListed: z
          .boolean()
          .describe("この呼び出しで初めてリソース一覧に追加されたか（2 回目以降は false）"),
      },
      // セッション5 では readOnlyHint: true でした。台帳に登録する副作用が増えたので嘘になります
      annotations: {
        readOnlyHint: false,
        destructiveHint: false, // 既存のデータを壊さない（追加するだけ）
        idempotentHint: true, // 同じ期間で 2 回呼んでも台帳は 1 件
        openWorldHint: false,
      },
    },
    async ({ from, to }) => {
      const span = daysBetween(from, to);
      if (Number.isNaN(span)) {
        return toolError("from / to には実在する日付を指定してください（例: 2026-08-03）。");
      }
      if (span <= 0) {
        return toolError(`from（${from}）は to（${to}）以前の日付を指定してください。`);
      }
      if (span > MAX_RANGE_DAYS) {
        return toolError(
          `書き出せる期間は最長 ${MAX_RANGE_DAYS} 日です（指定された期間は ${span} 日）。`,
        );
      }

      const period = formatPeriod(from, to);
      const rows = buildReportRows(from, to);
      const csv = toCsv(rows);
      const byteSize = byteSizeOf(csv);
      const uri = `report://weekly/${period}.csv`;
      const newlyListed = recordExportedPeriod(period);

      if (newlyListed) {
        // 一覧が実際に変わったときだけ送る（毎回送るとクライアントが list を無駄に取り直す）
        await server.server.sendResourceListChanged();
        console.error(`[notify] resources/list_changed（${uri} を一覧に追加）`);
      }

      return {
        content: [
          {
            type: "text",
            text:
              `${from} 〜 ${to} の稼働記録 ${rows.length} 件（合計 ${sumHours(rows)} 時間）を CSV にしました。` +
              `本文（${byteSize} バイト）は ${uri} を読み取ってください。`,
          },
          {
            type: "resource_link",
            uri,
            name: `${period}.csv`,
            title: "週次稼働レポート（CSV）",
            mimeType: "text/csv",
            description: `${from} 〜 ${to} の稼働記録 ${rows.length} 件（${byteSize} バイト）`,
          },
        ],
        structuredContent: { uri, rows: rows.length, totalHours: sumHours(rows), byteSize, newlyListed },
      };
    },
  );

  server.registerTool(
    "add_work_log",
    {
      title: "稼働記録の追加",
      description:
        "稼働記録を 1 件追加します。追加すると集計リソース（dashboard://summary/current）の内容が変わります。" +
        "同じ内容で 2 回呼ぶと 2 件登録されるため、ユーザーの依頼 1 回につき 1 回だけ呼び出してください。",
      inputSchema: {
        memberId: z
          .string()
          .regex(MEMBER_ID_PATTERN, "m-001 のような形式で指定してください")
          .describe("記録するメンバーの ID（例: m-003）"),
        projectId: z
          .string()
          .regex(PROJECT_ID_PATTERN, "p-portal のような形式で指定してください")
          .describe("記録するプロジェクトの ID（例: p-report）"),
        date: z
          .string()
          .regex(DATE_PATTERN, "YYYY-MM-DD 形式で指定してください")
          .describe("稼働日（YYYY-MM-DD）"),
        hours: z
          .number()
          .min(0.5)
          .max(12)
          .describe("稼働時間（0.5〜12 時間）。0.5 時間単位で指定してください"),
      },
      outputSchema: {
        revision: z.number().int().describe("更新後の集計リソースの改訂番号"),
        entries: z.number().int().describe("登録されている稼働記録の総件数"),
        totalHours: z.number().describe("集計リソースの合計稼働時間（更新後）"),
        updatedResource: z.string().describe("内容が変わったリソースの URI"),
        notified: z.boolean().describe("購読者に更新通知を送ったか"),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false, // 追加するだけで既存の記録を書き換えない
        idempotentHint: false, // 2 回呼べば 2 件になる
        openWorldHint: false,
      },
    },
    async ({ memberId, projectId, date, hours }) => {
      if (findMember(memberId) === undefined) {
        return toolError(
          `メンバー ID ${memberId} は存在しません。有効な ID: ${["m-001", "m-002", "m-003", "m-004"].join(", ")}`,
        );
      }
      if (findProject(projectId) === undefined) {
        return toolError(
          `プロジェクト ID ${projectId} は存在しません。有効な ID: ${["p-portal", "p-report", "p-search"].join(", ")}`,
        );
      }
      if (Number.isNaN(daysBetween(date, date))) {
        return toolError("date には実在する日付を指定してください（例: 2026-08-07）。");
      }

      const result = addWorkLog({ memberId, projectId, date, hours });

      const notified = subscribedUris.has(SUMMARY_URI);
      if (notified) {
        await server.server.sendResourceUpdated({ uri: SUMMARY_URI });
        console.error(`[notify] resources/updated ${SUMMARY_URI} revision=${result.revision}`);
      } else {
        console.error(`[notify] 購読者がいないため通知を送りません revision=${result.revision}`);
      }

      return {
        content: [
          {
            type: "text",
            text:
              `${date} の稼働記録（${memberId} / ${projectId} / ${hours} 時間）を追加しました。` +
              `集計は改訂 ${result.revision} になり、合計 ${result.totalHours} 時間です。`,
          },
        ],
        structuredContent: {
          revision: result.revision,
          entries: result.entries,
          totalHours: result.totalHours,
          updatedResource: SUMMARY_URI,
          notified,
        },
      };
    },
  );
}

/** ツール実行の失敗（前章と同じ方針。リソースと違い isError が使えます） */
function toolError(message: string) {
  return { content: [{ type: "text" as const, text: message }], isError: true };
}

/**
 * 週次レポートの下書きプロンプト。
 *
 * プロンプトは「指示文」と「資料」を組み立てて返すだけの存在です。
 * ここで DB を更新したりファイルを書いたりしてはいけません
 * （ユーザーは「テンプレートを見ただけ」のつもりでいるため）。
 *
 * 引数名に week_start / week_end を使っているのは、Python 側で from が
 * 予約語になるのを避けるためです（2 言語で提供するなら最初から避けます）。
 */
function registerWeeklyReportPrompt(server: McpServer): void {
  server.registerPrompt(
    "weekly_report_draft",
    {
      title: "週次レポート下書き",
      description:
        "指定した週の稼働実績をもとに、週次レポートの下書きを作る指示と資料を組み立てます。" +
        "読み手（team / manager）によって強調する内容が変わります。",
      argsSchema: {
        // completable() で包むと、その引数に補完が付きます
        week_start: completable(
          z
            .string()
            .regex(DATE_PATTERN, "YYYY-MM-DD 形式で指定してください")
            .describe("対象週の月曜日（YYYY-MM-DD）"),
          (value) => listWeekStarts().filter((monday) => monday.startsWith(value)),
        ),
        week_end: completable(
          z
            .string()
            .regex(DATE_PATTERN, "YYYY-MM-DD 形式で指定してください")
            .describe("対象週の金曜日（YYYY-MM-DD）"),
          (value, context) => {
            // すでに week_start が入力済みなら、終了日は 1 つに決まる
            const start = context?.arguments?.["week_start"];
            const candidates =
              start === undefined
                ? listWeekStarts().map((monday) => weekEndOf(monday))
                : [weekEndOf(start)];
            return candidates.filter((candidate) => candidate.startsWith(value));
          },
        ),
        audience: z
          .enum(["team", "manager"])
          .describe("読み手（team: チーム内共有 / manager: 上長への報告）"),
      },
    },
    ({ week_start, week_end, audience }) => {
      const span = daysBetween(week_start, week_end);
      if (Number.isNaN(span) || span <= 0 || span > 31) {
        // プロンプトの失敗は JSON-RPC エラー（isError は使えません）
        throw new McpError(
          ErrorCode.InvalidParams,
          "week_start と week_end は実在する日付で、1〜31 日の範囲にしてください。",
        );
      }

      const rows = buildReportRows(week_start, week_end);
      const csv = toCsv(rows);
      const csvBytes = byteSizeOf(csv);
      const uri = `report://weekly/${formatPeriod(week_start, week_end)}.csv`;
      const snapshot = getDashboardSnapshot();

      const focus =
        audience === "manager"
          ? [
              "- 読み手は上長です。所要 1 分で読める要約を先頭に置いてください",
              "- 稼働の偏り（特定メンバーへの集中）とリスクを明示してください",
              "- 数値は合計と前週比だけに絞り、個人名の列挙は避けてください",
            ]
          : [
              "- 読み手はチームメンバーです。誰が何に時間を使ったかを共有してください",
              "- 来週に持ち越す作業と、手が空きそうな人を書いてください",
              "- 反省ではなく事実の共有として書いてください",
            ];

      const instruction = [
        `${week_start}（月）〜 ${week_end}（金）の週次レポートの下書きを作成してください。`,
        "",
        "## 前提",
        `- 集計対象の全期間: ${snapshot.from} 〜 ${snapshot.to}（改訂 ${snapshot.revision}）`,
        `- 全期間の合計稼働時間: ${snapshot.totalHours} 時間 / 対象 ${snapshot.memberCount} 名`,
        `- この週の稼働記録: ${rows.length} 件 / 合計 ${sumHours(rows)} 時間`,
        "",
        "## 書き方",
        ...focus,
        "",
        "## 出力形式",
        "見出し「今週のサマリー」「メンバー別の稼働」「来週の予定」の 3 節構成の Markdown。",
        "用語が分からない場合は glossary://{term} リソースを参照してください。",
      ].join("\n");

      // 資料は埋め込みリソースとして添える。上限を超えるなら URI だけ渡す
      const attachment =
        csvBytes <= MAX_INLINE_BYTES
          ? ({
              type: "resource",
              resource: { uri, mimeType: "text/csv", text: csv },
            } as const)
          : ({
              type: "text",
              text: `明細（${csvBytes} バイト）は大きいため添付していません。${uri} を読み取ってください。`,
            } as const);

      return {
        description: `${week_start} 〜 ${week_end} の週次レポート下書き（${audience} 向け）`,
        messages: [
          { role: "user" as const, content: { type: "text" as const, text: instruction } },
          { role: "user" as const, content: attachment },
        ],
      };
    },
  );
}
