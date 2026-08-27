# 動作確認用サンドボックス（AIエージェント実装実践）

本文・練習問題・解答のコード例はすべてこの環境で実行して動作確認しています。
**APIキーは不要**です（LLM は決定的なオラクルで置き換えます）。

## 起動

```bash
docker compose up -d          # app と tool-runner が起動する
docker compose exec app python tools/make_data.py
docker compose exec app bash verify-all.sh
```

## 2つのコンテナ

| サービス | 役割 | 制約 |
| :--- | :--- | :--- |
| `app` | エージェント本体を動かす | 通常のコンテナ |
| `tool-runner` | エージェントが書いたコードを実行する | `network_mode: none`／`read_only: true`／メモリ 256MB／PID 64／`cap_drop: ALL` |

`tool-runner` はネットワーク名前空間を持たないため HTTP で依頼を受けられません。
`app` は共有ボリューム（`runner_queue/`）にファイルを置いて依頼し、結果ファイルを待ちます。
不便になった代わりに「外に出る経路が存在しない」という強い保証が得られます。

## ディレクトリ

| パス | 内容 |
| :--- | :--- |
| `agentkit/` | 章をまたいで共有する共通ライブラリ（インターフェースを変えない） |
| `runner/` | 隔離実行ワーカー（標準ライブラリのみで書く） |
| `tools/` | データ生成と実測値を出す決定的スクリプト |
| `scenarios/` | `ScriptedClient` が読むシナリオ（LLM の応答を固定する） |
| `data/` | 業務データ（`tools/make_data.py` が生成。コミット対象外） |
| `workspace/` | エージェントが書き込める作業領域（コミット対象外） |
| `runner_queue/` | 隔離実行の依頼と結果（コミット対象外） |
| `traces/` | 軌跡・トレース・チェックポイント（コミット対象外） |
| `src/sessionNN/` | 各セッションのコードと自己検証スクリプト |

## よく使うコマンド

```bash
# データを作り直す（演習で汚れた状態をリセットする）
docker compose exec app python tools/make_data.py

# 統計と実測値
docker compose exec app python tools/data_stats.py
docker compose exec app python tools/traj_stats.py
docker compose exec app python tools/bench_sandbox.py
docker compose exec app python tools/eval_trajectories.py

# 検証（隔離実行コンテナを使う分を飛ばす場合）
docker compose exec -e SKIP_RUNNER=1 app bash verify-all.sh
```

## 停止と片付け

```bash
docker compose down
```
