import type { ReactNode } from 'react';
import { WebVitals } from './WebVitals';

export const metadata = { title: '計測対象アプリ（Next.js）' };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ja">
      <body>
        {children}
        {/* 計測値を window.__webVitals に貯める（SPA 版と同じ契約） */}
        <WebVitals />
      </body>
    </html>
  );
}
