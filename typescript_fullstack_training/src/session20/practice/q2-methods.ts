// 問題2: HTTP メソッドの「安全」と「冪等」を表にする。

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

export type MethodTrait = {
  /** サーバーの状態を変えないか */
  safe: boolean;
  /** 同じリクエストを何回送っても結果が同じか */
  idempotent: boolean;
  purpose: string;
};

const METHOD_TRAITS = {
  GET: { safe: true, idempotent: true, purpose: '取得する' },
  POST: { safe: false, idempotent: false, purpose: '新しく作る・処理を起こす' },
  PUT: { safe: false, idempotent: true, purpose: '内容をまるごと置き換える' },
  PATCH: { safe: false, idempotent: false, purpose: '一部だけ書き換える' },
  DELETE: { safe: false, idempotent: true, purpose: '削除する' },
} as const satisfies Record<HttpMethod, MethodTrait>;

export const HTTP_METHODS = [
  'GET',
  'POST',
  'PUT',
  'PATCH',
  'DELETE',
] as const satisfies readonly HttpMethod[];

function toYesNo(value: boolean): string {
  return value ? 'はい' : 'いいえ';
}

export function describeMethod(method: HttpMethod): string {
  const trait = METHOD_TRAITS[method];
  return `${method}: 安全=${toYesNo(trait.safe)} / 冪等=${toYesNo(trait.idempotent)} / ${trait.purpose}`;
}

export function formatMethodTable(): string {
  return HTTP_METHODS.map((method) => describeMethod(method)).join('\n');
}

/** 通信が失敗したとき、同じリクエストをそのまま送り直してよいか */
export function isRetrySafe(method: HttpMethod): boolean {
  return METHOD_TRAITS[method].idempotent;
}

/** 送り直しが危ないメソッドだけを並べる */
export function listUnsafeToRetry(): string {
  return HTTP_METHODS.filter((method) => !isRetrySafe(method)).join(' / ');
}
