import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  // 本番用の最小イメージを作るための出力形式。Session 28 で使う。
  output: 'standalone',
  // このフォルダを基準にする。親フォルダにも package-lock.json があるため明示する。
  outputFileTracingRoot: __dirname,

  // 開発サーバーのログ設定（セッション27）。
  // fetch した URL を省略せずに出す。どのデータがキャッシュに当たったかを読むため。
  logging: {
    fetches: { fullUrl: true },
  },

  // 画像最適化の設定（セッション27）。
  // 本書のサンドボックスには画像ファイルを置いていないが、public/images に画像を
  // 置いて next/image で表示すると、この設定で変換・キャッシュされる。
  images: {
    // 対応しているブラウザには軽い形式で配る（元のファイルは差し替えなくてよい）
    formats: ['image/avif', 'image/webp'],
    // 変換した画像を最低30日はキャッシュする（秒）
    minimumCacheTTL: 60 * 60 * 24 * 30,
  },
};

export default nextConfig;
