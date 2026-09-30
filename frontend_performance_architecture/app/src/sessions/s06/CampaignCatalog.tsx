import { StrictMode, useEffect, useState, type CSSProperties } from 'react';
import { createRoot } from 'react-dom/client';
import { ProductList } from '../../components/ProductList';

/**
 * S06：後から挿入されるキャンペーンバナーと CLS。
 * バナーの文言は「少し遅れて届く」想定で、表示の仕方（mode）だけを変えて比べる。
 *   late     … Bad。届いてから一覧の上に差し込む（一覧が押し下げられる）
 *   reserved … Good。最初から同じ高さの枠を確保しておき、届いたら中身だけを入れる
 *   overlay  … Good。一覧の流れに入れず、画面下に重ねて出す
 */
export type BannerMode = 'late' | 'reserved' | 'overlay';

/** 文言が届くまでの時間（擬似）。measure/src/session06/verify-cls.ts はこれより長く待ってから CLS を読む */
export const CAMPAIGN_DELAY_MS = 300;
/** 商品写真つきのバナーを想定した高さ。CLS は距離をビューポートの長辺（1280px）で割るので、小さいずれは数値に出にくい */
export const BANNER_HEIGHT_PX = 280;

const CAMPAIGN_TEXT = '今週末は送料無料。3,000 円以上のご注文が対象です。';

const bannerStyle: CSSProperties = {
  boxSizing: 'border-box',
  height: BANNER_HEIGHT_PX,
  margin: '0 0 16px',
  padding: 24,
  borderRadius: 12,
  background: '#fef3c7',
  fontSize: 20,
};

function useCampaignText(): string | null {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    const id = setTimeout(() => setText(CAMPAIGN_TEXT), CAMPAIGN_DELAY_MS);
    return () => clearTimeout(id);
  }, []);
  return text;
}

function CampaignBanner({ mode }: { mode: BannerMode }) {
  const text = useCampaignText();

  if (mode === 'reserved') {
    // 文言の有無にかかわらず高さは同じ。届いても周りは動かない
    return (
      <aside style={bannerStyle} data-campaign={text === null ? 'pending' : 'loaded'}>
        {text}
      </aside>
    );
  }
  // 文言が届くまで何も描かない。届いた瞬間に高さ 280px の枠が現れ、一覧を押し下げる（late の場合）
  if (text === null) {
    return null;
  }
  if (mode === 'overlay') {
    // position: fixed は通常の流れから外れるので、出現しても他の要素を押さない
    return (
      <aside
        style={{ ...bannerStyle, position: 'fixed', left: 24, right: 24, bottom: 24, margin: 0 }}
        data-campaign="loaded"
      >
        {text}
      </aside>
    );
  }
  return (
    <aside style={bannerStyle} data-campaign="loaded">
      {text}
    </aside>
  );
}

export function mountCampaignCatalog(mode: BannerMode): void {
  const rootElement = document.getElementById('root');
  if (!rootElement) {
    throw new Error('#root が見つかりません');
  }
  createRoot(rootElement).render(
    <StrictMode>
      <main style={{ fontFamily: 'system-ui', padding: 24, maxWidth: 960, margin: '0 auto' }}>
        <h1>商品カタログ</h1>
        <CampaignBanner mode={mode} />
        <ProductList keyword="" />
      </main>
    </StrictMode>,
  );
}
