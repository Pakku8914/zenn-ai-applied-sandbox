// カート（cart_items テーブル）への読み書きをまとめる場所（セッション24）。
//
// 画面や Server Action から直接 prisma を呼ばず、必ずこのモジュールを通す。
// 「どんな SQL が飛ぶか」と「どこで userId を条件に入れているか」を1か所に閉じ込めるため。

import type { CartItem, Product } from '@prisma/client';
import { prisma } from '@/lib/db';
import { MAX_CART_QUANTITY } from '@/lib/cart';

/**
 * データベースの cart_items 行に商品を結合した形（セッション11で決めた型）。
 * include: { product: true } の結果がちょうどこの形になる。
 */
export type CartItemWithProduct = CartItem & { product: Product };

/** 書き込みの結果。判別タグは本書共通の kind */
export type CartChange = { kind: 'ok'; message: string } | { kind: 'error'; message: string };

/** カートの中身を明細の並び順で取り出す（1回の問い合わせで商品も一緒に取る） */
export async function findCartItems(userId: number): Promise<CartItemWithProduct[]> {
  return prisma.cartItem.findMany({
    where: { userId },
    include: { product: true },
    orderBy: { id: 'asc' },
  });
}

/**
 * カートに商品を足す。
 * 同じ商品がすでに入っていれば行を増やさず数量を足す（cart_items の複合ユニークに合わせた形）。
 */
export async function addToCart(
  userId: number,
  productId: number,
  quantity: number
): Promise<CartChange> {
  const product = await prisma.product.findUnique({
    where: { id: productId },
    select: { name: true, stock: true },
  });

  if (product === null) {
    return { kind: 'error', message: 'その商品は取り扱っていません' };
  }

  // @@unique([userId, productId]) を張ったので、この2列の組でも1件に特定できる
  const existing = await prisma.cartItem.findUnique({
    where: { userId_productId: { userId, productId } },
    select: { quantity: true },
  });
  const currentQuantity = existing === null ? 0 : existing.quantity;
  const nextQuantity = currentQuantity + quantity;

  if (nextQuantity > MAX_CART_QUANTITY) {
    return {
      kind: 'error',
      message: `1商品あたり${MAX_CART_QUANTITY}点までです（すでに${currentQuantity}点入っています）`,
    };
  }

  if (product.stock < nextQuantity) {
    return { kind: 'error', message: `在庫が足りません（残り${product.stock}点）` };
  }

  await prisma.cartItem.upsert({
    where: { userId_productId: { userId, productId } },
    update: { quantity: nextQuantity },
    create: { userId, productId, quantity: nextQuantity },
  });

  return { kind: 'ok', message: `${product.name}を${nextQuantity}点にしました` };
}

/** 明細の数量を差し替える。where に userId を入れるので、他人の明細は変更できない */
export async function changeCartQuantity(
  userId: number,
  productId: number,
  quantity: number
): Promise<CartChange> {
  const product = await prisma.product.findUnique({
    where: { id: productId },
    select: { name: true, stock: true },
  });

  if (product === null) {
    return { kind: 'error', message: 'その商品は取り扱っていません' };
  }

  if (product.stock < quantity) {
    return { kind: 'error', message: `在庫が足りません（残り${product.stock}点）` };
  }

  const updated = await prisma.cartItem.updateMany({
    where: { userId, productId },
    data: { quantity },
  });

  if (updated.count === 0) {
    return { kind: 'error', message: 'カートにその商品がありません' };
  }

  return { kind: 'ok', message: `${product.name}を${quantity}点にしました` };
}

/**
 * 明細を取り除く。
 * deleteMany に userId を含めることで「自分の明細だけ」を消せる。
 * 存在しない行を消しても例外にならず count が 0 になるので、結果を数で判断できる。
 */
export async function removeFromCart(userId: number, productId: number): Promise<CartChange> {
  const deleted = await prisma.cartItem.deleteMany({ where: { userId, productId } });

  if (deleted.count === 0) {
    return { kind: 'error', message: 'カートにその商品がありません' };
  }

  return { kind: 'ok', message: 'カートから削除しました' };
}
