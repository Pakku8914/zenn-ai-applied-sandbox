# 動作確認用サンドボックス

Zenn の書籍「[手を動かして学ぶ React + TypeScript 実践入門 ― Vite で作る型安全なモダンフロントエンド（SPA）](https://zenn.dev/pakku8914/books/react_frontend_training)」（近日公開）のコード例を動かして確認するための、Vite + React + TypeScript の最小プロジェクトです。

## ねらい

- 読者が **コマンド一発** で開発環境を起動し、本文のコード例をそのまま動かせるようにする。
- 執筆したコード例を **実機で検証** し、壊れたコードが本文に混入するのを防ぐ。
- Docker（Linux コンテナ）で動かすため、**Windows / Mac の差異が消える**。

## 前提

- Docker Desktop（Windows / Mac）がインストール済みであること。
- ホスト側に Node.js は不要です（コンテナ内の Node.js を使います）。

## 使い方（One-step 起動）

ホスト側のターミナルで、このディレクトリ（`react_frontend_training/`）に移動してから実行します。

```bash
# 0. 取得して、このディレクトリへ移動
git clone https://github.com/Pakku8914/zenn-ai-applied-sandbox.git
cd zenn-ai-applied-sandbox/react_frontend_training

# 1. 起動（初回はイメージのビルドと npm install が走るため数分かかります）
docker compose up -d

# 2. ブラウザで開く
#    http://localhost:5173

# 3. 後片付け（コンテナ停止）
docker compose down
```

起動後、`src/App.tsx` を編集して保存すると、ブラウザが自動で更新されます（HMR）。これが React 開発の基本サイクルです。

## コンテナ内でコマンドを実行する（型チェック・ビルド）

```bash
# 型チェック
docker compose exec app npm run typecheck

# 本番ビルド（dist/ が生成される）
docker compose exec app npm run build

# シェルに入って自由に操作する
docker compose exec app sh
```

## 構成

| ファイル / ディレクトリ | 役割 |
| :--- | :--- |
| `docker-compose.yml` | `app` サービス。ローカルをバインドマウントし 5173 を公開 |
| `Dockerfile` | `node:22.12.0-bookworm-slim`（タグ固定）。`npm install` 済みのイメージ |
| `vite.config.ts` | `host: '0.0.0.0'` と `watch.usePolling: true`（Docker での HMR の要） |
| `src/` | `main.tsx`（エントリ）・`App.tsx`（最小の動作確認コンポーネント） |
| `.gitattributes` / `.editorconfig` | 改行コードを LF に固定（CRLF 混入防止） |

## バージョン

| ツール | バージョン |
| :--- | :--- |
| Node.js | 22.12.0（LTS・タグ固定） |
| React / React DOM | 19 系 |
| TypeScript | 5.7 系 |
| Vite | 6 系 |

## トラブルシューティング

| 症状 | 原因 | 対処 |
| :--- | :--- | :--- |
| `http://localhost:5173` が開けない | `--host`（0.0.0.0 待ち受け）が効いていない | `docker compose logs app` を確認。`vite.config.ts` の `server.host` を確認 |
| 保存しても画面が更新されない | バインドマウント越しのファイル監視が効いていない | `vite.config.ts` の `watch.usePolling: true` を確認し再起動 |
| `port is already allocated` | 5173 が他プロセスで使用中 | 使用中のプロセスを止めるか、`docker-compose.yml` の公開ポートを変更 |
| 依存を追加したのに反映されない | イメージ内の `node_modules` が古い | `docker compose build --no-cache` で作り直す |

## セッションが進んだら

ルーティング（`react-router-dom`）やテスト（`vitest` / `@testing-library/react`）など、各セッションで使うライブラリは進行に合わせて `package.json` に追加します。追加後は `docker compose build` でイメージを作り直してください。
