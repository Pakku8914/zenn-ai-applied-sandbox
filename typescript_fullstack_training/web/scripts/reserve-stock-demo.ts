// 在庫引当を $transaction と条件付き更新で行うデモ（セッション23）。
//
// 実行: docker compose exec ts sh -c 'cd web && node --experimental-strip-types scripts/reserve-stock-demo.ts'
//
// 最後に在庫をマスタの値へ戻すので、何度実行しても同じ出力になる。
// reserveStockForItems はデータベースのクライアントを引数で受け取る形にしてあるので、
// 次章で注文確定の処理に組み込むときはそのまま移せる。

import type { Prisma } from '@prisma/client';
import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();

type Result<T, E> = { kind: 'ok'; value: T } | { kind: 'error'; error: E };

type ReserveItem = { productId: number; quantity: number };

type ReserveFailure =
  | { kind: 'product_not_found'; productId: number }
  | { kind: 'insufficient_stock'; productId: number; stock: number; quantity: number };

type ReserveLine = {
  productId: number;
  name: string;
  quantity: number;
  remainingStock: number;
};

/**
 * トランザクションを取り消すために投げる専用のエラー（セッション18のカスタムエラー）。
 * 対話型トランザクションは「値を返す＝コミット」「例外を投げる＝ロールバック」なので、
 * 途中でやめたいときは Result を返すのではなく投げる必要がある。
 */
class ReservationAbort extends Error {
  readonly failure: ReserveFailure;

  constructor(failure: ReserveFailure) {
    super(`在庫を引き当てられません: ${failure.kind}`);
    this.name = 'ReservationAbort';
    this.failure = failure;
  }
}

/** 更新できなかった理由を調べる（商品が無いのか、在庫が足りないのか） */
async function explainFailure(
  tx: Prisma.TransactionClient,
  item: ReserveItem
): Promise<ReserveFailure> {
  const product = await tx.product.findUnique({
    where: { id: item.productId },
    select: { stock: true },
  });

  return product === null
    ? { kind: 'product_not_found', productId: item.productId }
    : {
        kind: 'insufficient_stock',
        productId: item.productId,
        stock: product.stock,
        quantity: item.quantity,
      };
}

/** 複数商品の在庫を「全部成功か、全部取り消し」で引き当てる */
async function reserveStockForItems(
  client: PrismaClient,
  items: readonly ReserveItem[]
): Promise<Result<ReserveLine[], ReserveFailure>> {
  try {
    const lines = await client.$transaction(async (tx) => {
      const results: ReserveLine[] = [];

      for (const item of items) {
        // 条件付き更新。「在庫が quantity 以上ある行」だけを減らすので、
        // 同時に2人が実行しても在庫はマイナスにならない。
        const updated = await tx.product.updateMany({
          where: { id: item.productId, stock: { gte: item.quantity } },
          data: { stock: { decrement: item.quantity } },
        });

        if (updated.count === 0) {
          throw new ReservationAbort(await explainFailure(tx, item));
        }

        const after = await tx.product.findUniqueOrThrow({
          where: { id: item.productId },
          select: { name: true, stock: true },
        });

        results.push({
          productId: item.productId,
          name: after.name,
          quantity: item.quantity,
          remainingStock: after.stock,
        });
      }

      return results;
    });

    return { kind: 'ok', value: lines };
  } catch (error) {
    // 想定した失敗だけを Result に変換する。それ以外はそのまま投げ直す（セッション18）
    if (error instanceof ReservationAbort) {
      return { kind: 'error', error: error.failure };
    }

    throw error;
  }
}

function describeFailure(failure: ReserveFailure): string {
  switch (failure.kind) {
    case 'product_not_found':
      return `商品が見つかりません（商品ID ${failure.productId}）`;
    case 'insufficient_stock':
      return `在庫不足（商品ID ${failure.productId}：在庫 ${failure.stock} / 要求 ${failure.quantity}）`;
    default: {
      const unreachable: never = failure;

      throw new Error(`未知の失敗です: ${JSON.stringify(unreachable)}`);
    }
  }
}

async function tryReserve(label: string, items: ReserveItem[]): Promise<void> {
  const result = await reserveStockForItems(prisma, items);

  if (result.kind === 'ok') {
    const detail = result.value
      .map((line) => `${line.name} ×${line.quantity}（残り ${line.remainingStock}）`)
      .join(' + ');

    console.log(`${label}: 成功 / ${detail}`);

    return;
  }

  console.log(`${label}: 失敗 / ${describeFailure(result.error)}`);
}

/** 在庫をマスタの値に戻す（何度実行しても同じ結果にするため） */
async function restoreStock(): Promise<void> {
  const master: { id: number; stock: number }[] = [
    { id: 1, stock: 24 },
    { id: 2, stock: 12 },
    { id: 3, stock: 3 },
    { id: 4, stock: 0 },
    { id: 5, stock: 5 },
  ];

  for (const row of master) {
    await prisma.product.update({ where: { id: row.id }, data: { stock: row.stock } });
  }

  console.log(`在庫を元に戻しました: ${master.map((row) => row.stock).join(' / ')}`);
}

async function main(): Promise<void> {
  await tryReserve('[1] マグカップ ×2', [{ productId: 3, quantity: 2 }]);
  await tryReserve('[2] マグカップ ×2（もう一度）', [{ productId: 3, quantity: 2 }]);
  await tryReserve('[3] 石けん ×1 ＋ リネンのふきん ×1', [
    { productId: 1, quantity: 1 },
    { productId: 4, quantity: 1 },
  ]);

  const soap = await prisma.product.findUniqueOrThrow({
    where: { id: 1 },
    select: { name: true, stock: true },
  });

  console.log(`    ロールバック後の在庫: ${soap.name} ${soap.stock}（減っていない）`);

  await tryReserve('[4] 存在しない商品 ×1', [{ productId: 999, quantity: 1 }]);
  await restoreStock();
}

main()
  .then(async () => {
    await prisma.$disconnect();
  })
  .catch(async (error: unknown) => {
    console.error('demo: 失敗しました', error);
    await prisma.$disconnect();
    process.exit(1);
  });
