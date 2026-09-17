# LLMアプリの評価と本番運用 — 動作確認用サンドボックス

Zenn の書籍「[手を動かして学ぶ LLMアプリの評価と本番運用 ― eval 設計・ガードレール・コスト最適化・可観測性](https://zenn.dev/pakku8914/books/llm_app_evaluation_operations)」（近日公開）のコード例を実行・テストするための最小環境です。
Python 3.12 / pytest / Anthropic SDK を使います。

ホスト側のターミナルでリポジトリを取得し、このディレクトリ（`llm_app_evaluation_operations/`）に移動してから、以下のコマンドを実行します。

```bash
git clone https://github.com/Pakku8914/zenn-ai-applied-sandbox.git
cd zenn-ai-applied-sandbox/llm_app_evaluation_operations
```

**APIキーが無くても、評価ハーネスと回帰テストはすべて実行できます。**
LLM の呼び出しは差し替え可能なクライアント（スタブ／記録再生／実 API）に抽象化してあり、
既定では記録済みレスポンス（カセット）を再生するため課金が発生しません。

## 道A：Docker（推奨）

```bash
docker compose up -d                                  # 起動（初回はビルド）
docker compose exec app python record.py              # カセットを生成（APIキー不要）
docker compose exec app python -m pytest              # 回帰テストを実行
docker compose exec app python run_eval.py            # 評価レポートを出力
docker compose down                                   # 停止
```

## 道B：ネイティブ Python

```bash
python -m venv .venv
source .venv/bin/activate        # Windows は .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python record.py
python -m pytest
python run_eval.py
```

## APIキーを使う場合（任意）

このディレクトリの `.env`（`docker-compose.yml` と同じ場所）に APIキーを置くと、実 API を使う実行に切り替えられます。
`.env` は `.gitignore` 済みです。**絶対に Git にコミットしないでください。**

```bash
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env
docker compose up -d --force-recreate      # compose が .env を読み込む
docker compose exec app python run_eval.py --live
docker compose exec app python -m pytest -m live
docker compose exec app python record.py --live       # カセットを実応答で更新
```

## 構成

```
llm_app_evaluation_operations/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── pytest.ini
├── app.py                      # 評価対象のアプリ（社内 FAQ ボット）
├── run_eval.py                 # 評価を 1 回まわしてレポートを出す
├── record.py                   # カセット（記録済みレスポンス）の生成・更新
├── evalkit/
│   ├── client.py               # LLM 呼び出しの抽象（Stub / Recorded / Anthropic）
│   ├── dataset.py              # 評価データセット（JSONL）の読み込み
│   ├── checks.py               # ルールベース（決定的）評価
│   ├── judge.py                # LLM-as-a-judge（バイアス対策込み）
│   └── report.py               # 集計と Markdown レポート
├── datasets/
│   └── faq_v1.jsonl            # 評価ケース（1 行 1 ケース）
├── recordings/
│   ├── seed_faq_v1.json        # 学習用のシード応答
│   └── faq_v1.json             # 生成されるカセット（record.py が作る）
└── tests/
    ├── conftest.py
    ├── test_checks.py          # 検査器そのものの単体テスト
    └── test_regression.py      # データセット全ケースの回帰テスト
```

各セッションのコードは `sessionNN/` のようにディレクトリを追加して実行・テストしてください。
