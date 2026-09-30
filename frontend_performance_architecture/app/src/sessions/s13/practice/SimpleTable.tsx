import type { ReactNode } from 'react';

/** 列の定義。行の型 T は使う側が決める（この部品は商品を知らない） */
export type Column<T> = {
  header: string;
  render: (row: T) => ReactNode;
  align?: 'left' | 'right';
};

type Props<T> = {
  rows: readonly T[];
  columns: readonly Column<T>[];
  rowKey: (row: T) => string | number;
  empty?: ReactNode;
};

/** 再利用できる表。3つ目の画面で同じ表が必要になった時点で切り出したもの */
export function SimpleTable<T>({ rows, columns, rowKey, empty = '該当するデータはありません' }: Props<T>) {
  if (rows.length === 0) return <p>{empty}</p>;
  return (
    <table>
      <thead>
        <tr>
          {columns.map((c) => (
            <th key={c.header} style={{ textAlign: c.align ?? 'left' }}>
              {c.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={rowKey(row)}>
            {columns.map((c) => (
              <td key={c.header} style={{ textAlign: c.align ?? 'left' }}>
                {c.render(row)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
