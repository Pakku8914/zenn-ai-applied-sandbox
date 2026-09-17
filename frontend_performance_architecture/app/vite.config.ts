import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// サンドボックス内でアクセスを許可するホスト名（compose のサービス名とネットワーク別名）
const ALLOWED_HOSTS = ['app', 'app.test', 'preview', 'preview.test', 'localhost'];

export default defineConfig({
  plugins: [react()],
  build: {
    // バンドル解析の章で中身を読むため、圧縮しても名前が追える形にしておく
    sourcemap: true,
    rollupOptions: {
      output: {
        // 手動チャンク分割の効果を測るための起点。S 内で読者が変更する
        manualChunks: undefined,
      },
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
