"""環境構築の章の動作確認。api コンテナの中で実行する：

    docker compose exec api bash verify-all.sh src/session01
"""

from __future__ import annotations

import importlib.metadata as md
import math
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx2

from kondate import media
from kondate.data import EXPECTED_SHA12, data_path, load_recipes, sha12
from kondate.settings import get_settings
from kondate.verifykit import check, eq, finish

API = get_settings().api_base_url
FRIDGE_PROMPT_BYTES = len("冷蔵庫の写真に写っている食材をすべて挙げてください。分量が分からないものは見た目から推定してください。".encode())

# requirements.md「固定バージョン表」と一致していること（陳腐化の検知）
PINNED = {
    "fastapi": "0.142.2", "starlette": "1.7.0", "uvicorn": "0.54.0", "pydantic": "2.13.5",
    "pydantic-settings": "2.15.0", "anthropic": "1.11.0", "httpx2": "2.13.1", "pillow": "12.3.0",
    "pypdf": "6.19.0", "fpdf2": "2.8.9", "faster-whisper": "1.2.1", "ctranslate2": "4.8.2",
    "onnxruntime": "1.30.0", "numpy": "2.5.3", "webrtcvad-wheels": "2.0.14", "websockets": "17.1",
    "python-multipart": "0.0.32", "pytest": "9.1.1",
}


@check("E1 Python とライブラリが固定バージョンどおり")
def _():
    eq(platform.python_version(), "3.12.14", "Python")
    eq({k: md.version(k) for k in PINNED}, PINNED, "ライブラリ")
    return f"Python {platform.python_version()}・{len(PINNED)} パッケージ"


@check("E2 共通データと検証用の画像・PDF の SHA256 が契約どおりで、再生成しても一致する")
def _():
    eq({n: sha12(data_path(n)) for n in EXPECTED_SHA12}, EXPECTED_SHA12, "data/ のハッシュ")
    eq({n: sha12(media.media_path(n)) for n in media.EXPECTED_SHA12}, media.EXPECTED_SHA12, "media/ のハッシュ")
    with tempfile.TemporaryDirectory() as d:
        subprocess.run([sys.executable, "tools/make_data.py", "--out", d], check=True, capture_output=True)
        subprocess.run([sys.executable, "tools/make_media.py", "--out", d], check=True, capture_output=True)
        eq({n: sha12(Path(d) / n) for n in EXPECTED_SHA12}, EXPECTED_SHA12, "再生成した data のハッシュ")
        eq({n: sha12(Path(d) / n) for n in media.EXPECTED_SHA12}, media.EXPECTED_SHA12, "再生成した media のハッシュ")
    eq(len(load_recipes()), 120, "レシピの件数")
    return f"recipes.json={EXPECTED_SHA12['recipes.json']}・media {len(media.EXPECTED_SHA12)} 件"


@check("E3 GET /health が 200 を返す")
def _():
    r = httpx2.get(f"{API}/health", timeout=5)
    eq(r.status_code, 200, "status")
    eq(r.json(), {"status": "ok", "version": "0.1.0"}, "本文")
    return r.text


@check("E4 GET /health/deps で mockllm・VOICEVOX・Whisper のモデルがすべて ok")
def _():
    r = httpx2.get(f"{API}/health/deps", timeout=10)
    eq(r.status_code, 200, f"status（本文 {r.text}）")
    deps = r.json()["deps"]
    eq(sorted(deps), ["mockllm", "voicevox", "whisper"], "項目")
    return ", ".join(f"{k}={v}" for k, v in deps.items())


@check("E5 冷蔵庫の写真を送ると、mockllm 経由で食材リスト（構造化出力）が返り、EXIF が取り除かれる")
def _():
    with media.media_path("fridge.jpg").open("rb") as f:
        r = httpx2.post(f"{API}/api/fridge/scan", files={"image": ("fridge.jpg", f, "image/jpeg")}, timeout=30)
    eq(r.status_code, 200, f"status（本文 {r.text}）")
    body = r.json()
    names = [i["name"] for i in body["ingredients"]]
    eq(names, ["キャベツ", "鶏むね肉", "卵", "にんじん", "牛乳"], "食材")
    assert all(0 <= i["confidence"] <= 1 for i in body["ingredients"])
    eq(body["image"]["exif_removed"], True, "EXIF を取り除いたか")
    eq(body["image"]["sent_size"], [1280, 960], "送った画像の寸法")
    # mockllm の式：4 + 3 + 画像 ceil(1280/28)×ceil(960/28) + ceil(プロンプトのバイト数/3)
    expected_in = 4 + 3 + math.ceil(1280 / 28) * math.ceil(960 / 28) + math.ceil(FRIDGE_PROMPT_BYTES / 3)
    eq(body["usage"]["input_tokens"], expected_in, "input_tokens")
    return f"{len(names)} 品（{'・'.join(names)}）・input_tokens={expected_in}"


@check("E6 画像でないファイルは 415 で断られ、上流には送られない")
def _():
    r = httpx2.post(f"{API}/api/fridge/scan", files={"image": ("fridge.jpg", b"not an image", "image/jpeg")}, timeout=10)
    eq(r.status_code, 415, "status")
    eq(r.json()["error"]["type"], "unsupported_media", "エラーの種別")
    return r.json()["error"]["message"]


@check("E7 VOICEVOX で読み上げた音声を faster-whisper で聞き取り直し、CER が 0.10 以下")
def _():
    r = httpx2.post(f"{API}/api/voice/loopback", timeout=120)
    eq(r.status_code, 200, f"status（本文 {r.text}）")
    body = r.json()
    assert body["cer"] <= 0.10, body
    eq(body["passed"], True, "passed")
    eq(body["credit"], "VOICEVOX:ずんだもん", "クレジット表記")
    return f"「{body['transcript']}」 CER={body['cer']}"


finish("session01")
