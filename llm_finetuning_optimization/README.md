# 動作確認用サンドボックス（LLMファインチューニングとモデル最適化）

**GPU は不要です。** すべての演習を CPU の Docker 環境で完走できるよう、
小型モデル（1.35億／4.94億パラメータ）と数百件のデータで設計しています。

## 起動

```bash
docker compose up -d --build
docker compose exec app python tools/make_dataset.py
docker compose exec app bash verify-all.sh
```

初回はモデルのダウンロードが走ります（名前付きボリューム `hf-cache` に保存され、
2回目以降は不要です）。

## 使うモデル

| 名前 | パラメータ | 特徴 | 用途 |
| :--- | :--- | :--- | :--- |
| `HuggingFaceTB/SmolLM2-135M-Instruct` | 1.35億 | 速い（fp32・1.8秒/step）。**日本語は苦手** | ループを速く回す練習 |
| `Qwen/Qwen2.5-0.5B-Instruct` | 4.94億 | 日本語が使える。3〜4倍遅い | 実際に精度を上げる演習 |

:::message
0.5B モデルは fp32 だと 2.3GB のメモリを使います。既定の Docker 割り当て（メモリ 4GB 前後）
では他のプロセスと競合して OOM で落ちることがあります。`--dtype bf16` を付けると
0.74GB に収まります（CPU では bf16 の方が遅くなりますが、メモリは半分になります）。
:::

## ディレクトリ

| パス | 内容 |
| :--- | :--- |
| `ftkit/` | 章をまたいで共有する共通ライブラリ（データ・トークナイズ・学習・評価・量子化） |
| `tools/` | データ生成と実測値を出す決定的スクリプト |
| `data/` | データセット（`tools/make_dataset.py` が生成。コミット対象外） |
| `runs/` | 学習・比較の結果 JSON（コミット対象外） |
| `export/` `gguf/` `onnx/` | 書き出したモデル（コミット対象外） |
| `src/sessionNN/` | 各セッションのコードと自己検証スクリプト |

## よく使うコマンド

```bash
# データセットを作り直す（固定シードなので毎回同じ）
docker compose exec app python tools/make_dataset.py

# トークナイザの比較（日本語のトークン膨張を見る）
docker compose exec app python tools/token_stats.py

# 学習の実測（フル微調整と LoRA の比較）
docker compose exec app python tools/bench_train.py --model fast --steps 10

# 本命の実験：学習前後でタスク指標を比較する
docker compose exec app python tools/train_and_eval.py --model fast --steps 60 --eval-n 30
docker compose exec app python tools/train_and_eval.py --model ja --steps 80 --task format --dtype bf16

# 検証（学習を伴う分を飛ばす場合）
docker compose exec -e SKIP_TRAIN=1 app bash verify-all.sh
```

## GGUF への変換と量子化（セッション10）

llama.cpp のコンテナを1回ずつ呼び出します。

```bash
# 1. HuggingFace 形式のモデルを書き出す（LoRA を統合する）
docker compose exec app python -c "..."   # 本文の手順に従う

# 2. GGUF（f16）に変換する
docker compose --profile gguf run --rm llamacpp -c --outtype f16 /work/export/qwen05b

# 3. 量子化する
docker compose --profile gguf run --rm llamacpp \
    -q /work/export/qwen05b/*F16.gguf /work/gguf/qwen05b-q4_k_m.gguf Q4_K_M
```

:::message
`llamacpp` サービスに `working_dir` を指定してはいけません。`--convert` は
イメージ内の作業ディレクトリにある `convert_hf_to_gguf.py` を実行するため、
上書きすると `No such file or directory` になります。
:::

## 停止と片付け

```bash
docker compose down          # コンテナを停止
docker compose down -v       # モデルキャッシュも削除
```
