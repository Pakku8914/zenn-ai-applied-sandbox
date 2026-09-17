// アプリ全体で共有する PrismaClient（セッション23）。
//
// PrismaClient は接続の入れ物なので、1つのプロセスに1つだけ持つ。
// 開発中はファイルを保存するたびにモジュールが読み直されるため、
// 素朴に new すると接続だけが増え続けて PostgreSQL が
// 「too many connections」で接続を拒否するようになる。
// そこで globalThis（プロセス全体で1つだけある入れ物）に覚えさせて使い回す。

import { PrismaClient } from '@prisma/client';

function createPrismaClient() {
  // 開発中に見たいのは警告とエラー。発行された SQL を見たいときは
  // scripts/n-plus-one-demo.ts のように log: ['query'] のクライアントを別に作る。
  return new PrismaClient({ log: ['warn', 'error'] });
}

// globalThis に生やす箱の形を型で宣言する（as unknown を挟むのは、
// globalThis の既定の型に prisma というプロパティが無いため）。
const globalForPrisma = globalThis as unknown as {
  prisma?: ReturnType<typeof createPrismaClient>;
};

export const prisma = globalForPrisma.prisma ?? createPrismaClient();

// 本番はプロセスが作り直されないので覚えさせる必要がない。
// 覚えさせるのは開発（ホットリロードがある環境）だけ。
if (process.env.NODE_ENV !== 'production') {
  globalForPrisma.prisma = prisma;
}
