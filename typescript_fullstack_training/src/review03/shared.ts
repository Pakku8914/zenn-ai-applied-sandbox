// 復習03「セッション16〜19の横断復習」で全問題が共有する部品。
// 「型」と「失敗の表し方」だけを置き、業務のロジックは置かない。
// このファイルは他のファイルを1つも import しない（依存の矢印を一方向にするため）。

/** 成功か失敗かを型で表す（セッション13） */
export type Result<T, E> = { kind: 'ok'; value: T } | { kind: 'error'; error: E };

/** データが壊れていたときのエラー。cause に元のエラーを保持する（セッション18） */
export class DataError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
    // name を設定しないと 'Error' のまま表示され、どの種類の失敗か分からなくなる
    this.name = 'DataError';
  }
}

/** 例外を投げる世界と Result を返す世界の境界（セッション18） */
export async function tryCatch<T>(task: () => Promise<T>): Promise<Result<T, unknown>> {
  try {
    return { kind: 'ok', value: await task() };
  } catch (error: unknown) {
    // catch に来る値は Error とは限らない。unknown で受けて呼び出し側に判断を任せる
    return { kind: 'error', error };
  }
}
