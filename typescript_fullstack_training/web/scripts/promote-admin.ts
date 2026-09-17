// 利用者を管理者にする道具（最終プロジェクト）。
//
// 実行:
//   docker compose exec ts sh -c 'cd web && node --experimental-strip-types scripts/promote-admin.ts demo@example.com'
//
// 管理画面（/admin）は role が 'admin' の人だけが開ける。新規登録の画面から
// 管理者を作れるようにはしない（誰でも管理者になれてしまうため）。
// だから昇格は「サーバーに入れる人だけができる操作」としてこの道具に閉じ込める。
//
// role を戻したいときは第2引数に user を渡す。

import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();

type Role = 'user' | 'admin';

function parseRole(raw: string | undefined): Role {
  return raw === 'user' ? 'user' : 'admin';
}

async function main(): Promise<void> {
  const email = process.argv[2];
  const role = parseRole(process.argv[3]);

  if (email === undefined || email === '') {
    throw new Error('メールアドレスを指定してください（例: demo@example.com）');
  }

  // updateMany を使うと、存在しないメールアドレスでも例外にならず count: 0 になる
  const updated = await prisma.user.updateMany({ where: { email }, data: { role } });

  if (updated.count === 0) {
    console.log(`promote-admin: ${email} という利用者は見つかりませんでした`);

    return;
  }

  console.log(`promote-admin: ${email} の role を ${role} にしました`);
}

main()
  .then(async () => {
    await prisma.$disconnect();
  })
  .catch(async (error: unknown) => {
    console.error('promote-admin: 失敗しました', error);
    await prisma.$disconnect();
    process.exit(1);
  });
