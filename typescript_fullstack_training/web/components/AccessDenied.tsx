// 認可に失敗したことを伝える表示（セッション25）。
// 401（ログインが必要）と 403（権限が足りない）の2つを1つの部品で扱う。

import Link from 'next/link';

type AccessDeniedProps = {
  status: 401 | 403;
  description: string;
};

export function AccessDenied({ status, description }: AccessDeniedProps) {
  const title = status === 401 ? 'ログインが必要です' : '権限がありません';

  return (
    <div>
      <h1>{`${status} ${title}`}</h1>

      <p>{description}</p>

      <p>
        <Link href="/">トップページへ戻る</Link>
      </p>
    </div>
  );
}
