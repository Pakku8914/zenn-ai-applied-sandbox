# 動作確認用サンドボックス（AI推論基盤とエッジAI）

**GPU は不要です。** CPU で動く推論サーバ（llama.cpp）を立て、負荷をかけ、
飽和点を測り、エッジ側の量子化まで一通り確認できます。

## 準備（初回のみ）

```bash
# 1. モデルを取得する
docker compose run --rm --no-deps app python tools/prepare_models.py

# 2. GGUF（f16）に変換する
docker compose --profile prepare run --rm llamacpp -c --outtype f16 /work/models/hf/qwen05b

# 3. 量子化する
docker compose --profile prepare run --rm llamacpp \
    -q /work/models/hf/qwen05b/Qwen05B-494M-F16.gguf /work/models/gguf/qwen05b-q8_0.gguf Q8_0
docker compose --profile prepare run --rm llamacpp \
    -q /work/models/hf/qwen05b/Qwen05B-494M-F16.gguf /work/models/gguf/qwen05b-q4_k_m.gguf Q4_K_M

# 4. f16 も比較用にコピーする
cp models/hf/qwen05b/Qwen05B-494M-F16.gguf models/gguf/qwen05b-f16.gguf
```

:::message
`llamacpp` サービスに `working_dir` を指定してはいけません。`--convert` はイメージ内の
作業ディレクトリにある `convert_hf_to_gguf.py` を実行するため、上書きすると失敗します。
:::

## 起動

```bash
docker compose up -d          # llama（推論サーバ）→ app → gateway の順に立つ
docker compose exec app bash verify-all.sh
```

`gateway` は `llama` が Healthy になるまで起動しません（モデルのロードを待つ）。

## サービス

| サービス | 役割 | 起動 |
| :--- | :--- | :--- |
| `llama` | 推論サーバ（llama.cpp） | 既定 |
| `app` | クライアント・負荷生成・エッジ実験 | 既定 |
| `gateway` | レート制限・バックプレッシャ・キャッシュ | 既定 |
| `llamacpp` | GGUF 変換・量子化 | `--profile prepare`（1回ずつ） |
| `prometheus` | メトリクス収集 | `--profile metrics` |

推論サーバの設定は環境変数で切り替えられます。

```bash
MODEL_FILE=qwen05b-q8_0.gguf SLOTS=1 CTX=1024 THREADS=2 docker compose up -d llama
```

## よく使うコマンド

```bash
# 実行環境とモデルの一覧
docker compose exec app python tools/env_report.py

# 推論サーバのベンチマーク（飽和点を探す）
docker compose exec app python tools/bench_serve.py --concurrency 1 2 4 8
docker compose exec app python tools/bench_serve.py --no-warmup   # ウォームアップ無しの跳ね

# KVキャッシュの計算
docker compose exec app python tools/bench_kvcache.py

# エッジ側（ONNX の int8 量子化とスレッド数）
docker compose exec app python tools/make_edge_model.py
docker compose exec app python tools/bench_edge.py --threads 1 2 4

# 検証（推論サーバを使う分を飛ばす場合）
docker compose exec -e SKIP_SERVER=1 app bash verify-all.sh
```

## Kubernetes マニフェストの検証（セッション8）

**クラスタも kubectl も要りません。** 推論ワークロード固有の要件（ロード完了を
待つ Probe・KVキャッシュ込みのメモリ要求・停止の猶予）を静的に検査します。

```bash
docker compose exec app python src/session08/lint_manifest.py --explain k8s/inference-deployment.yaml
docker compose exec app python src/session08/lint_manifest.py src/session08/bad-probes.yaml   # 落ちる例
```

kubectl を使った追加確認をしたい場合は、`profiles: [k8s]` の道具コンテナがあります
（クラスタは不要ですが、既定の検証はクラスタの OpenAPI を見に行くため
`--validate=false` を付けます）。

```bash
docker compose --profile k8s run --rm kubectl apply --dry-run=client --validate=false -f k8s/inference-deployment.yaml
```

kind でクラスタを立てる手順は `k8s/kind-cluster.yaml` のコメントにあります（任意。
2コア・メモリ 5.8GB の環境では起動しません）。

## オートスケールの検証（セッション9）

**クラスタも kubectl も要りません。** 容量計画を計算し、その計画と HPA の
マニフェストが矛盾していないかを静的に検査します（`minReplicas` が 0 でないか、
CPU 使用率だけでスケールしていないか、スケールインがスケールアウトより
保守的か、対象の Deployment が実在するか）。

```bash
# 容量計画（何本必要か・スケールの遅れ）
docker compose exec app python src/session09/plan.py
docker compose exec app python src/session09/plan.py --lag --weights-mib 4700

# HPA の検査（対象の Deployment も一緒に渡す）
docker compose exec app python src/session09/lint_hpa.py --plan --explain \
  k8s/hpa.yaml k8s/inference-deployment.yaml
docker compose exec app python src/session09/lint_hpa.py --plan \
  src/session09/bad-hpa.yaml k8s/inference-deployment.yaml   # 落ちる例
```

## 停止と片付け

```bash
docker compose down
docker compose down -v   # ボリュームも削除
```

`models/` と `reports/` は生成物なので追跡していません。消しても準備手順で作り直せます。
