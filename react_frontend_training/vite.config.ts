/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 動作確認用サンドボックスの Vite 設定。
// Docker（Linux コンテナ）内で開発サーバを動かし、
// ホスト（Windows/Mac）のブラウザから http://localhost:5173 で確認できるようにする。
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0', // コンテナ外（ホスト）からアクセス可能にする
    port: 5173,
    watch: {
      // バインドマウント越しのファイル変更を検知し、Win/Mac の両方で HMR を効かせる
      usePolling: true,
    },
  },
  // セッション10（テスト）用の Vitest 設定。
  test: {
    environment: 'jsdom', // ブラウザ相当の DOM をテストで使えるようにする
    globals: true, // describe/it/expect をインポートなしで使う
    setupFiles: './src/setupTests.ts',
  },
})
