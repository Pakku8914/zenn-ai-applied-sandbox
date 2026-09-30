import { RenderedAt } from '../../lib/s12/RenderedAt';

export const metadata = { title: 'S12 ISR' };
// 3,600 秒たつまでは作り置きを返し、それを過ぎたアクセスを契機に裏で作り直す（ISR）
export const revalidate = 3600;

export default function Page() {
  return (
    <main>
      <h1>ISR：作り置きを一定時間ごとに作り直す HTML</h1>
      <RenderedAt />
    </main>
  );
}
