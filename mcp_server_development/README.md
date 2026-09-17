# 動作確認用サンドボックス（MCP サーバー開発）

Zenn の書籍「[手を動かして学ぶ MCP サーバー開発実践 ― Model Context Protocol で AI に自社のツールとデータをつなぐ](https://zenn.dev/pakku8914/books/mcp_server_development)」（近日公開）の
コード例を実際に動かすための Docker 環境です。TypeScript と Python の 2 つの
SDK を同じ手順で扱えるように、サービスを 2 つ用意しています。

## 前提

- Docker Desktop（Windows / Mac）または Rancher Desktop が起動していること
- `docker compose` が v2 以降であること（`docker compose version` で確認）

ホスト側に Node.js や Python を入れる必要はありません。すべてコンテナの中で実行します。
コンテナの中は Linux なので、Windows と Mac で同じ結果になります。

## 起動と疎通確認

Windows（PowerShell）でも Mac（zsh / bash）でも、コマンドは同一です。

```bash
# リポジトリを取得し、このディレクトリ（mcp_server_development/）へ移動してから
git clone https://github.com/Pakku8914/zenn-ai-applied-sandbox.git
cd zenn-ai-applied-sandbox/mcp_server_development
docker compose up -d --build

# TypeScript 側の疎通確認（initialize → tools/list → tools/call）
docker compose exec node npm run smoke

# Python 側の疎通確認（同じ 3 ステップ）
docker compose exec python python src/smoke.py
```

期待される出力（TypeScript 側）:

```text
[sandbox-server] stdio でリクエストを待機しています
[1/3] 接続成功: sandbox-server v1.0.0
[2/3] tools/list: add
[3/3] tools/call: 2 + 3 = 5
OK: サンドボックスは正常に動作しています
```

期待される出力（Python 側）:

```text
[sandbox-server] stdio でリクエストを待機しています
[1/3] 接続成功: sandbox-server v1.0.0
[2/3] tools/list: add
[3/3] tools/call: 2.0 + 3.0 = 5.0
OK: サンドボックスは正常に動作しています
```

停止・破棄:

```bash
docker compose down
```

## 全セッションの検証（verify-all）

本書のコード例は、すべてこのサンドボックスで実行して確認しています。その確認は
**誰でも同じ手順で再現できます**。章を直したときに壊れていないかも、これで分かります。

```bash
# TypeScript・Python の両方をまとめて（1 つでも失敗したら非 0 で終了）
./verify-all.sh

# HTTP 章（認可サーバーを 9100、MCP サーバーを 3939 で起動する）を飛ばす場合
SKIP_HTTP=1 ./verify-all.sh
```

サービスごとにコンテナの中で直接叩くこともできます。

```bash
docker compose exec node   sh verify-all.sh
docker compose exec python sh verify-all.sh
```

| 段 | node サービス | python サービス |
| :- | :--- | :--- |
| 1 | `npm run typecheck` | `python -m pytest -q`（58 件） |
| 2 | `npx vitest run`（213 件） | `src/*/verify*.py`（9 本） |
| 3 | Inspector CLI での E2E | — |
| 4 | `src/*/verify*.ts`（stdio、13 本） | — |
| 5 | HTTP 章（`verify-auth.ts` / `verify-http.ts`） | — |

> **メモ**
> 5 段目だけは認可サーバーと MCP サーバーの起動・停止を伴うため、ポートの競合に弱く
> なります。GitHub Actions のワークフロー例（`.github/workflows/mcp-server-ci.yml`）に
> 載せていないのはこのためです。CI には安定して回るものだけを置き、HTTP は手元で
> リリース前に 1 回叩く運用にしています。

## よく使うコマンド

| 目的 | コマンド |
| :--- | :------- |
| TypeScript サーバーを stdio で起動 | `docker compose exec node npm run server` |
| TypeScript の型チェック | `docker compose exec node npm run typecheck` |
| TypeScript のテスト | `docker compose exec node npm test` |
| MCP Inspector（CLI モード）でツール一覧を確認 | `docker compose exec node npm run inspect` |
| Python サーバーを stdio で起動 | `docker compose exec python python src/server.py` |
| Python のテスト | `docker compose exec python python -m pytest -q` |
| コンテナ内のシェルに入る | `docker compose exec node bash` / `docker compose exec python bash` |

> **メモ**
> `npm run server` や `python src/server.py` を単体で実行すると、何も表示されずに止まって
> 見えます。これは異常ではありません。stdio トランスポートのサーバーは標準入力から
> JSON-RPC のリクエストが来るのを待っているだけです。`Ctrl+C` で終了できます。

## 構成

```text
mcp_server_development/
├── docker-compose.yml     # node / python の 2 サービス（ポートは 127.0.0.1 のみ公開）
├── verify-all.sh          # 全セッションの検証をまとめて実行する（ホスト側から叩く）
├── .github/workflows/     # セッション13 の CI 教材（この位置では実行されない・見本）
├── docs/                  # セッション15 のインシデント Runbook 教材
├── node/                  # TypeScript 側
│   ├── Dockerfile         # node:22.23.2-bookworm-slim（タグ固定）
│   ├── package.json       # 依存はすべて完全一致のバージョンで固定
│   ├── package-lock.json
│   ├── tsconfig.json
│   ├── verify-all.sh      # コンテナ内で回す検証（typecheck → vitest → E2E → verify）
│   └── src/
│       ├── create-server.ts  # サーバーの組み立て（トランスポート非依存）
│       ├── server.ts         # stdio で起動するエントリーポイント
│       ├── server.test.ts    # インメモリトランスポートでのテスト例
│       ├── smoke.ts          # 子プロセスとして server.ts を起動して叩く疎通確認
│       └── sessionNN/        # 各セッションのコードと verify スクリプト
└── python/                # Python 側
    ├── Dockerfile         # python:3.13.14-slim-bookworm（タグ固定）
    ├── requirements.txt   # 依存はすべて `==` で固定
    ├── pytest.ini
    ├── verify-all.sh      # コンテナ内で回す検証（pytest → verify）
    └── src/
        ├── server.py         # stdio で起動する最小サーバー
        ├── test_server.py    # インメモリトランスポートでのテスト例
        ├── smoke.py          # 子プロセスとして server.py を起動して叩く疎通確認
        └── sessionNN/        # 各セッションのコードと verify スクリプト
```

各セッションのコードは `node/src/sessionNN/` および `python/src/sessionNN/` に入っています。
本文を読みながら自分で書く場合も、詰まったときの答え合わせに使えます。

追跡していないもの（実行すれば再生成されます）:

- `node/src/**/release-candidate/` — セッション横断復習5 のスクリプトが生成するリリース候補
- `**/dist/` `*.tgz` — `tsc` と `npm pack` の成果物
- `**/.env` — セッション14 の混入デモ用ダミー。本文に中身が載っているので、その場で作ってください
  （`.env` を追跡しないこと自体が、この章で学ぶ内容です）

> **注意**
> 起動すると `node/node_modules/` という**空のディレクトリ**がホスト側に作られます。これは
> Docker が匿名ボリュームのマウント先として用意するもので、中身はコンテナ内にあります。
> **削除しないでください。** 削除すると実行中のコンテナから依存パッケージが見えなくなり、
> `sh: 1: tsx: not found` のようなエラーになります（`docker compose up -d --force-recreate node`
> で復旧できます）。`.gitignore` 済みなのでコミットには含まれません。

## バージョン（基準日：2026-08-05）

| 項目 | バージョン |
| :--- | :--------- |
| Node.js | 22.23.2（Docker イメージ `node:22.23.2-bookworm-slim`） |
| `@modelcontextprotocol/sdk`（TypeScript） | 1.30.0 |
| `zod` | 4.4.3 |
| `vitest` | 4.1.10 / `typescript` 5.9.3 / `tsx` 4.23.7 |
| `@modelcontextprotocol/inspector` | 2.0.0 |
| `@cfworker/json-schema` | 4.1.1（`@modelcontextprotocol/sdk` の peerDependency。`outputSchema` の検証に使われる。明示的に固定するため直接依存として記載している） |
| Python | 3.13.14（Docker イメージ `python:3.13.14-slim-bookworm`） |
| `mcp`（Python SDK） | 2.0.0 |
| `pytest` | 8.4.2 / `pytest-asyncio` 1.2.0 |
| MCP プロトコル仕様（TypeScript SDK の最新対応） | `2025-11-25`（`2024-10-07` まで後方互換） |
| MCP プロトコル仕様（Python SDK の最新対応） | ハンドシェイク世代 `2025-11-25` ／ modern 世代 `2026-07-28` |

> **注意**
> MCP は仕様の改訂が速い領域です。特に次の 2 点は陳腐化しやすいので、本書のコードが
> 動かないときは最初にここを疑ってください。
>
> - **Python SDK の高水準クラス名**：`mcp` 2.0 で `FastMCP` → `MCPServer` に変わりました
>   （`from mcp.server.mcpserver import MCPServer`）。Web 上の 1.x 向けサンプルは動きません。
> - **モデルのフィールド名**：`mcp` 2.0 は snake_case（`server_info`）です。1.x は camelCase
>   （`serverInfo`）でした。
