/**
 * S06：価格バーの描画（レイアウトスラッシングの題材）。
 * React の再レンダリングとは切り離して「DOM の読み書きの順番」だけを比べるため、DOM を直接操作する。
 */
export type BarRow = {
  row: HTMLElement;
  track: HTMLElement;
  bar: HTMLElement;
  stock: HTMLElement;
  price: number;
};

/** バーの長さの基準（products.ts の生成式では価格は最大 9,999 円） */
const PRICE_SCALE = 10_000;

/** バーの中に価格ラベルを置ける最小の幅。これより細いバーは色を変えて示す */
export const LABEL_MIN_PX = 60;

/** 枠の幅と価格からバーの幅（px）を決める。DOM に触らない純粋な計算 */
export function barWidthPx(trackWidth: number, price: number): number {
  return Math.round((trackWidth * price) / PRICE_SCALE);
}

export function collectRows(list: HTMLElement): BarRow[] {
  return [...list.querySelectorAll<HTMLElement>('li.bar-row')].map((row) => {
    const track = row.querySelector<HTMLElement>('.bar-track');
    const bar = row.querySelector<HTMLElement>('.bar');
    const stock = row.querySelector<HTMLElement>('.bar-stock');
    if (!track || !bar || !stock) {
      throw new Error('価格バーの行の構造が想定と違います');
    }
    return { row, track, bar, stock, price: Number(row.dataset.price) };
  });
}

/** 実験の前に、すべてのバーを描く前の状態に戻す（書き込みだけなのでレイアウトは起きない） */
export function resetBars(rows: readonly BarRow[]): void {
  for (const { bar } of rows) {
    bar.style.width = '0px';
    bar.classList.remove('narrow');
  }
}

/** Bad：1行ごとに「読む → 書く」を繰り返す。読むたびにブラウザはその場でレイアウトをやり直す */
export function drawBarsThrashing(rows: readonly BarRow[]): void {
  for (const { track, bar, price } of rows) {
    const width = track.clientWidth; // 読み取り：直前の書き込みを反映するため、強制同期レイアウトが走る
    bar.style.width = `${barWidthPx(width, price)}px`; // 書き込み：レイアウトを「古い」状態に戻す
  }
}

/** Good：先に全部読み、あとで全部書く。レイアウトは読み取りの最初の1回だけで済む */
export function drawBarsBatched(rows: readonly BarRow[]): void {
  const plan = rows.map(({ track, bar, price }) => ({ bar, width: barWidthPx(track.clientWidth, price) }));
  for (const { bar, width } of plan) {
    bar.style.width = `${width}px`;
  }
}

/** 練習問題4の Bad：書いた結果（バーの実際の幅）を読んで、細いバーに印を付ける */
export function markNarrowThrashing(rows: readonly BarRow[]): void {
  for (const { track, bar, price } of rows) {
    bar.style.width = `${barWidthPx(track.clientWidth, price)}px`;
    bar.classList.toggle('narrow', bar.offsetWidth < LABEL_MIN_PX); // 書いた直後に読む
  }
}

/** 練習問題4の Good：「読む → 書く → 読む → 書く」を段階ごとにまとめる。行数によらずレイアウトは最大2回 */
export function markNarrowPhased(rows: readonly BarRow[]): void {
  const plan = rows.map(({ track, bar, price }) => ({ bar, width: barWidthPx(track.clientWidth, price) })); // 読む
  for (const { bar, width } of plan) {
    bar.style.width = `${width}px`; // 書く
  }
  const narrow = plan.map(({ bar }) => ({ bar, isNarrow: bar.offsetWidth < LABEL_MIN_PX })); // 読む（ここで1回だけレイアウト）
  for (const { bar, isNarrow } of narrow) {
    bar.classList.toggle('narrow', isNarrow); // 書く
  }
}

/** contain の実験：1行の在庫表示を書き換えてはその行の高さを読む、を times 回繰り返す */
export function editStock(rows: readonly BarRow[], times: number): void {
  for (let i = 0; i < times; i += 1) {
    const target = rows[(i * 7) % rows.length];
    if (!target) return;
    target.stock.textContent = `在庫 ${i % 100}`;
    void target.row.offsetHeight; // 1行だけ変えても、読むたびにレイアウトが走る
  }
}
