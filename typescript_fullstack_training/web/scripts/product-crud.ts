// 商品の CRUD（作成・取得・更新・削除）を1本で通すスクリプト（セッション23 練習問題3の解答）。
//
// 実行: docker compose exec ts sh -c 'cd web && node --experimental-strip-types scripts/product-crud.ts'
//
// マスタに無い商品は作らない方針なので、ここで作る行は確認用の一時的なもの。
// 最後に必ず削除するので、何度実行しても商品は5件に戻る。

import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();

const TEMP_NAME = 'テスト商品（削除予定）';

async function main(): Promise<void> {
  const before = await prisma.product.count();

  // C（Create）：1件作る。id は指定しない（データベースの自動採番に任せる）
  const created = await prisma.product.create({
    data: {
      name: TEMP_NAME,
      price: 100,
      stock: 1,
      description: '確認用の行',
      categoryId: 2,
    },
    select: { id: true, name: true },
  });
  const afterCreate = await prisma.product.count();

  console.log(`[C] create: ${created.name} を作成しました（商品件数 ${before} → ${afterCreate}）`);

  // R（Read）：主キーで1件取る。include でカテゴリ名も一緒に取る
  const found = await prisma.product.findUnique({
    where: { id: created.id },
    include: { category: true },
  });

  if (found === null) {
    throw new Error('作ったはずの商品が見つかりません');
  }

  console.log(
    `[R] findUnique: ${found.name} / ${found.price}円 / 在庫 ${found.stock} / カテゴリ ${found.category.name}`
  );

  // U（Update）：主キーで1件更新する。返り値は更新後の行
  const updated = await prisma.product.update({
    where: { id: created.id },
    data: { price: 120, stock: { increment: 3 } },
    select: { price: true, stock: true },
  });

  console.log(
    `[U] update: 価格 ${found.price} → ${updated.price} / 在庫 ${found.stock} → ${updated.stock}`
  );

  // D（Delete）：主キーで1件消す
  await prisma.product.delete({ where: { id: created.id } });

  const afterDelete = await prisma.product.count();

  console.log(`[D] delete: 削除しました（商品件数 ${afterCreate} → ${afterDelete}）`);

  // 消えたことを確認する。findUnique は「見つからない」を例外ではなく null で返す
  const gone = await prisma.product.findUnique({ where: { id: created.id } });

  console.log(`[R] findUnique（削除後）: ${gone === null ? 'null' : '残っている'}`);
}

main()
  .then(async () => {
    await prisma.$disconnect();
  })
  .catch(async (error: unknown) => {
    console.error('crud: 失敗しました', error);
    await prisma.$disconnect();
    process.exit(1);
  });
