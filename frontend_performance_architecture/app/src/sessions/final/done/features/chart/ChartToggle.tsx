import { useState } from 'react';
import { ChunkedChart } from '../../../../s07/chunked/ChunkedChart';

/**
 * グラフの開閉。開いているかどうかは、この部品の中だけで使うローカルな状態なのでここに置く。
 * 最上位に置くと、押すたびに 20,000 件の一覧まで再レンダリングされる。
 * 計算は S07 の分割版（ChunkedChart）を使い、8ms ごとにメインスレッドを譲る。
 */
export function ChartToggle() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen((v) => !v)}>
        {open ? 'グラフを隠す' : 'グラフを表示'}
      </button>
      {open ? <ChunkedChart /> : null}
    </>
  );
}
