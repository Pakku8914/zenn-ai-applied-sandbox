import type { CSSProperties } from 'react';

/** 画面全体で使う見た目の定数。どの feature にも属さないので shared/ui に置く（ここから features は import しない） */
export const pageStyle: CSSProperties = { fontFamily: 'system-ui', padding: 24, maxWidth: 960, margin: '0 auto' };

export const inputStyle: CSSProperties = {
  display: 'block',
  width: '100%',
  padding: 8,
  marginBottom: 16,
  boxSizing: 'border-box',
};

/** ライブリージョンの行。文言が変わっても高さが変わらないよう最小の高さを決めておく */
export const statusStyle: CSSProperties = { minHeight: '1.5em', margin: '4px 0', color: '#374151' };

export const mutedTextStyle: CSSProperties = { margin: '0 0 8px', color: '#6b7280', fontSize: 14 };

/** 後から文言が届く枠。高さを先に決めておくと、届いても周りが動かない（S06） */
export const bannerStyle: CSSProperties = {
  boxSizing: 'border-box',
  height: 280,
  margin: '16px 0',
  padding: 24,
  borderRadius: 12,
  background: '#fef3c7',
  fontSize: 16,
};
