// 注文ステータスとその遷移（最終プロジェクト）。
//
// ここには Prisma も React も import しない。「この状態から次に進めるか」は
// 引数だけで決まる判定なので、純粋な関数にしておけば src/final/verify.ts で
// 全パターン（4×4＝16通り）を確かめられる。
//
// データベースの orders.status は文字列（VarChar）である。DB 側に enum を作らず
// アプリのリテラル型のユニオンで扱うのが本書の方針（セッション11）なので、
// 境界（DB から読んだ直後）で parseOrderStatus を通して型を付け直す。

/** 注文の状態。4種類で固定（セッション3で決めたもの） */
export type OrderStatus = 'pending' | 'paid' | 'shipped' | 'cancelled';

export const ORDER_STATUSES = ['pending', 'paid', 'shipped', 'cancelled'] as const;

/**
 * データベースの文字列をアプリの型に変換する。
 * 知らない値が入っていたら、いちばん害の小さい pending に寄せる
 * （「発送済み」と誤って表示するより「確認中」と出すほうが安全）。
 */
export function parseOrderStatus(raw: string): OrderStatus {
  return ORDER_STATUSES.find((status) => status === raw) ?? 'pending';
}

/**
 * その状態から次に進める先。
 * default で never に代入しているので、状態を増やしたらここで型エラーになる（セッション12）。
 */
export function nextStatuses(from: OrderStatus): readonly OrderStatus[] {
  switch (from) {
    case 'pending':
      return ['paid', 'cancelled'];
    case 'paid':
      return ['shipped', 'cancelled'];
    case 'shipped':
      return [];
    case 'cancelled':
      return [];
    default: {
      const unreachable: never = from;

      throw new Error(`未知の注文ステータスです: ${String(unreachable)}`);
    }
  }
}

/** その遷移を行ってよいか。同じ状態への遷移（pending → pending）も許さない */
export function canTransitionTo(from: OrderStatus, to: OrderStatus): boolean {
  return nextStatuses(from).includes(to);
}

export function canCancelOrder(status: OrderStatus): boolean {
  return canTransitionTo(status, 'cancelled');
}

/** もう動かない状態か（発送済み・取消済みは終着点） */
export function isSettled(status: OrderStatus): boolean {
  return nextStatuses(status).length === 0;
}

/** 利用者向けの日本語。DB の値（'paid'）をそのまま画面に出さない */
export function describeOrderStatus(status: OrderStatus): string {
  switch (status) {
    case 'pending':
      return 'お支払いの確認中';
    case 'paid':
      return 'お支払い済み';
    case 'shipped':
      return '発送済み';
    case 'cancelled':
      return 'キャンセル';
    default: {
      const unreachable: never = status;

      throw new Error(`未知の注文ステータスです: ${String(unreachable)}`);
    }
  }
}

/** 決済（payments.status）の状態。決済サービスの言葉に合わせる */
export type PaymentRecordStatus = 'succeeded' | 'pending' | 'failed';

export function describePaymentStatus(status: string): string {
  switch (status) {
    case 'succeeded':
      return '決済完了';
    case 'pending':
      return '決済の確認中';
    case 'failed':
      return '決済失敗';
    default:
      // DB には知らない値が入りうる。ここは never で締めずに既定の表示に落とす
      return '不明';
  }
}
