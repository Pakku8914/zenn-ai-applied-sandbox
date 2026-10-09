# mockllm — 課金なしで動く Claude / OpenAI 互換モックサーバ

「AIアプリ開発の道」シリーズ（①バックエンド編・②フロントエンド編・③マルチモーダル編）の演習で使う、Anthropic Messages API と OpenAI Chat Completions API の **互換サーバ** です。公式 SDK の接続先（base URL）をこのサーバに向けるだけで、本物の SDK・本物のストリーミング解析をそのまま動かせます。API キーも課金も要りません。

- 実装：Python 3.12 + FastAPI（`app/`）。応答は `fixtures/*.json` のシナリオで決まる
- コンテナ内ポート：`8080`（ホストへは公開しない。compose のサービス名 `mockllm` で呼ぶ）
- 測定日 2026-10-02 に、次の SDK がエラーなく解析できることを実測済み（`verify-all.sh`）
  - Python：`anthropic==1.11.0`、`openai==3.23.0`
  - TypeScript：`@ai-sdk/anthropic@4.0.71`（`ai@7.0.127`）

> mockllm の応答は **本物のモデルの出力ではありません**。決まった文章を決まった形で返すだけです。usage（トークン数）も mockllm 独自の近似式で、実際の課金額とは一致しません。

## 接続のしかた

| クライアント | 接続先の書き方 | 注意 |
| :-- | :-- | :-- |
| Python `anthropic` | `Anthropic(base_url="http://mockllm:8080")` または環境変数 `ANTHROPIC_BASE_URL=http://mockllm:8080` | **`/v1` を付けない**（SDK が `/v1/messages` を足す） |
| TypeScript `@ai-sdk/anthropic` | `createAnthropic({ baseURL: "http://mockllm:8080/v1" })` | **`/v1` まで含める**。同じ環境変数 `ANTHROPIC_BASE_URL` を読むので、Python と同じ値を共有すると 404 になる |
| Python `openai` | `OpenAI(base_url="http://mockllm:8080/v1")` | `/v1` まで含める |

API キーは何でもかまいません（`mock-key` など）。ただし **ヘッダが無いと 401** を返します（Anthropic 互換は `x-api-key` か `Authorization`、OpenAI 互換は `Authorization`）。本物と同じく「キーの渡し忘れ」に気づけるようにするためです。

## エンドポイント

| メソッドとパス | 内容 |
| :-- | :-- |
| `POST /v1/messages` | Anthropic Messages API 互換。`stream: true` で SSE |
| `POST /v1/messages/count_tokens` | `{"input_tokens": N}` を返す（usage と同じ式） |
| `POST /v1/chat/completions` | OpenAI Chat Completions 互換。`stream: true` で SSE（`data: [DONE]` で終わる） |
| `GET /_mock/health` | ヘルスチェック（compose の healthcheck が使う） |
| `GET /_mock/stats` | 呼び出し回数などの統計（リトライ回数の観測用） |
| `POST /_mock/reset` | 統計とプロンプトキャッシュを消す |
| `GET /_mock/scenarios` | 読み込んだシナリオの一覧 |
| `POST /_mock/reload` | `fixtures/` を読み直す（コンテナを再起動せずにシナリオを足せる） |

## 応答の決め方

1. ヘッダ `x-mock-scenario: <名前>` があれば、そのシナリオを使う（`default` で既定応答を強制）。存在しない名前は 400
2. ヘッダが無ければ、`fixtures/*.json` を `priority` の高い順（同じならファイル名順）に照合し、最初に合ったものを使う
3. どれにも合わなければ **既定応答**（日本語の固定文。構造化出力が指定されていればスキーマから決定的に作った JSON）

照合に使う「ユーザーの発言」は、**tool_result を含まない最後の user メッセージのテキスト** です。そこから後ろにある assistant メッセージの数を **ステップ番号**（0 始まり）とし、シナリオの `steps[ステップ番号]` を返します（範囲外なら最後のステップ）。ツール呼び出しの往復は、この仕組みで「1回目は tool_use、tool_result を受けたら次へ」と進みます。

### 付属のシナリオ

| 名前 | priority | 照合条件 | 内容 |
| :-- | --: | :-- | :-- |
| `receipt` | 70 | 発言に「レシート」 | 購入品の読み取り（画像・PDF どちらでも） |
| `fridge_photo` | 60 | 画像あり＋「冷蔵庫／食材／写真／何が」 | 冷蔵庫の写真から食材リスト |
| `recipe_pdf` | 60 | document（PDF・テキスト文書）あり | レシピ本 PDF の要約（ページ数を返す） |
| `kondate_tool_search` | 50 | tools に `search_recipes` ＋「冷蔵庫／作れる／レシピ／献立／探して」 | `search_recipes` → `get_recipe`（R001）→ 最終回答 の2往復 |
| `kondate_structured` | 40 | 構造化出力の指定あり＋「献立／メニュー／1週間／3日」 | 献立表（スキーマに合わせて値を埋める） |
| `kondate_chat` | 10 | 「献立／作れる／メニュー／何を作／夕飯／晩ごはん／レシピ」 | 献立相談のテキスト応答（Markdown の番号付きリスト） |

### シナリオファイルの書式

```json
{
  "name": "kondate_tool_search",
  "description": "説明（任意）",
  "priority": 50,
  "match": {
    "any": ["冷蔵庫", "作れる"],
    "all": [],
    "tools": ["search_recipes"],
    "has_image": true,
    "has_document": true,
    "output_format": true
  },
  "steps": [
    {"content": [
      {"type": "text", "text": "条件に合うレシピを探しますね。"},
      {"type": "tool_use", "name": "search_recipes", "input": {"ingredients": ["鶏むね肉"]}}
    ]},
    {"text": "最終回答（content の代わりに text だけでもよい）"}
  ]
}
```

- `match` の各条件はすべて満たす必要がある（書かなかった条件は問わない）。`any` は「どれか1語を含む」、`all` は「すべて含む」、`tools` は「リクエストの tools にその名前がすべてある」
- `steps[].content` は `text` と `tool_use` のブロックの並び。`tool_use` の `id` は mockllm が決定的に付ける（`toolu_mock_` + ハッシュ）。`stop_reason` は tool_use があれば `tool_use`、なければ `end_turn`（`"stop_reason"` で上書き可）
- 構造化出力（Anthropic の `output_config.format` / OpenAI の `response_format`）が指定されたときは、tool_use の無いステップは JSON 1個の text になる。値は `json`（そのまま返す）か `json_hints`（スキーマに沿って生成し、プロパティ名が一致する所にヒントの値を入れる）で決める
  - `json_hints` の値が配列で、スキーマ側がスカラーなら「配列要素 i 番目には i 番目の値」。スキーマ側も配列ならその配列をそのまま使う
  - 特別なキー `_array_len` は、ヒントの無い配列を何要素で作るか（既定 1。`minItems`／`maxItems` が優先）
- テキストに書けるプレースホルダ：`{{last_user_text}}`・`{{image_count}}`・`{{image_sizes}}`（例 `1280×960`）・`{{pdf_pages}}`・`{{document_count}}`・`{{tool_result}}`（直近の tool_result の先頭200字）・`{{step}}`・`{{model}}`

## 障害注入と遅延（リクエストヘッダで指定）

| ヘッダ | 値 | 効果 |
| :-- | :-- | :-- |
| `x-mock-fault` | `429` | `rate_limit_error`。`retry-after` ヘッダ付き |
| | `529` | `overloaded_error`（OpenAI 互換は 529 の `server_error`） |
| | `500` | `api_error` |
| | `disconnect` | ストリームを途中で切る（終端チャンクを送らずに接続を閉じる）。非ストリーミングでは 500 |
| | `sse-error` | ストリーム途中で SSE の `error` イベントを送って終わる（HTTP は 200）。非ストリーミングでは 500 |
| `x-mock-fault-times` | 整数 N | **最初の N 回だけ** 障害を起こし、N+1 回目からは正常に返す。省略時は毎回 |
| `x-mock-fault-key` | 任意の文字列 | 回数を数える単位。省略時は「障害の種類＋パス＋リクエスト本文の SHA256」なので、**SDK の自動リトライ（同じ本文の再送）は同じカウンタに数えられる** |
| `x-mock-fault-after` | 整数（既定 2） | `disconnect` / `sse-error` を、何個目のコンテンツ差分の前で起こすか |
| `x-mock-retry-after` | 秒（既定 `1`） | 429 の `retry-after` の値 |
| `x-mock-error-type` | 既定 `overloaded_error` | `sse-error` で送る `error.type` |
| `x-mock-ttft-ms` | ミリ秒 | 最初のコンテンツ差分までの待ち（TTFT）。非ストリーミングでは応答前に待つ |
| `x-mock-tps` | トークン毎秒 | 2個目以降の差分ごとに「差分のトークン数 ÷ tps」秒待つ |

遅延の既定値は環境変数 `MOCKLLM_TTFT_MS`・`MOCKLLM_TPS` で変えられます（既定 0＝待たない）。画面で逐次表示を見たいときは `MOCKLLM_TPS=40` 程度にします。

`disconnect` を使うと、mockllm のログに `ERROR: ASGI callable returned without completing response.` が1行出ます。これは「途中で切った」印で、異常ではありません。

### SDK ごとの実測（2026-10-02）

| 事象 | `anthropic==1.11.0`（Python） | `@ai-sdk/anthropic@4.0.71`（ai@7.0.127） |
| :-- | :-- | :-- |
| 429 を2回 | 自動リトライで成功。呼び出し3回、`retry-after: 1` に従い約 2.0 秒 | 自動リトライで成功。呼び出し3回、約 2.0 秒（retry-after を尊重） |
| 429 が続く | 3回で `anthropic.RateLimitError` | 3回で `AI_RetryError`（`reason=maxRetriesExceeded`） |
| 529 を2回 | 自動リトライで成功（指数バックオフ 0.5s→1s×ジッタ、約 1.3 秒） | 自動リトライで成功（2s→4s、約 6.0 秒） |
| 529 が続く | 3回で `anthropic.OverloadedError` | 3回で `AI_RetryError` |
| ストリーム途中の切断 | **`httpx2.RemoteProtocolError`**（`anthropic.APIConnectionError` ではない）。リトライされない | `fullStream` の反復が `AI_APICallError`（`Failed to process successful response`）を投げる。リトライされない |
| ストリーム途中の `error` イベント | **`anthropic.APIStatusError`（`status_code=200`）**。`OverloadedError` ではない | `fullStream` の `error` パート（`AI_StreamProviderError`、`statusCode=529`、`isRetryable=true`） |

Python SDK は再送のたびに `x-stainless-retry-count`（0, 1, 2）を付けます。mockllm は `/_mock/stats` の `faults.<キー>.retry_counts` にこれを記録します。

## usage の計算式（mockllm 独自の近似）

| 項目 | 式 |
| :-- | :-- |
| テキスト | `ceil(UTF-8 のバイト数 / 3)`（日本語はおおむね1文字1トークン、英数字は3文字1トークン） |
| 入力トークン | `4`（固定） + Σ メッセージごとに `3` + 各ブロックのトークン + system + tools（JSON 文字列のトークン） |
| 画像（base64） | 長辺が 2576px を超えるなら縮小し、`ceil(幅/28) × ceil(高さ/28)`、上限 `4784`。例：1280×960 → 46×35 = **1610**、800×600 → 29×22 = **638** |
| 画像（url / file） | 寸法が分からないので固定 `1600` |
| PDF（base64） | `ページ数 × 1600`。ページ数は pypdf で数える。600 ページ超は 400 |
| 文書（text / content） | 中のテキストを上の式で数える |
| tool_use | `name` と `input`（キー順に並べた JSON）のトークン |
| tool_result | 中身（文字列またはブロック）のトークン |
| 出力トークン | 出力した text と tool_use のトークンの合計（最低 1）。`max_tokens` を超える分は切り詰めて `stop_reason: "max_tokens"` |

プロンプトキャッシュ：`cache_control` の付いた最後のブロック（またはトップレベルの `cache_control`）までを接頭辞とし、そのトークン数が **1024 以上** のときだけキャッシュします。初回は `cache_creation_input_tokens`、TTL（既定 5分、`ttl: "1h"` で1時間）内の同じ接頭辞は `cache_read_input_tokens` に入り、`input_tokens` からはその分が引かれます。

画像の検査：`media_type` と実際の画像形式が違う（例：PNG を `image/jpeg` と宣言）と 400、一辺 8000px 超も 400。リクエスト全体が 32MB を超えると 413。

## モデル固有の 400（本物の挙動の模倣）

`claude-api` スキル資料（2026-10 時点）に基づき、次のリクエストを 400 `invalid_request_error` にします。環境変数 `MOCKLLM_MODEL_RULES=off` で無効にできます。

| モデル | 400 になる指定 |
| :-- | :-- |
| `claude-opus-5-5*`・`claude-sonnet-5-5*` | `thinking: {"type": "disabled"}`／`tool_choice` の `any`・`tool`（強制）／最後のメッセージが assistant（prefill） |
| `claude-opus-5-5*` | `temperature`・`top_p`・`top_k` |

## /_mock/stats の形

```json
{
  "total": 3,
  "by_path": {"/v1/messages": 3},
  "by_status": {"429": 2, "200": 1},
  "by_scenario": {"kondate_chat": 1},
  "faults": {"429:/v1/messages:1a2b3c4d5e6f7a8b": {"fault": "429", "calls": 3, "injected": 2, "retry_counts": ["0", "1", "2"]}},
  "requests": [{"seq": 1, "path": "/v1/messages", "stream": false, "status": 429, "fault": "429", "retry_count": "0", "...": "..."}]
}
```

`requests` は直近 200 件。成功したものには `scenario`・`step`・`stop_reason`・`input_tokens`・`output_tokens`・`cache_*` が入ります。統計はプロセス内に持つだけなので、コンテナを再起動すると消えます。

## 環境変数

| 変数 | 既定 | 内容 |
| :-- | :-- | :-- |
| `MOCKLLM_TTFT_MS` | `0` | TTFT の既定値（ミリ秒） |
| `MOCKLLM_TPS` | `0` | tokens/s の既定値（0 は待たない） |
| `MOCKLLM_TEXT_CHUNK_CHARS` | `6` | text_delta 1個あたりの文字数 |
| `MOCKLLM_JSON_CHUNK_CHARS` | `16` | input_json_delta 1個あたりの文字数 |
| `MOCKLLM_MODEL_RULES` | `on` | モデル固有の 400 を模倣するか |
| `MOCKLLM_REQUIRE_API_KEY` | `on` | 認証ヘッダが無いとき 401 にするか |
| `MOCKLLM_FIXTURES_DIR` | `/app/fixtures` | シナリオの置き場所 |
