import type { Product } from '../../../data/products';
import { toError, type RequestState } from '../../s10/requestState';
import { parseProducts } from './productGuard';

/**
 * 取ってきた値を検証してから画面の状態にする。
 * 通信の失敗も形の違いも「error の状態」として返し、例外を画面側へ漏らさない。
 */
export async function loadProducts(load: () => Promise<unknown>): Promise<RequestState<Product[]>> {
  try {
    const result = parseProducts(await load());
    return result.ok
      ? { status: 'success', data: result.value }
      : { status: 'error', error: new Error(result.reason) };
  } catch (error) {
    return { status: 'error', error: toError(error) };
  }
}
