import { existsSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// サンドボックス内でアクセスを許可するホスト名（compose のサービス名とネットワーク別名）
const ALLOWED_HOSTS = ['app', 'app.test', 'preview', 'preview.test', 'localhost'];

// 各セッションの改善版は pages/<名前>/index.html に置いた別ページとして配信する。
// 出発点（ルートの index.html）を書き換えずに、改善前後を同じ条件で並べて計測するため。
const pagesDir = resolve(import.meta.dirname, 'pages');
const pageEntries = Object.fromEntries(
  (existsSync(pagesDir) ? readdirSync(pagesDir) : [])
    .filter((name) => existsSync(resolve(pagesDir, name, 'index.html')))
    .map((name) => [name, resolve(pagesDir, name, 'index.html')]),
);

export default defineConfig({
  plugins: [react()],
  build: {
    // バンドル解析の章で中身を読むため、圧縮しても名前が追える形にしておく
    sourcemap: true,
    rollupOptions: {
      input: { main: resolve(import.meta.dirname, 'index.html'), ...pageEntries },
    },
  },
  server: {
    // Vite は DNS リバインディング対策で、既定では localhost 以外のホスト名からの
    // アクセスを拒否する（Blocked request. This host is not allowed.）。
    // 計測用コンテナからはサービス名で来るため、両方を明示的に許可する。
    allowedHosts: ALLOWED_HOSTS,
    watch: {
      usePolling: true,
    },
  },
  preview: {
    // server と preview は設定が別。preview 側にも同じ許可が必要（忘れやすい）
    allowedHosts: ALLOWED_HOSTS,
  },
});
