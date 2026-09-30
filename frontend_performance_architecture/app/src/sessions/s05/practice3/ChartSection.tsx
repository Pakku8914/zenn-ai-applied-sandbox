import { lazy, Suspense } from 'react';

// 練習問題3の解答。lazy はモジュールの最上位で1回だけ呼び、名前付きエクスポートは詰め替える
const HeavyChart = lazy(() =>
  import('../../../components/HeavyChart').then((m) => ({ default: m.HeavyChart })),
);

export function ChartSection({ show }: { show: boolean }) {
  if (!show) return null;
  // 境界はグラフの区画だけを包む。待っている間も入力と一覧はそのまま表示される
  return (
    <Suspense fallback={<p role="status">グラフを読み込み中…</p>}>
      <HeavyChart />
    </Suspense>
  );
}
