# 動作確認用サンドボックス（RAG・検索エンジニアリング実践）

本文・練習問題・解答のコード例はすべてこの環境で実行して動作確認しています。
**APIキーは不要**です（生成部分は同梱の合成カセットで回ります）。

## 起動

```bash
docker compose up -d          # app と qdrant が起動する
docker compose exec app bash verify-all.sh
```

初回は埋め込みモデル・リランカのダウンロードが走ります（名前付きボリューム `hf-cache`
に保存されるため2回目以降は不要です）。

セッション5・16 で全文検索エンジンを使う回だけ、次のように追加起動します。

```bash
docker compose --profile search-engine up -d
```

## ディレクトリ

| パス | 内容 |
| :--- | :--- |
| `ragkit/` | 章をまたいで共有する共通ライブラリ（インターフェースを変えない） |
| `tools/` | データ生成と実測値を出す決定的スクリプト。本文の数値はここの出力を転記している |
| `corpus/` | `tools/make_corpus.py` が生成する文書・クエリ・判定データ（コミット対象外） |
| `fixtures/` | `tools/make_fixtures.py` が生成する合成カセット（コミット対象外） |
| `reports/` | 評価レポートの出力先（コミット対象外） |
| `src/sessionNN/` | 各セッションのコードと自己検証スクリプト |

`corpus/` `fixtures/` `reports/` は生成物なので追跡しません。生成器（`tools/`）は追跡します。

## よく使うコマンド

```bash
# データを作り直す（固定シードなので毎回同じ結果になる）
docker compose exec app python tools/make_corpus.py
docker compose exec app python tools/make_fixtures.py

# 統計と実測値
docker compose exec app python tools/corpus_stats.py
docker compose exec app python tools/chunk_stats.py
docker compose exec app python tools/eval_matrix.py --quick   # BM25 のみ（数十秒）
docker compose exec app python tools/eval_matrix.py           # 密ベクトル・ハイブリッドも（数分）
docker compose exec app python tools/bench_embed.py
docker compose exec app python tools/bench_hnsw.py
docker compose exec app python tools/bench_rerank.py
docker compose exec app python tools/bench_hybrid.py

# 検証（モデルを使う分を飛ばす場合）
docker compose exec -e SKIP_DENSE=1 app bash verify-all.sh
```

Qdrant のダッシュボードはホストのブラウザから <http://localhost:6333/dashboard> で開けます。

## 停止と片付け

```bash
docker compose down            # コンテナを停止
docker compose down -v         # ボリューム（Qdrant のデータとモデルキャッシュ）も削除
```
