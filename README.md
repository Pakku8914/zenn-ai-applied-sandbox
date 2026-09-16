# zenn-ai-applied-sandbox

Zenn で公開している書籍（[Pakku8914 の本](https://zenn.dev/pakku8914)）の演習環境（サンドボックス）をまとめたリポジトリです。書籍ごとにサブディレクトリが分かれています。

各サンドボックスは Docker だけで動きます。AI 応用シリーズと AWS 生成AI 資格教材は **APIキーも課金も不要**です（生成側は合成カセットの再生、または API 互換のローカルモックで動きます）。

## 収録している書籍

| ディレクトリ | 書籍 |
| :--- | :--- |
| [`rag_search_engineering/`](./rag_search_engineering) | 手を動かして学ぶ RAG・検索エンジニアリング実践 ― チャンク設計・ハイブリッド検索・リランクで「答えられる検索」を作る |
| [`ai_agent_engineering/`](./ai_agent_engineering) | 手を動かして学ぶ AIエージェント実装実践 ― 計画・ツール編成・メモリ・マルチエージェントを「壊れない形」で作る |
| [`ai_infra_edge_deployment/`](./ai_infra_edge_deployment) | 手を動かして学ぶ AI推論基盤とエッジAI ― サービング・KVキャッシュ・オートスケールからオンデバイス実行まで |
| [`aws_genai_developer_pro_active_recall/`](./aws_genai_developer_pro_active_recall) | AWS認定 Generative AI Developer – Professional（AIP-C01）アクティブリコール合格教材（近日公開） |
| [`llm_finetuning_optimization/`](./llm_finetuning_optimization) | 手を動かして学ぶ LLMファインチューニングとモデル最適化 ― SFT・LoRA・DPO・量子化・蒸留をCPUだけで一巡させる（近日公開） |
| [`network_protocols_practical_training/`](./network_protocols_practical_training) | [手を動かして学ぶ コンピュータネットワーク実践入門 ― パケットで追う TCP/IP・HTTP・DNS・TLS の仕組み](https://zenn.dev/pakku8914/books/network_protocols_practical_training) |

## 使い方

書籍の「環境構築」章の手順に従ってください。共通する流れは次のとおりです。

```bash
git clone https://github.com/Pakku8914/zenn-ai-applied-sandbox.git
cd zenn-ai-applied-sandbox/<書籍のディレクトリ>
docker compose up -d
docker compose exec app bash verify-all.sh
```

`verify-all.sh` が最後まで通れば、その書籍のコードがすべて手元で再現できている状態です。

サービス名（`app` など）や検証スクリプトの有無は書籍によって異なります。各ディレクトリの `README.md` と書籍の「環境構築」章を優先してください。

## コーパスなどのデータについて

AI 応用シリーズ（`rag_search_engineering/` `ai_agent_engineering/` `ai_infra_edge_deployment/` `llm_finetuning_optimization/`）では、
`corpus/` `data/` `fixtures/` `reports/` `traces/` `models/` は**生成物なのでリポジトリに含めていません**。代わりに生成器（`tools/make_corpus.py` / `tools/make_data.py` / `tools/prepare_models.py` など）を配布しています。いずれも固定シード・固定時刻で動くため、誰が何度実行しても同じデータが得られます。

`ai_infra_edge_deployment/` だけは、モデルの取得と GGUF への変換・量子化が初回に必要です（合計 2GB 弱）。手順はそのディレクトリの `README.md` と書籍の「環境構築」章にあります。

`aws_genai_developer_pro_active_recall/` は方式が異なり、**ナレッジベースのコーパス（`fixtures/kb_corpus.json`）をリポジトリに同梱しています**（サイズが小さく、決定的な検索結果を全章で共有するため）。ダウンロードも生成も不要で、`docker compose up -d` だけで始められます。

## `aws_genai_developer_pro_active_recall/` について

Amazon Bedrock は LocalStack Community が対応していないため、この書籍だけ **Bedrock 互換のモックを自作して同梱**しています。
`InvokeModel` / `InvokeModelWithResponseStream` / `Converse` / `ConverseStream` / `ApplyGuardrail` / `Retrieve` /
`RetrieveAndGenerate` / `Rerank` / `ListFoundationModels` を `boto3` からそのまま呼べます（AWS のイベントストリーム形式も実装しているため、`ConverseStream` も本物と同じ形で処理できます）。

スロットリング・レイテンシ・モデル停止・打ち切りなどを意図したタイミングで起こす制御 API も付いているので、
リトライ・フェイルオーバー・サーキットブレーカーの演習が決定的に再現できます。

**モックの単価・トークン数・レイテンシは教材用の固定値**で、実際の Amazon Bedrock の料金や性能とは一致しません。
詳細はディレクトリ内の `README.md` を参照してください。

## ライセンス

各書籍のディレクトリ内の記載に従ってください。
