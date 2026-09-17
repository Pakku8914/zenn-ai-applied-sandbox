// 商品・カテゴリのマスタデータをデータベースに投入する（セッション23）。
//
// 実行: docker compose exec ts sh -c 'cd web && node --experimental-strip-types prisma/seed.ts'
//
// upsert を使っているので何度実行しても同じ状態になる（冪等）。
// Node.js 24 は型注釈を剥がして .ts を直接実行できるため、tsx は使わない。

import { randomBytes, scryptSync } from 'node:crypto';
import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();

type CategorySeed = {
  id: number;
  name: string;
  slug: string;
};

type ProductSeed = {
  id: number;
  name: string;
  price: number;
  stock: number;
  description: string;
  imageUrl: string;
  categoryId: number;
};

const CATEGORIES: CategorySeed[] = [
  { id: 1, name: 'バス・ボディケア', slug: 'bath-body' },
  { id: 2, name: 'キッチン雑貨', slug: 'kitchen' },
  { id: 3, name: 'ファブリック', slug: 'fabric' },
];

const PRODUCTS: ProductSeed[] = [
  {
    id: 1,
    name: 'ラベンダーの石けん',
    price: 480,
    stock: 24,
    description: 'ラベンダーの精油を練り込んだ手作りの石けんです。',
    imageUrl: '/images/products/lavender-soap.png',
    categoryId: 1,
  },
  {
    id: 2,
    name: 'ハンドクリーム',
    price: 1800,
    stock: 12,
    description: 'べたつかない使用感の保湿ハンドクリームです。',
    imageUrl: '/images/products/hand-cream.png',
    categoryId: 1,
  },
  {
    id: 3,
    name: 'マグカップ',
    price: 2350,
    stock: 3,
    description: '厚みのある陶器で、冷めにくいマグカップです。',
    imageUrl: '/images/products/mug.png',
    categoryId: 2,
  },
  {
    id: 4,
    name: 'リネンのふきん',
    price: 990,
    stock: 0,
    description: '洗うほどやわらかくなるリネン100%のふきんです。',
    imageUrl: '/images/products/linen-cloth.png',
    categoryId: 3,
  },
  {
    id: 5,
    name: 'コットンのトートバッグ',
    price: 2800,
    stock: 5,
    description: 'A4サイズが入る、しっかりした厚手のトートバッグです。',
    imageUrl: '/images/products/tote-bag.png',
    categoryId: 3,
  },
];

/**
 * デモ用の利用者（セッション24で追加）。
 * カートは cart_items テーブルに user_id とともに保存するため、
 * ログインを実装する前でも「誰のカートか」を決める相手が1人必要になる。
 */
const DEMO_USER = {
  id: 1,
  email: 'demo@example.com',
  name: 'デモユーザー',
  role: 'user',
};

/** デモ用のパスワード。学習用なので固定の文字列にしてある */
const DEMO_PASSWORD = 'demo-password-1234';

/**
 * パスワードは平文で保存しない。必ずハッシュ化する。
 *
 * ソルト（毎回変わるランダムな値）を混ぜてから scrypt で変換し、
 * 「<ソルト(hex)>:<導出鍵(hex)>」という1つの文字列にして保存する。
 * ソルトを一緒に保存するのは、照合のときに同じ計算を再現するためである。
 *
 * ハッシュ化の仕組みと照合の方法は「セッション25：認証と認可」で詳しく学ぶ。
 */
function hashPassword(password: string): string {
  const salt = randomBytes(16);
  const derivedKey = scryptSync(password, salt, 64);

  return `${salt.toString('hex')}:${derivedKey.toString('hex')}`;
}

/** 利用者を投入する。再実行してもパスワードのハッシュは作り直さない（update に含めない） */
async function seedUsers(): Promise<void> {
  await prisma.user.upsert({
    where: { id: DEMO_USER.id },
    update: { email: DEMO_USER.email, name: DEMO_USER.name, role: DEMO_USER.role },
    create: { ...DEMO_USER, passwordHash: hashPassword(DEMO_PASSWORD) },
  });
}

/** カテゴリを投入する。外部キーの参照先なので商品より先に入れる */
async function seedCategories(): Promise<void> {
  for (const category of CATEGORIES) {
    await prisma.category.upsert({
      where: { id: category.id },
      update: { name: category.name, slug: category.slug },
      create: category,
    });
  }
}

/** 商品を投入する。すでにある行は上書きするので、在庫を減らしたあとでも元に戻せる */
async function seedProducts(): Promise<void> {
  for (const product of PRODUCTS) {
    await prisma.product.upsert({
      where: { id: product.id },
      update: {
        name: product.name,
        price: product.price,
        stock: product.stock,
        description: product.description,
        imageUrl: product.imageUrl,
        categoryId: product.categoryId,
      },
      create: product,
    });
  }
}

/**
 * id を明示して入れたので、自動採番（連番）の位置が 1 のまま残っている。
 * このままだと id を指定しない create が id=1 で衝突するため、採番位置を最大 id に合わせる。
 * Prisma のメソッドでは書けない操作なので、ここだけ生 SQL を使う。
 * Unsafe という名前は「文字列を組み立てて渡せてしまう＝SQL インジェクションの入口になりうる」
 * という警告。ここでは固定の文字列しか渡していない（入力値は一切混ぜない）。
 */
async function fixSequences(): Promise<void> {
  await prisma.$queryRawUnsafe(
    "SELECT setval(pg_get_serial_sequence('categories', 'id'), (SELECT COALESCE(MAX(id), 1) FROM categories))"
  );
  await prisma.$queryRawUnsafe(
    "SELECT setval(pg_get_serial_sequence('products', 'id'), (SELECT COALESCE(MAX(id), 1) FROM products))"
  );
  await prisma.$queryRawUnsafe(
    "SELECT setval(pg_get_serial_sequence('users', 'id'), (SELECT COALESCE(MAX(id), 1) FROM users))"
  );
}

/** 投入結果を検算する。在庫金額の合計はセッション10で確認した 54170 円になる */
async function reportResult(): Promise<void> {
  const categoryCount = await prisma.category.count();
  const productCount = await prisma.product.count();
  const products = await prisma.product.findMany({
    include: { category: true },
    orderBy: { id: 'asc' },
  });

  const stockValueByCategory = new Map<string, number>();

  for (const product of products) {
    const current = stockValueByCategory.get(product.category.name) ?? 0;

    stockValueByCategory.set(product.category.name, current + product.price * product.stock);
  }

  const breakdown = [...stockValueByCategory]
    .map(([name, value]) => `${name} ${value}`)
    .join(' / ');
  const total = [...stockValueByCategory.values()].reduce((sum, value) => sum + value, 0);

  const userCount = await prisma.user.count();

  console.log(`seed: カテゴリ ${categoryCount}件 / 商品 ${productCount}件`);
  console.log(`seed: 在庫金額の合計 ${total}円（${breakdown}）`);
  console.log(`seed: 利用者 ${userCount}件（${DEMO_USER.email}）`);
}

async function main(): Promise<void> {
  await seedCategories();
  await seedProducts();
  await seedUsers();
  await fixSequences();
  await reportResult();
}

main()
  .then(async () => {
    await prisma.$disconnect();
  })
  .catch(async (error: unknown) => {
    console.error('seed: 失敗しました', error);
    await prisma.$disconnect();
    process.exit(1);
  });
