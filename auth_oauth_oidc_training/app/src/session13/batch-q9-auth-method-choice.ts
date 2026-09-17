// セッション 13（前半）問題 4: 4 方式を 3 本の軸に分類し、現場の制約から方式を選びます。
// 選んだ理由と選ばなかった理由の両方を残すのが要点です。
import { AUTH_METHOD_FACTS } from "./batch-q1-client-auth-matrix.js";
import type { AuthMethodFact } from "./batch-q1-client-auth-matrix.js";

/** 4 方式を貫く 3 本の軸。「何で自分を証明するか」で分けます */
export type SecretAxis = "秘密を送る" | "秘密で署名する" | "通信路に紐づける";

/** 軸は方式名から決めず、事実（秘密が外に出るか・置き場所）から導きます */
export function axisOf(fact: AuthMethodFact): SecretAxis {
  if (fact.secretLeavesTheClient) return "秘密を送る";
  return fact.secretLocation === "TLS の通信路" ? "通信路に紐づける" : "秘密で署名する";
}

export type AxisGroup = { readonly axis: SecretAxis; readonly methods: readonly string[] };

/** 軸ごとに方式をまとめます。並び順は AUTH_METHOD_FACTS に従うので決定的です */
export function groupByAxis(facts: readonly AuthMethodFact[] = AUTH_METHOD_FACTS): readonly AxisGroup[] {
  const axes: readonly SecretAxis[] = ["秘密を送る", "秘密で署名する", "通信路に紐づける"];
  return axes.map((axis) => ({ axis, methods: facts.filter((f) => axisOf(f) === axis).map((f) => f.method) }));
}

/** 現場の制約。方式の強さではなく「何が運用できるか」を並べます */
export type Constraints = {
  readonly name: string;
  readonly canDistributePrivateKey: boolean;
  readonly canRunCertificateRenewal: boolean;
  readonly httpsEverywhere: boolean;
  /** 秘密を知ることになる人・系の数 */
  readonly secretSharedWith: number;
};

export type Choice = {
  readonly scenario: string;
  readonly method: string;
  readonly axis: SecretAxis;
  readonly reason: string;
  /** 見送った方式とその理由。見送った順に積みます */
  readonly rejected: readonly { readonly method: string; readonly because: string }[];
  /** 強さとは別に、運用で先に決めるべきこと */
  readonly note: string;
};

/**
 * 強い順（通信路に紐づける → 秘密で署名する → 秘密を送る）に見て、
 * 運用できる最初のものを採ります。
 */
export function chooseMethod(c: Constraints): Choice {
  const rejected: { method: string; because: string }[] = [];
  const base = { scenario: c.name, rejected, note: "" };

  if (c.canRunCertificateRenewal && c.httpsEverywhere) {
    return { ...base, method: "tls_client_auth", axis: "通信路に紐づける", reason: "証明書を回せて経路も HTTPS" };
  }
  rejected.push({
    method: "tls_client_auth",
    because: c.canRunCertificateRenewal ? "HTTPS でない経路が残っている" : "証明書を回す体制が無い",
  });

  if (c.canDistributePrivateKey) {
    return { ...base, method: "private_key_jwt", axis: "秘密で署名する", reason: "秘密鍵を配って管理できる" };
  }
  rejected.push({ method: "private_key_jwt", because: "秘密鍵を配って管理する手立てが無い" });

  return {
    ...base,
    method: "client_secret_basic",
    axis: "秘密を送る",
    reason: "鍵も証明書も配れないので秘密を送る方式に留まる",
    note: c.secretSharedWith >= 2 ? `秘密を ${c.secretSharedWith} 者が知るのでローテーションの段取りを先に決める` : "",
  };
}

/** 3 つの現場。制約だけが違います */
export const SCENARIOS: readonly Constraints[] = [
  { name: "社内のサーバー間", canDistributePrivateKey: true, canRunCertificateRenewal: true, httpsEverywhere: true, secretSharedWith: 1 },
  { name: "クラウドの夜間バッチ", canDistributePrivateKey: true, canRunCertificateRenewal: false, httpsEverywhere: true, secretSharedWith: 1 },
  { name: "他社に運用を委ねたジョブ", canDistributePrivateKey: false, canRunCertificateRenewal: false, httpsEverywhere: true, secretSharedWith: 3 },
];

export const chooseAll = (scenarios: readonly Constraints[] = SCENARIOS): readonly Choice[] =>
  scenarios.map(chooseMethod);

/** 決定の記録。レビューで読まれるのは「見送った理由」のほうです */
export function decisionTable(choices: readonly Choice[] = chooseAll()): string {
  const rows = choices.map(
    (c) => `| ${c.scenario} | \`${c.method}\` | ${c.reason} | ${
      c.rejected.map((r) => `\`${r.method}\`（${r.because}）`).join(" / ") || "なし"
    } |`,
  );
  return ["| 現場 | 選んだ方式 | 選んだ理由 | 見送った方式 |", "| :--- | :--- | :--- | :--- |", ...rows].join("\n");
}
