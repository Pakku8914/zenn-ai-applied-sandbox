# 最終プロジェクト：声で相談できるこんだてAI（`src/final/`）

写真・レシート・PDF で食材とレシピを取り込み、声で相談すると文ごとに返事が聞こえ、読み上げの途中で割り込めるアプリです。
セッション2〜14の部品を1つのアプリにまとめています（他のセッションは import せず、必要な分を写しています）。

## 起動

```bash
# Mac / Linux
APP_MODULE=src.final.app:app docker compose up -d --wait api
docker compose exec api python tools/fetch_whisper.py   # 初回だけ（Whisper のモデルを取得）
```

```powershell
# Windows（PowerShell）
$env:APP_MODULE="src.final.app:app"; docker compose up -d --wait api
docker compose exec api python tools/fetch_whisper.py
```

ブラウザで <http://localhost:8720/> を開くと、声で相談する画面です（マイクは `localhost` で開いたときだけ使えます）。
起動直後はウォームアップ（Whisper の読み込みと VOICEVOX の1回の合成）が終わるまで `GET /health/deps` が 503 を返します。

既定に戻すときは `APP_MODULE` を付けずに `docker compose up -d --wait api` を実行します（PowerShell は `Remove-Item Env:APP_MODULE` のあと）。

## エンドポイント

利用者はヘッダ `x-user-id`（`u` ＋数字3桁。省略時は `u001`）で区別します。`DELETE /api/me/data` だけは省略できません。

| メソッドとパス | 内容 | 初出 |
| :-- | :-- | :-- |
| `GET /health` | 生存確認（ウォームアップ中も 200） | S1 |
| `GET /health/deps` | mockllm・VOICEVOX・ウォームアップ・CPU の入口の状態。整うまで 503 | S1・S14 |
| `POST /api/uploads` | multipart `file` → 201 `{upload_id, kind, bytes, sha256}`（24時間で削除） | S2・S13 |
| `POST /api/fridge/scan` | multipart `image` → `{ingredients, needs_review, issues, image, usage}`（応答キャッシュ・`x-cache`） | S4・S14 |
| `POST /api/receipts/import` | multipart `file`（画像か PDF）→ 201 `{receipt_id, source, store, purchased_at, items, total, needs_review, issues, text_checked, usage}`。同じファイルは 409 | S7 |
| `POST /api/documents` | multipart `file`（PDF）→ 201 `{document_id, pages, sha256}`。同じ PDF は 200 | S5 |
| `POST /api/documents/{id}/ask` | `{question, pages?}` → `{answer, citations, usage}`（usage はキャッシュの2項目つき） | S5・S6・S14 |
| `POST /api/documents/{id}/import-recipes` | 202 `{job_id}` | S6 |
| `GET /api/jobs/{id}`・`GET /api/jobs/{id}/events`・`DELETE /api/jobs/{id}` | スナップショット＋`result`・SSE（progress → done／error）・取り消し | S6 |
| `POST /api/voice/transcribe` | multipart `audio`（WAV）→ `{text, audio_seconds, rtf}` | S8・S14 |
| `POST /api/voice/speak` | `{text}` → `audio/wav`＋`x-voice-credit`（パーセントエンコード） | S9・S14 |
| `POST /api/voice/loopback` | 閉ループ検査（合成した声を認識し直して CER を出す） | S1 |
| `WS /ws/voice` | 上り start（`store_audio` は任意）・20ms の PCM・stop／下り ready・vad・transcript・reply_delta・audio＋WAV・turn_end・interrupted・error | S10・S11・S13 |
| `GET /` | 声で相談する画面 | S10 |
| `DELETE /api/me/data` | 自分のデータ（アップロード・食材名・文書・レシート・音声・利用記録・応答キャッシュ・ジョブ）を消す | S13 |
| `GET /api/usage` | 自分の利用量（トークン・キャッシュ・音声の秒数・応答キャッシュの命中） | S14 |

混み合ったときは 503 `stt_busy`／`tts_busy`（`Retry-After: 2`）。WebSocket では `error {type: "stt_busy"}` を送ります。

## 検証

```bash
docker compose exec api bash verify-all.sh src/final
```

| ファイル | 確かめること |
| :-- | :-- |
| `verify_http.py` | HTTP の入口すべて（mockllm でトークン数、偽物で取り込みと音声の HTTP）・削除後の利用量が0 |
| `verify_voice.py` | 手元の食材を添えた相談・同意・割り込み・入口のあふれ・本物の部品で1ターン |
| `verify_privacy.py` | 保持期限・ログのマスク・同意・手元の食材に入れる語 |
| `verify_eval.py` | 評価スクリプトの決定的な部分（抽出の正解率・p95 の計算・基準との比較） |

## 評価（抽出の正解率・CER・遅延 p50/p95）

```bash
docker compose exec api python -m src.final.evaluate --update-baseline   # 基準を作る
docker compose exec api python -m src.final.evaluate                     # 基準と比べる（終了コード 0／1／2）
docker compose exec api python -m src.final.evaluate --skip-latency      # 遅延を測らない
docker compose exec api python -m src.final.evaluate --skip-cer --targets voice --repeat 5   # 声の1ターンの内訳
```

結果は `out/final/eval/report.json`。合否に使うのは抽出の4指標と CER（加重）だけで、遅延は表示するだけです。

## 本物の API で動かす（任意・課金あり）

`.env` の `ANTHROPIC_BASE_URL=https://api.anthropic.com` と `ANTHROPIC_API_KEY` の行を有効にしてから `api` を起動し直します。
未設定のままだと compose.yaml の既定で mockllm に向きます。検証（`verify-all.sh`）は mockllm の固定応答を前提にしているので、本物の API では実行しないでください。
