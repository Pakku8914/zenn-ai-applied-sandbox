# こんだてAI バックエンド（最終プロジェクト）― ②から接続する手順

『AIアプリ開発の道① バックエンド編』の最終プロジェクトです。姉妹書②（Next.js＋AI SDK 7 のフロントエンド編）の最終プロジェクトは、この `src/final/` を接続先にします。

- 受信側の基準：`ai@7.0.127` の `DefaultChatTransport`（`useChat` の既定の transport）
- 契約の正は、本書の「最終プロジェクト」章の要件（API契約④）です。この README と食い違ったら章が正です。API を変えるときは、章とこの README の両方を直してください

## 1. 全体像

```text
ブラウザ ──> ②の web（Next.js・ホスト 3710）
              └─ Route Handler（サーバー側）── Authorization: Bearer <BACKEND_API_KEY> ──>
                 backend（このアプリ・コンテナ内 8000・ホスト 8711）
                   ├─ postgres（スキーマ final）
                   ├─ redis（キー接頭辞 final:）
                   ├─ mockllm（上流の LLM。課金なし）
                   └─ worker（Celery。1週間の献立ジョブ final.plan_week を実行）
```

②は、このアプリをブラウザから直接ではなく、サーバー側（Route Handler）から呼ぶのが既定です。API キーをブラウザに配らないためです。

## 2. backend サービスの要件

②の compose は、このアプリを `backend` サービス（ホスト 8711 → コンテナ内 8000）として同梱します。①の sandbox と同じイメージ（`kondate/`・`src/final/`・`data/` が `/app` にあるもの）で、次のように動かします。

| 項目 | 値 |
| :--- | :--- |
| 起動コマンド | `uvicorn src.final.app:app --host 0.0.0.0 --port 8000`（作業ディレクトリは `/app`） |
| ヘルスチェック | `GET /health`（何も見ずに 200）。依存先まで見るなら `GET /ready` |
| 依存するサービス | postgres・redis・mockllm・worker |
| worker | 同じイメージで `celery -A kondate.worker worker --loglevel=INFO`。`src/*/tasks.py` を起動時に読む |

環境変数：

| 変数 | 既定 | 説明 |
| :--- | :--- | :--- |
| `DATABASE_URL` | `postgresql+asyncpg://kondate:kondate@postgres:5432/kondate` | テーブルはスキーマ `final` に作る |
| `REDIS_URL` | `redis://redis:6379/0` | 制限・予約・ブレーカ・ジョブの状態 |
| `CELERY_BROKER_URL` ／ `CELERY_RESULT_BACKEND` | `redis://redis:6379/1` ／ `redis://redis:6379/2` | worker と同じ値にする |
| `ANTHROPIC_BASE_URL` | `https://api.anthropic.com`（①の compose では `http://mockllm:8080`） | `/v1` を付けない。②の `LLM_BASE_URL`（`/v1` まで含む）とは書き方が違う |
| `ANTHROPIC_API_KEY` | （①の compose では `mock-key`） | mockllm に向けるなら任意の文字列でよい |
| `LLM_MODEL` ／ `LLM_MODEL_LIGHT` | `kondate/settings.py` の既定 | チャット用（primary）と、フォールバック先（light）のモデル |
| `CORS_ORIGINS` | `http://localhost:3710` | カンマ区切り。ブラウザから直接呼ぶときだけ効く |
| `TRUST_REQUEST_ID` | `true` | ②が付けた `x-request-id`（`req_` ＋ ULID）を使う。形式違いは採番し直す |
| `MAX_STREAMS_PER_WORKER` ／ `DRAIN_GRACE_SECONDS` | `100` ／ `20` | 同時ストリームの上限と、停止時の猶予（秒） |

- 上流のホスト名が `mockllm` のときだけ、②から届いた `x-mock-*` ヘッダ（障害注入）を上流へ転送します。②の画面でエラー表示を試すときに使えます
- `tasks.py` を変えたら worker を再起動してください（`docker compose restart worker`）。Celery は自動で読み直しません

### ①の sandbox だけで試す場合

②を使わずに試すときは、①の sandbox の api（ホスト 8710）に載せます。

Mac：

```bash
docker compose up -d --wait
docker compose restart worker
APP_MODULE=src.final.app:app docker compose up -d --wait api
```

Windows（PowerShell）：

```powershell
docker compose up -d --wait
docker compose restart worker
$env:APP_MODULE = "src.final.app:app"
docker compose up -d --wait api
```

戻すときは、Mac は `APP_MODULE` を付けずに `docker compose up -d --wait api`、Windows は `Remove-Item Env:APP_MODULE` のあとに `docker compose up -d --wait api` です。

## 3. API キーの発行

コマンドはコンテナの中で動くので、Mac と Windows で同じです。①の sandbox ではサービス名 `api`、②の compose ではサービス名 `backend` を使います（②で profile が付いているなら `docker compose --profile final exec backend …`）。

```bash
# 1. マイグレーション（スキーマ final を head まで）と、data/users.json の5人（u001〜u005）の登録
docker compose exec api python -m src.final.cli setup

# 2. API キーを発行する（平文はこの1回だけ表示される）
docker compose exec api python -m src.final.cli issue u001
```

```text
API キーを発行しました。平文はこの1回しか表示しません。
  user_id : u001
  prefix  : （先頭8文字）
  api_key : kd_…
```

表示された `api_key` を、②の `.env` の `BACKEND_API_KEY` に書きます。

②の `.env` に先にキーを決めてある場合は、同じ値を登録できます（開発用。本番では使わない）。キーは `kd_` に続く43文字です。新しく作るなら、次のコマンドで生成できます。

```bash
docker compose exec api python -c "import secrets; print('kd_' + secrets.token_urlsafe(32))"
docker compose exec api python -m src.final.cli register-key u001 （生成した kd_… の全体）
```

Redis の `final:` のキー（回数・使用量・ブレーカ・ジョブ）だけを消したいときは `python -m src.final.cli reset-redis` です。

> 注意：①の `python src/final/verify.py` は、冒頭でスキーマ `final` を作り直します。会話・API キー・台帳はすべて消えるので、verify のあとは `setup` と `issue`（または `register-key`）をやり直してください。

## 4. ②の側の設定

| 変数（②の `.env`） | 値 |
| :--- | :--- |
| `BACKEND_URL` | `http://backend:8000`（②の web コンテナから）。ホストから試すときは `http://localhost:8711` |
| `BACKEND_API_KEY` | 手順3のキー。サーバー側の環境変数にだけ置き、`NEXT_PUBLIC_` を付けない |

動作確認（ホストから。Windows は `curl` を `curl.exe` に読み替える）：

```bash
curl -s http://localhost:8711/ready
curl -s -X POST http://localhost:8711/api/chat -H "content-type: application/json" -d "{}"
```

1つ目は `{"status":"ready","checks":{"postgres":"ok","redis":"ok","mockllm":"ok"}}`、2つ目は 401 の `{"error":{"type":"unauthorized","message":"認証が必要です","request_id":"req_…"}}` が返れば、backend は動いています。

## 5. POST /api/chat

### リクエスト

`DefaultChatTransport` が送る本文をそのまま受けます。

```json
{
  "id": "chat-1",
  "messages": [
    {"id": "m1", "role": "user", "parts": [{"type": "text", "text": "冷蔵庫に鶏むね肉とキャベツがある。20分で作れるものは？"}]}
  ],
  "trigger": "submit-message"
}
```

| 項目 | 規則 |
| :--- | :--- |
| `Authorization` | `Bearer <APIキー>` 必須 |
| `id` | chatId。`^[A-Za-z0-9_-]{1,64}$`。利用者ごとに別の会話になる |
| `messages` | 1〜200件。最後は user のテキスト。`system` の発言・`file` part・空の発言・4000字を超える発言は 422 |
| `trigger` | `submit-message` または `regenerate-message` |
| `messageId` | 任意（使わない。再生成は、送られてきた履歴を正として DB を合わせる） |
| そのほかのキー | 捨てる（transport の `body` オプションの値が混ざっても 422 にしない） |
| `x-request-id` | 任意。`req_` ＋ ULID なら、そのまま応答とログに使う |

履歴の正は、毎回送られてくる `messages` です。サーバーは assistant の parts を `step-start` で区切り、ツールの part を tool_use と tool_result に戻して LLM に送ります。

### レスポンス（200）

ヘッダ5個（AI SDK の既定と同じ）：

| ヘッダ | 値 |
| :--- | :--- |
| `content-type` | `text/event-stream`（charset なし） |
| `cache-control` | `no-cache` |
| `connection` | `keep-alive` |
| `x-vercel-ai-ui-message-stream` | `v1` |
| `x-accel-buffering` | `no` |

ほかに `x-request-id`・`x-ratelimit-limit-requests`・`x-ratelimit-remaining-requests`・`x-ratelimit-limit-tokens`・`x-ratelimit-remaining-tokens`、フォールバックしたときだけ `x-kondate-fallback: light` が付きます。

本文は1チャンク＝`data: <JSON>` と空行です。`event:` 行は使いません。並びは次のとおりです。

```text
start {messageId}
start-step > text-start > text-delta… > text-end > tool-input-start > tool-input-delta… > tool-input-available > tool-output-available > finish-step
（ステップの数だけ繰り返す。最後のステップはテキストだけ）
data-usage
finish {finishReason, messageMetadata}
data: [DONE]
```

- `start.messageId`：保存した assistant の ID（UUIDv7）。`GET /api/conversations/{id}` の最後の assistant の `id` と同じ
- サーバーで実行したツールの結果（`tool-output-available`、失敗は `tool-output-error`）は、同じステップの `finish-step` より前に届く
- `plan_week` ツールの結果は `{"job_id": "job_…", "status": "queued"}`。進捗は `GET /api/jobs/{job_id}/events` で読む
- `finishReason`：`stop`（答え終えた）・`length`（`max_tokens`）・`content-filter`・`other`（ツールの呼び出しが上限に達し、サーバーが締めの文を送って打ち切った）・`error`（途中のエラー）

`data-usage`（`finish` の直前に1回）：

```json
{"type": "data-usage", "id": "usage",
 "data": {"input_tokens": 600, "output_tokens": 60, "cache_read_input_tokens": 0,
          "plan": "free", "used_today": 660, "limit_today": 20000}}
```

値は例です。`input_tokens` と `output_tokens` は1往復（ツールのステップをすべて含む）の合計で、`used_today` には今回の分が入っています。

`finish.messageMetadata`：

```json
{"conversation_id": "chat-1", "request_id": "req_…",
 "usage": {"input_tokens": 600, "output_tokens": 60, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}
```

## 6. エラー

### ストリーム開始前（200 を返す前）：JSON

```json
{"error": {"type": "rate_limited", "message": "ただいま混み合っています。しばらく待ってから再度お試しください。", "request_id": "req_…"}}
```

AI SDK は、この本文の文字列をそのまま `error.message` にします。②は `JSON.parse` して `error.type` で表示を変えてください。

| ステータス | type | message（固定文） | 付くヘッダ |
| :--- | :--- | :--- | :--- |
| 401 | `unauthorized` | 認証が必要です | `WWW-Authenticate: Bearer` |
| 404 | `not_found` | 指定されたものが見つかりません。（存在しない URL は「指定された URL は存在しません」） | — |
| 422 | `invalid_request` | 項目ごとの固定文（例：最後の発言は user のテキストにしてください。） | — |
| 429 | `rate_limited` | ただいま混み合っています。しばらく待ってから再度お試しください。 | `retry-after`・`x-ratelimit-*` |
| 429 | `quota_exceeded` | 本日の利用上限に達しました。日付が変わってから再度お試しください。 | `retry-after`（日付が変わるまでの秒）・`x-ratelimit-*-tokens` |
| 402 | `budget_exceeded` | 今月の利用予算に達しました。翌月になってから再度お試しください。 | なし |
| 503 | `upstream_unavailable` | AI が一時的に利用できません。時間をおいて再度お試しください。 | — |
| 503 | `service_unavailable` | このサーバーはいま新しい会話を受け付けていません。少し待ってから再度お試しください。 | `retry-after: 1` |
| 504 | `upstream_timeout` | AI の応答が時間内に返りませんでした。時間をおいて再度お試しください。 | — |
| 502 | `upstream_error` | AI の呼び出しに失敗しました。 | — |
| 500 | `internal_error` | サーバー内部でエラーが発生しました | — |

開始前に失敗した要求は、会話にも課金計測の台帳にも残りません。同じ発言をそのまま送り直してかまいません。

### ストリームの途中：error チャンク

```text
data: {"type":"error","errorText":"AI が一時的に利用できません。時間をおいて再度お試しください。"}

data: {"type":"finish","finishReason":"error"}

data: [DONE]
```

`errorText` は上の表の固定文のどれかです。上流の生のエラー文は出しません。それまでに届いたテキストは、サーバー側で `status=partial` の assistant として保存されています。

## 7. そのほかのエンドポイント

すべて `Authorization: Bearer <APIキー>` が必要です（`/health`・`/ready` を除く）。

| メソッドとパス | 応答 |
| :--- | :--- |
| `GET /api/chat/{id}/stream` | 常に 204（ストリームの再開はしない。AI SDK の再接続への応答）。切れた会話は下の GET で読み直す |
| `GET /api/conversations` | 自分の会話の一覧 `[{id, title, created_at, updated_at}]`（新しい順・最大50件。`id` は chatId） |
| `GET /api/conversations/{id}` | UIMessage[]。1往復を1つの assistant（`step-start` 区切り）にまとめる。他人の会話は 404 |
| `POST /api/jobs/plan-week` | 本文 `{"days": 1〜14}`（既定 7）。202 `{job_id, status}` と `Location` |
| `GET /api/jobs/{job_id}` | `{job_id, status, done, total, cancel_requested, result, error}` |
| `GET /api/jobs/{job_id}/events` | SSE。`progress {done, total}` … → `done {result}`（または `cancelled`・`error`）。`Last-Event-ID` 可 |
| `DELETE /api/jobs/{job_id}` | 実行中なら 202、それ以外は 200 |
| `GET /api/usage` | `{plan, used_today, limit_today, requests_per_minute}` |
| `GET /health` ／ `GET /ready` | 200 `{"status":"ok"}` ／ 200 または 503（停止中は `{"status":"draining"}`） |

他人のジョブ・期限切れのジョブも 404 です（存在を教えません）。

## 8. 検証

```bash
docker compose restart worker
docker compose exec api python src/final/verify.py
```

最後の行が `== final: 13/13 passed` なら、ここに書いた約束（ヘッダ・チャンクの並び・エラー本文・ジョブ・持ち主の分離）がすべて守られています。
