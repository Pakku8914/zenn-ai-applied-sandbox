# zenn-ai-applied-sandbox

Zenn で公開している **AI 応用シリーズ**の演習環境（サンドボックス）をまとめたリポジトリです。書籍ごとにサブディレクトリが分かれています。

各サンドボックスは Docker だけで動き、**APIキーも課金も不要**です（生成側は合成カセットの再生で動きます）。

## 収録している書籍

| ディレクトリ | 書籍 |
| :--- | :--- |
| [`rag_search_engineering/`](./rag_search_engineering) | 手を動かして学ぶ RAG・検索エンジニアリング実践 ― チャンク設計・ハイブリッド検索・リランクで「答えられる検索」を作る |
| [`ai_agent_engineering/`](./ai_agent_engineering) | 手を動かして学ぶ AIエージェント実装実践 ― 計画・ツール編成・メモリ・マルチエージェントを「壊れない形」で作る |
| [`ai_infra_edge_deployment/`](./ai_infra_edge_deployment) | 手を動かして学ぶ AI推論基盤とエッジAI ― サービング・KVキャッシュ・オートスケールからオンデバイス実行まで |

※ 残り1冊（LLMファインチューニングとモデル最適化）は書籍の公開に合わせて追加します。

## 使い方

書籍の「環境構築」章の手順に従ってください。共通する流れは次のとおりです。

```bash
git clone https://github.com/Pakku8914/zenn-ai-applied-sandbox.git
cd zenn-ai-applied-sandbox/<書籍のディレクトリ>
docker compose up -d
docker compose exec app bash verify-all.sh
```

`verify-all.sh` が最後まで通れば、その書籍のコードがすべて手元で再現できている状態です。

## コーパスなどのデータについて

`corpus/` `data/` `fixtures/` `reports/` `traces/` `models/` は**生成物なのでリポジトリに含めていません**。代わりに生成器（`tools/make_corpus.py` / `tools/make_data.py` / `tools/prepare_models.py` など）を配布しています。いずれも固定シード・固定時刻で動くため、誰が何度実行しても同じデータが得られます。

`ai_infra_edge_deployment/` だけは、モデルの取得と GGUF への変換・量子化が初回に必要です（合計 2GB 弱）。手順はそのディレクトリの `README.md` と書籍の「環境構築」章にあります。

## ライセンス

各書籍のディレクトリ内の記載に従ってください。
