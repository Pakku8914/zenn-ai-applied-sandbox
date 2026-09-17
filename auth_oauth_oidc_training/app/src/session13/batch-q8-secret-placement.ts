// セッション 13（前半）問題 3: client_secret_basic と client_secret_post の違いが
// 「秘密をどこに置くか」だけであることを、リクエストの組み立てから突き合わせます。
// 置き場所が変わると「どの記録に残りうるか」が変わる、という帰結まで関数にします。
import { buildTokenRequest } from "./batch-worker-client.js";
import type { ClientAuthMethod } from "./batch-worker-client.js";

/** 秘密が残りうる記録。置き場所から機械的に導きます */
export type ExposureChannel =
  | "URL を記録するアクセスログ"
  | "リクエストヘッダを記録するプロキシ"
  | "リクエストボディをダンプするデバッグ設定";

export type Placement = {
  readonly method: ClientAuthMethod;
  /** Authorization ヘッダの値（無ければ空文字） */
  readonly header: string;
  /** ボディに入ったキー（並べ替え済み） */
  readonly bodyKeys: readonly string[];
  readonly secretInHeader: boolean;
  readonly secretInBody: boolean;
  /** どちらの方式でも URL には秘密を載せません */
  readonly secretInUrl: boolean;
};

/** 方式名から推測せず、buildTokenRequest() が実際に組んだものから判定します */
export function placementOf(method: ClientAuthMethod): Placement {
  const { headers, body } = buildTokenRequest({ method });
  const header = headers["authorization"] ?? "";
  return {
    method,
    header,
    bodyKeys: [...body.keys()].sort(),
    secretInHeader: header !== "",
    secretInBody: body.has("client_secret"),
    secretInUrl: false,
  };
}

/** 2 つの組み立てで値が違う項目名だけを、決まった順序で返します */
export function differences(a: Placement, b: Placement): readonly string[] {
  const fields: ReadonlyArray<keyof Placement> = [
    "header",
    "bodyKeys",
    "secretInHeader",
    "secretInBody",
    "secretInUrl",
  ];
  return fields.filter((field) => JSON.stringify(a[field]) !== JSON.stringify(b[field]));
}

/** 秘密が載った場所から、残りうる記録を導きます */
export function exposure(placement: Placement): readonly ExposureChannel[] {
  const channels: ExposureChannel[] = [];
  if (placement.secretInUrl) channels.push("URL を記録するアクセスログ");
  if (placement.secretInHeader) channels.push("リクエストヘッダを記録するプロキシ");
  if (placement.secretInBody) channels.push("リクエストボディをダンプするデバッグ設定");
  return channels;
}

/** 「秘密そのものがネットワークに出るか」が同じなら、2 方式の強さは同じです */
export function sameStrength(a: Placement, b: Placement): boolean {
  const leaves = (placement: Placement): boolean => placement.secretInHeader || placement.secretInBody;
  return leaves(a) === leaves(b);
}

export type PlacementComparison = {
  readonly basic: Placement;
  readonly post: Placement;
  readonly differences: readonly string[];
  readonly sameStrength: boolean;
};

export function comparePlacements(): PlacementComparison {
  const basic = placementOf("client_secret_basic");
  const post = placementOf("client_secret_post");
  return {
    basic,
    post,
    differences: differences(basic, post),
    sameStrength: sameStrength(basic, post),
  };
}
