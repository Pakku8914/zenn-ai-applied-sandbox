# 動作確認用サンドボックス（TypeScript / Next.js）

Zenn の書籍「TypeScriptで学ぶ プログラミングの基礎とWebアプリ開発 ― 型の基本からNext.jsでECサイトを作るまで」（近日公開。`https://zenn.dev/pakku8914/books/typescript_fullstack_training`）のコード例を実機検証するための Docker 環境です。`node:24-bookworm-slim` と `postgres:17-alpine` を使い、コンテナ内で TypeScript を実行します。

本書「環境構築」章で読者が作る作業フォルダ（`ts-shop/sandbox`）と同一構成の**完成版**です。

## 読者の方へ

- 作業は、書籍の「環境構築」章で自分で作る `ts-shop/sandbox` で行います。**このディレクトリを作業場所にしないでください**（全セッションの完成コードが入っています）。
- このディレクトリは、書籍の指示に従って次のファイルをコピーする元として使います。
  - `fixtures/products.json` / `fixtures/categories.json`：「セッション17：非同期処理」でコピー
  - `web/`：「セッション21：Next.js App Routerの基礎」で作業フォルダへ丸ごとコピー
  - `src/<セッション>/verify.ts` など：本文で実行する検証スクリプト。作業フォルダの同じ場所へコピー
- `compose.yaml` のプロジェクト名（`ts-fullstack-sandbox`）は作業フォルダと同じです。**このディレクトリで `docker compose` を実行すると、作業フォルダのコンテナが置き換わります。** 以下の「使い方」は、作業フォルダを使わずに完成版だけを動かす場合の手順です。

## 前提

- Docker Desktop（Windows / Mac）がインストール済みで起動していること

## 使い方（One-step 起動）

このディレクトリ（`typescript_fullstack_training/`。`compose.yaml` がある場所）で実行します。Windows / Mac 共通です。

```bash
git clone https://github.com/Pakku8914/zenn-ai-applied-sandbox.git
cd zenn-ai-applied-sandbox/typescript_fullstack_training
```

```bash
# 1. コンテナを起動（初回はイメージのダウンロードに数分かかる）
docker compose up -d

# 2. 依存パッケージをインストール（初回のみ）
docker compose exec ts npm install

# 3. 最初のプログラムを実行
docker compose exec ts npx tsx src/hello.ts
# => Hello, TypeScript!

# 4. 全セッションの検証をまとめて実行
docker compose exec ts bash verify-all.sh

# 5. 後片付け（データも消す場合は -v を付ける）
docker compose down
```

## 構成

| パス | 役割 |
| :--- | :--- |
| `compose.yaml` | `ts`（Node.js 24）と `db`（PostgreSQL 17）の2サービス |
| `package.json` | tsx / typescript / vitest / zod |
| `tsconfig.json` | `strict` + `noUncheckedIndexedAccess` を有効化 |
| `verify-all.sh` | 型チェック → 各セッションの `verify.ts` を順に実行。1つでも失敗したら非0終了 |
| `src/hello.ts` | 環境構築章で実行する最初のプログラム |
| `src/sessionNN/` | セッションごとのコード例と `verify.ts` |
| `src/midNN/` | 中間プロジェクトの成果物と `verify.ts`（`verify-all.sh` が拾う） |
| `fixtures/` | 記録済みJSON（ネットワーク接続なしで演習を回すため） |
| `web/` | Session 21 以降の Next.js アプリの完成版（Session 21 で読者が作業フォルダへコピーする） |

## 検証ハーネスの契約

- 各セッションのコード例は `src/sessionNN/verify.ts` で自己検証する。**期待値と一致しなければ非0終了**すること（人が出力を読んで判断する形にしない）。
- 本文に書いた「期待される出力」は、`verify.ts` が実際に出力するものと一致させる。食い違ったら**実機が正**。
- データベースを使うセッションは、`verify.ts` の冒頭で状態をリセットしてから実行する。
- 外部APIや課金が必要な処理は使わない。`fixtures/` の記録済みレスポンスで回るようにする。

## トラブルシューティング

| 症状 | 対処 |
| :--- | :--- |
| `Cannot connect to the Docker daemon` | Docker Desktop が起動しているか確認する |
| `docker compose exec ts` が `service "ts" is not running` | `docker compose up -d` を先に実行する |
| `Cannot find module` | `docker compose exec ts npm install` を実行する |
| Windows でシェルスクリプトが動かない | `.gitattributes` により LF 固定。改行が CRLF になっていないか確認する |
| ポート 5432 が使用中 | ホストで別の PostgreSQL が動いている。`compose.yaml` の `ports` を `"55432:5432"` などに変更する |
