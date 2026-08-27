#!/usr/bin/env python3
"""セッション7の自己検証：イメージ設計とモデル配布の計画。

**`docker build` は実行しない。** app コンテナの中から docker は使えないため、
検証するのは次の2種類だけである。

  1. Dockerfile と `.dockerignore` の静的な性質（タグ固定・レイヤ順序・
     コンテキストに何が送られるか）
  2. サイズと時間の見積りが満たす**関係**（絶対値は環境で変わるので検証しない）

推論サーバは不要（SKIP_SERVER の有無に関係なく動く）。
"""

from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.session07.fetch_weights import (  # noqa: E402
    FetchPlan, HttpError, backoff_delays, fetch_waves, fetch_with_retry,
    herd_mb, sha256_bytes, sha256_file, should_retry,
)
from src.session07.imageplan import (  # noqa: E402
    APP_IMAGE_MB, BAKED, FETCH, GGUF_MB, SAMPLE_CONTEXT, VOLUME, Assumptions,
    Constraints, build_context, delivery_table, image_mb, image_pull_waves,
    lint_dockerfile, read_patterns, recommend, registry_stored_mb,
    rollout_traffic_mb, startup_cost, summary_report,
)

SANDBOX = Path(__file__).resolve().parents[2]
HERE = SANDBOX / "src" / "session07"

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-6)


# --- 1. Dockerfile の静的検査 ----------------------------------------------
print("=== Dockerfile の静的検査 ===")

slim = (HERE / "Dockerfile.slim").read_text(encoding="utf-8")
baked = (HERE / "Dockerfile.baked").read_text(encoding="utf-8")
torch_exp = (HERE / "Dockerfile.torch").read_text(encoding="utf-8")

check("重みを入れない Dockerfile は指摘なしで通る",
      lint_dockerfile(slim) == [], "Dockerfile.slim")
check("重みを焼く Dockerfile は方式①として許可すれば通る",
      lint_dockerfile(baked, allow_weights=True) == [], "Dockerfile.baked")
baked_default = lint_dockerfile(baked)
check("許可しなければ「重みをイメージに入れている」と指摘される",
      len(baked_default) == 1 and baked_default[0].rule == "weights-in-image",
      str(baked_default[0]) if baked_default else "指摘なし")
check("実験用の Dockerfile も指摘なしで通る",
      lint_dockerfile(torch_exp) == [], "Dockerfile.torch")

BAD = """
FROM python:latest
WORKDIR /app
COPY . /app
RUN apt-get update && apt-get install -y curl
RUN pip install -r requirements.txt
ADD https://example.internal/qwen05b-q4_k_m.gguf /opt/models/qwen05b-q4_k_m.gguf
CMD ["python", "-m", "gateway.main"]
"""
bad = lint_dockerfile(BAD)
rules = {f.rule for f in bad}
check("よくある書き方は7つの指摘に分解される", len(bad) == 7 and len(rules) == 7,
      " / ".join(sorted(rules)))
check("latest は再現性の問題として検出される", "unpinned-base" in rules)
check("COPY . を依存インストールより前に置くとキャッシュの問題になる",
      "cache-order" in rules
      and next(f.lineno for f in bad if f.rule == "cache-order") == 4,
      "行 4 の COPY .")
check("ADD で重みを取ると検証できない取得として検出される",
      {"add-remote", "weights-in-image"} <= rules)
check("apt / pip のキャッシュ残りと root 実行も検出される",
      {"apt-cache", "pip-cache", "root-user"} <= rules)

DIGEST = ("FROM ghcr.io/ggml-org/llama.cpp@sha256:" + "0" * 64
          + '\nUSER 10001\nCMD ["--server"]\n')
check("ダイジェスト固定はタグ無しでも指摘されない", lint_dockerfile(DIGEST) == [],
      "@sha256:... は中身が一意に決まる")

MULTISTAGE = """
FROM python:3.12-slim AS build
COPY requirements.txt /tmp/requirements.txt
RUN python -m venv /opt/venv \\
    && /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

FROM python:3.12-slim AS runtime
COPY --from=build /opt/venv /opt/venv
COPY infrakit/ /workspace/infrakit/
USER 10001
CMD ["/opt/venv/bin/python", "-c", "print('ok')"]
"""
check("マルチステージ（--from= 付きの COPY）も正しく読める",
      lint_dockerfile(MULTISTAGE) == [])

STAGE_REF = """
FROM python:3.12-slim AS base
USER 10001
FROM base AS runtime
CMD ["python", "-c", "print(1)"]
"""
check("前のステージ名の参照をタグ無しと誤検出しない",
      lint_dockerfile(STAGE_REF) == [])

# --- 2. .dockerignore の効果 -----------------------------------------------
print("\n=== ビルドコンテキストと .dockerignore ===")

patterns = read_patterns((HERE / "dockerignore.example").read_text(encoding="utf-8"))
naked = build_context(SAMPLE_CONTEXT, [])
ignored = build_context(SAMPLE_CONTEXT, patterns)

check(".dockerignore が無いと生成物まで送られる",
      close(naked.sent_mb, 2787.3) and close(ignored.total_mb, naked.total_mb),
      f"{naked.sent_mb:.1f} MB（COPY していない models/ と reports/ を含む）")
check(".dockerignore を置くと送るのはコードだけになる",
      close(ignored.sent_mb, 0.0) and close(ignored.excluded_mb, 2787.3),
      f"送る {ignored.sent_mb:.1f} MB / 除く {ignored.excluded_mb:.1f} MB")
check("重みとキャッシュが除外され、コードは残る",
      "models/gguf/qwen05b-q4_k_m.gguf" in ignored.excluded
      and "infrakit/__pycache__/client.cpython-312.pyc" in ignored.excluded
      and "infrakit/client.py" in ignored.sent)

for_baked = build_context(SAMPLE_CONTEXT,
                          [*patterns, "!models/gguf/qwen05b-q4_k_m.gguf"])
check("焼く1本だけを ! で送り返せる",
      close(for_baked.sent_mb, GGUF_MB["q4_k_m"])
      and "models/gguf/qwen05b-f16.gguf" in for_baked.excluded,
      f"送る {for_baked.sent_mb:.1f} MB")
wrong_order = build_context(SAMPLE_CONTEXT,
                            ["!models/gguf/qwen05b-q4_k_m.gguf", "models"])
check("! を先に書くと後の除外に負ける（順番が意味を持つ）",
      close(wrong_order.sent_mb, 0.0), f"送る {wrong_order.sent_mb:.1f} MB")

# --- 3. イメージサイズ ------------------------------------------------------
print("\n=== イメージサイズ ===")
q4 = GGUF_MB["q4_k_m"]
check("焼くとイメージは重みのぶんだけ大きくなる",
      close(image_mb(BAKED, q4), APP_IMAGE_MB + q4)
      and close(image_mb(BAKED, q4) - image_mb(VOLUME, q4), q4),
      f"{image_mb(VOLUME, q4):.1f} MB -> {image_mb(BAKED, q4):.1f} MB")
check("量子化を強めるとイメージも小さくなる",
      image_mb(BAKED, GGUF_MB["f16"]) > image_mb(BAKED, GGUF_MB["q8_0"])
      > image_mb(BAKED, q4),
      f"{image_mb(BAKED, GGUF_MB['f16']):.1f} / "
      f"{image_mb(BAKED, GGUF_MB['q8_0']):.1f} / {image_mb(BAKED, q4):.1f} MB")
check("重みを外す方式ではイメージサイズは方式によらず同じ",
      close(image_mb(VOLUME, q4), image_mb(FETCH, q4)))

# --- 4. 起動時間の内訳（検証するのは関係だけ）-------------------------------
print("\n=== 起動時間の内訳 ===")
even = Assumptions()  # レジストリとオブジェクトストレージの帯域が同じ場合
cold = {m: startup_cost(m, q4, even) for m in (BAKED, VOLUME, FETCH)}
warm = {m: startup_cost(m, q4, even, image_cached=True)
        for m in (BAKED, VOLUME, FETCH)}

check("cold では焼くのと起動時取得の合計が一致する",
      close(cold[BAKED].total_ms, cold[FETCH].total_ms),
      f"どちらも {cold[BAKED].total_ms:.1f} ms（同じ重みを1回運ぶだけ）")
check("cold で最短なのは重みがすでにあるボリューム",
      cold[VOLUME].total_ms < cold[BAKED].total_ms,
      f"{cold[VOLUME].total_ms:.1f} ms < {cold[BAKED].total_ms:.1f} ms")
check("warm（イメージがノードにある）では焼くのが最短になる",
      close(warm[BAKED].total_ms, warm[VOLUME].total_ms)
      and warm[BAKED].total_ms < warm[FETCH].total_ms,
      f"焼く {warm[BAKED].total_ms:.1f} ms < 起動時取得 {warm[FETCH].total_ms:.1f} ms")
check("焼く方式の pull だけがイメージのサイズに比例して伸びる",
      cold[BAKED].pull_ms > cold[FETCH].pull_ms and cold[FETCH].fetch_ms > 0.0
      and cold[BAKED].fetch_ms == 0.0)
check("モデルロードは重みのサイズに比例する",
      close(startup_cost(BAKED, GGUF_MB["f16"], even).load_ms,
            cold[BAKED].load_ms * GGUF_MB["f16"] / q4),
      "ディスク読み出しの見積り")

f16_cold = startup_cost(BAKED, GGUF_MB["f16"], even)
check("量子化を強めると起動も速くなる",
      f16_cold.total_ms > cold[BAKED].total_ms * 1.5,
      f"f16 {f16_cold.total_ms:.1f} ms / q4_k_m {cold[BAKED].total_ms:.1f} ms")

skewed = Assumptions(registry_mbps=30.0, object_store_mbps=200.0)
check("帯域が違えば焼くのと起動時取得の優劣は逆転する",
      startup_cost(FETCH, q4, skewed).total_ms
      < startup_cost(BAKED, q4, skewed).total_ms,
      "レジストリ 30MB/s・オブジェクトストレージ 200MB/s の場合")
check("この見積りは絶対値ではなく順序を見るためのものである",
      startup_cost(VOLUME, q4, skewed).total_ms
      < startup_cost(FETCH, q4, skewed).total_ms)

# --- 5. ロールアウトの転送量 ------------------------------------------------
print("\n=== ロールアウトの転送量（10レプリカ）===")
weights_traffic = {m: rollout_traffic_mb(m, replicas=10, changed="weights",
                                         weights_mb=q4)
                   for m in (BAKED, VOLUME, FETCH)}
code_traffic = {m: rollout_traffic_mb(m, replicas=10, changed="code",
                                      weights_mb=q4)
                for m in (BAKED, VOLUME, FETCH)}
check("モデルだけ差し替えるならボリュームは転送 0",
      close(weights_traffic[VOLUME], 0.0)
      and close(weights_traffic[BAKED], q4 * 10)
      and close(weights_traffic[FETCH], q4 * 10),
      f"焼く {weights_traffic[BAKED]:.1f} MB / ボリューム 0.0 MB")
check("コードだけ直すなら3方式で差がない",
      close(code_traffic[BAKED], code_traffic[VOLUME])
      and close(code_traffic[VOLUME], code_traffic[FETCH]),
      f"いずれも {code_traffic[BAKED]:.1f} MB")
check("同時 pull に上限があると波に分かれる",
      image_pull_waves(10, 3) == 4, "10 レプリカ / 同時 3 本 = 4 波")

# --- 6. マルチアーキ --------------------------------------------------------
print("\n=== マルチアーキ ===")
from src.session07.imageplan import (  # noqa: E402
    DEFAULT_PLATFORMS, is_arch_dependent, missing_platforms,
)

check("作っていない platform を検出できる",
      missing_platforms(["linux/arm64"], DEFAULT_PLATFORMS) == ["linux/amd64"],
      "arm64 だけ作ってクラウドに載せると exec format error になる")
check("両方作れば不足はない",
      missing_platforms(DEFAULT_PLATFORMS, DEFAULT_PLATFORMS) == [])
check("wheel はアーキ依存・重みはアーキ非依存",
      is_arch_dependent("onnxruntime-1.28.0-cp312-manylinux_x86_64.whl")
      and not is_arch_dependent("qwen05b-q4_k_m.gguf")
      and not is_arch_dependent("classifier_int8.onnx"))
stored = registry_stored_mb(BAKED, platforms=2, weights_mb=q4)
naive = (APP_IMAGE_MB + q4) * 2
check("同じ重みの層は platform をまたいで1つしか保存されない",
      close(stored, APP_IMAGE_MB * 2 + q4) and stored < naive,
      f"{stored:.1f} MB（単純に2倍すると {naive:.1f} MB）")
check("重みを外せばレジストリの占有は app だけになる",
      close(registry_stored_mb(VOLUME, platforms=2, weights_mb=q4),
            APP_IMAGE_MB * 2))

# --- 7. 方式の選択 ----------------------------------------------------------
print("\n=== 方式の選択 ===")
cases = [
    ("オフラインに配る", Constraints(offline=True), BAKED),
    ("更新が多く共有ストレージがある",
     Constraints(model_updates_per_week=2.0, shared_storage=True), VOLUME),
    ("更新が多く共有ストレージが無い",
     Constraints(model_updates_per_week=2.0), FETCH),
    ("再現性が最優先・重みが小さい",
     Constraints(reproducibility_first=True, weights_mb=GGUF_MB["q4_k_m"]), BAKED),
    ("再現性が最優先でも重みが大きい",
     Constraints(reproducibility_first=True, weights_mb=GGUF_MB["f16"]), FETCH),
    ("共有ストレージがあり更新はまれ", Constraints(shared_storage=True), VOLUME),
    ("何も決まっていない", Constraints(), FETCH),
]
for label, constraints, expected in cases:
    got = recommend(constraints)
    check(f"{label} → {expected}", got.method == expected,
          f"{got.name}: {got.reason}")

table = delivery_table()
check("比較表に3方式と5軸がそろっている",
      all(name in table for name in ("イメージに焼く", "ボリューム", "起動時に取得"))
      and all(axis in table for axis in ("イメージサイズ", "起動時間",
                                         "更新のしやすさ", "レジストリ帯域", "再現性")))
report = summary_report()
check("引き継げるレポートに測定日と前提が入る",
      "2026-08-15 実測" in report and "すべて仮定" in report
      and "読み取れる関係" in report, report.splitlines()[0])

# --- 8. 起動時取得の失敗モード ----------------------------------------------
print("\n=== 起動時取得の失敗モード ===")
check("5xx・429・408 はリトライし、404・403 はリトライしない",
      should_retry(503) and should_retry(429) and should_retry(408)
      and not should_retry(404) and not should_retry(403)
      and not should_retry(200))
check("バックオフは指数で伸びる", backoff_delays(4, 0.5) == [0.5, 1.0, 2.0],
      "実運用ではここにジッタを足す")

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    dest = root / "weights" / "model.gguf"
    payload = b"weights-v1"
    digest = sha256_bytes(payload)

    attempts = {"n": 0}
    slept: list[float] = []

    def flaky(url: str) -> bytes:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise HttpError(503, url)
        return payload

    got = fetch_with_retry(FetchPlan("http://store/model.gguf", dest, digest),
                           opener=flaky, sleep=slept.append)
    check("一時的な失敗はリトライして成功する",
          got.ok and got.attempts == 3 and slept == [0.5, 1.0],
          f"試行 {got.attempts} 回 / 待ち {slept}")
    check("成功したら本番のパスに置かれ、一時ファイルは残らない",
          dest.read_bytes() == payload
          and not (dest.parent / "model.gguf.part").exists())

    bad_sum = fetch_with_retry(FetchPlan("http://store/model.gguf", dest, "f" * 64),
                              opener=lambda url: b"weights-v2", sleep=slept.append)
    check("チェックサムが合わなければ置き換えない",
          not bad_sum.ok and "チェックサム" in bad_sum.reason,
          bad_sum.reason)
    check("失敗しても前のファイルが壊れない（原子的な差し替え）",
          dest.read_bytes() == payload)

    gone = fetch_with_retry(
        FetchPlan("http://store/none.gguf", root / "none.gguf", digest),
        opener=lambda url: (_ for _ in ()).throw(HttpError(404, url)),
        sleep=slept.append)
    check("404 は1回で諦める（待っても直らない）",
          not gone.ok and gone.attempts == 1, gone.reason)

    exhausted: list[float] = []
    dead = fetch_with_retry(
        FetchPlan("http://store/model.gguf", root / "dead.gguf", digest, attempts=3),
        opener=lambda url: (_ for _ in ()).throw(HttpError(503, url)),
        sleep=exhausted.append)
    check("リトライ上限に達したら失敗として返す",
          not dead.ok and dead.attempts == 3 and exhausted == [0.5, 1.0],
          dead.reason)

    src = root / "source.bin"
    src.write_bytes(payload)
    copied = root / "copied.bin"
    local = fetch_with_retry(FetchPlan(src.resolve().as_uri(), copied,
                                       sha256_file(src)))
    check("file:// でも同じ経路で取得できる（ネットワーク不要の検証）",
          local.ok and copied.read_bytes() == payload,
          f"{local.bytes_written} バイト")

check("一斉起動は波に分かれ、合計転送量はレプリカ数に比例する",
      fetch_waves(10, 3) == 4 and close(herd_mb(10, q4), q4 * 10),
      f"10 レプリカ / 同時 3 本 = 4 波 / 合計 {herd_mb(10, q4):.1f} MB")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション7の検証はすべて成功しました。")
