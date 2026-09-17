// N+1 問題を「発行された SELECT の本数」で確かめるデモ（セッション23）。
//
// 実行: docker compose exec ts sh -c 'cd web && node --experimental-strip-types scripts/n-plus-one-demo.ts'
//
// スクリプトからは @/lib/... の別名が使えないので、ここでは PrismaClient を自分で作る。
// 1回動いて終わるプロセスなので、接続が増え続ける心配（lib/db.ts の話）は無い。

import type { Prisma } from '@prisma/client';
import { PrismaClient } from '@prisma/client';

// log をイベントとして受け取ると、発行された SQL をプログラムから数えられる。
const prisma = new PrismaClient({ log: [{ emit: 'event', level: 'query' }] });

let selectCount = 0;

prisma.$on('query', (event: Prisma.QueryEvent) => {
  // BEGIN / COMMIT も流れてくるので、SELECT だけを数える
  if (event.query.trimStart().toUpperCase().startsWith('SELECT')) {
    selectCount += 1;
  }
});

/** 商品名とカテゴリ名の対応を作る。方法ごとに実装を差し替えて本数を比べる */
type Loader = () => Promise<string[]>;

/** 悪い例：商品を取ってから、1件ずつカテゴリを引く（1 + N 本） */
const loadWithNPlusOne: Loader = async () => {
  const products = await prisma.product.findMany({
    select: { id: true, name: true, categoryId: true },
    orderBy: { id: 'asc' },
  });
  const labels: string[] = [];

  for (const product of products) {
    const category = await prisma.category.findUnique({
      where: { id: product.categoryId },
      select: { name: true },
    });

    labels.push(`${product.name}=${category?.name ?? '未分類'}`);
  }

  return labels;
};

/** 良い例：include でカテゴリを一緒に取る（商品と関連の2本） */
const loadWithInclude: Loader = async () => {
  const products = await prisma.product.findMany({
    include: { category: true },
    orderBy: { id: 'asc' },
  });

  return products.map((product) => `${product.name}=${product.category.name}`);
};

/** 自分でまとめる例：IN でカテゴリを1回だけ引き、メモリで突き合わせる（2本） */
const loadWithIn: Loader = async () => {
  const products = await prisma.product.findMany({
    select: { id: true, name: true, categoryId: true },
    orderBy: { id: 'asc' },
  });
  const categories = await prisma.category.findMany({
    where: { id: { in: products.map((product) => product.categoryId) } },
    select: { id: true, name: true },
  });
  const nameById = new Map<number, string>(
    categories.map((category) => [category.id, category.name] as const)
  );

  return products.map(
    (product) => `${product.name}=${nameById.get(product.categoryId) ?? '未分類'}`
  );
};

/** クエリログのイベントは少し遅れて届くので、数える前に一息待つ */
async function waitForLog(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 200));
}

async function report(label: string, load: Loader): Promise<string> {
  selectCount = 0;
  const labels = await load();

  await waitForLog();
  console.log(`${label}: SELECT ${selectCount}本`);

  return labels.join(', ');
}

async function main(): Promise<void> {
  const a = await report('[1] 商品を取ってから1件ずつカテゴリを引く（N+1）', loadWithNPlusOne);
  const b = await report('[2] include: { category: true }', loadWithInclude);
  const c = await report('[3] IN でまとめて引く', loadWithIn);

  console.log(`結果は3つとも同じ: ${a === b && b === c}`);
  console.log(a);
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
