// カテゴリタブが届くまでのあいだに出す骨組み（セッション27）。
//
// タブは3件しかないのでほぼ一瞬で届くが、境界を分けておくと
// 「一覧の問い合わせが遅いときでもタブだけ先に出る」状態になる。

export function CategoryTabsSkeleton() {
  return (
    <nav aria-busy="true">
      <span aria-hidden="true">━━━ / ━━━ / ━━━</span>
    </nav>
  );
}
