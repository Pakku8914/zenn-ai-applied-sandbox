# AIP-C01 教材サンドボックス

『AWS認定 Generative AI Developer – Professional（AIP-C01）アクティブリコール合格教材』の動作確認用環境です。
**AWS アカウント不要・課金ゼロ**で、Amazon Bedrock の主要 API を `boto3` から呼び出せます。

## 起動

```bash
docker compose up -d                          # 4サービス（実測: イメージ既存時 6秒で healthy）
docker compose exec app python src/session00/hello_bedrock.py
docker compose exec app bash verify-all.sh    # 全検証（実測: 1,311チェック + pytest 9件 / 約50秒）
```

環境が組み上がったかだけを確かめたいときは、セッション0のスモークテスト（47チェック / 約4秒）を使います。

```bash
docker compose exec app python src/session00/verify.py
```

ハイブリッド検索の章だけ OpenSearch を追加起動します（実測: 応答まで29秒）。OpenSearch を止めた状態でも
`verify-all.sh` は通ります（ハイブリッド検索の章の検査だけがスキップされ、1,293チェックになります）。

```bash
docker compose --profile search up -d opensearch
docker compose stop opensearch
```

## 構成

| サービス | ホストポート | 役割 |
| :--- | :--- | :--- |
| `bedrock-mock` | 18080 | Bedrock 互換 API（`/docs` で一覧） |
| `localstack` | 14566 | S3 / DynamoDB / SQS / SNS / IAM / Step Functions ほか |
| `postgres` | 15432 | pgvector 入り PostgreSQL（`doc_chunks`） |
| `opensearch` | 19200 | ハイブリッド検索用（プロファイル `search`） |
| `app` | — | 演習コードの実行環境（`sleep infinity`） |

## モックが実装している API

| クライアント | API |
| :--- | :--- |
| `bedrock` | ListFoundationModels |
| `bedrock-runtime` | InvokeModel / InvokeModelWithResponseStream / Converse / ConverseStream / ApplyGuardrail |
| `bedrock-agent-runtime` | Retrieve / RetrieveAndGenerate / Rerank |

Anthropic 形式・Nova 形式・Meta 形式の3種のネイティブリクエストに対応しており、
Converse API がそれらを吸収することを実際に確かめられます。

## モック専用の制御 API

障害を意図したタイミングで確実に起こすための仕組みです（リトライ・フェイルオーバー・
サーキットブレーカー・コスト監視の演習に使います）。

```bash
# 次の2回をスロットリングさせる
curl -X POST http://localhost:18080/_mock/behavior -H 'Content-Type: application/json' \
     -d '{"throttle_next": 2}'

# トークン・キャッシュ・スロットリング回数・モデル別推定コスト
curl http://localhost:18080/_mock/usage

# 状態を初期化（各 verify の冒頭で必ず呼ぶ）
curl -X POST http://localhost:18080/_mock/reset
```

設定できる項目は `bedrock_mock/behavior.py` の `Behavior` を参照してください。

## 注意

- 単価は `bedrock_mock/catalog.py` の**教材用の固定値**です。実際の請求額の見積もりには使えません。
- 埋め込みは文字 n-gram のハッシュによる決定的なベクトルで、実 Titan Embeddings の意味理解はありません
  （ベクトル検索の仕組みを学ぶには十分ですが、検索品質そのものを論じる用途には使えません）。
- LocalStack Community は Bedrock 系 API に非対応です。そのため Bedrock だけ自前モックを使っています。
