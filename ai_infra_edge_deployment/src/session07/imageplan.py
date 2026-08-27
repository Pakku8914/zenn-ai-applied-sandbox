#!/usr/bin/env python3
"""イメージ設計とモデル配布の計画（セッション7）。

`docker build` を実行せずに確かめられる部分だけを集めてある（サンドボックスの
app コンテナの中から docker は使えないため）。扱うのは次の6つ。

- Dockerfile の静的検査（タグ固定・レイヤ順序・重みの同梱・apt/pip キャッシュ・実行ユーザー）
- `.dockerignore` の効果（ビルドコンテキストに何が送られるか）
- イメージサイズの見積り（重みを焼くと何MB増えるか）
- 起動時間の内訳（イメージ取得・プロセス起動・重み取得・モデルロード・ウォームアップ）
- ロールアウトの転送量とマルチアーキのレジストリ占有量
- 重みの配り方3方式の比較と、制約からの選択

**ここで扱う時間はすべて見積りであって実測ではない。** 帯域・ディスク・プロセス
起動時間は環境で桁が変わる。検証しているのは絶対値ではなく「方式を変えたときに
どちら向きに動くか」という関係である。

サイズだけは本書の実測値を使う（2026-08-15 実測 / aarch64 / CPU 2コア /
メモリ 5.8GB / Python 3.12.13）。
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from fnmatch import fnmatch

# ---------------------------------------------------------------------------
# 本書の実測値（サイズだけ。時間は下の Assumptions で読者が入れる）
# ---------------------------------------------------------------------------

APP_IMAGE_MB = 572.0
"""app イメージのサイズ（2026-08-15 実測）。torch を入れていないため軽い。"""

MODEL_HF_MB = 953.3
"""HuggingFace 形式のモデル取得サイズ（2026-08-15 実測）。"""

GGUF_MB: dict[str, float] = {"f16": 948.1, "q8_0": 506.5, "q4_k_m": 379.4}
"""GGUF のサイズ（2026-08-15 実測）。量子化を強めると小さくなる。"""

SAMPLE_CONTEXT: dict[str, float] = {
    # コードや設定は重みに比べて無視できる大きさなので 0.0 として数える
    "requirements.txt": 0.0,
    "Dockerfile": 0.0,
    "infrakit/client.py": 0.0,
    "infrakit/__pycache__/client.cpython-312.pyc": 0.0,
    "gateway/main.py": 0.0,
    "src/session07/plan.py": 0.0,
    "reports/load_serve_c1.json": 0.0,
    # 生成物（ここが効く）
    "models/hf/qwen05b": MODEL_HF_MB,
    "models/gguf/qwen05b-f16.gguf": GGUF_MB["f16"],
    "models/gguf/qwen05b-q8_0.gguf": GGUF_MB["q8_0"],
    "models/gguf/qwen05b-q4_k_m.gguf": GGUF_MB["q4_k_m"],
}
"""サンドボックスのビルドコンテキストを模したファイル一覧（`.dockerignore` の実験用）。"""

# ---------------------------------------------------------------------------
# Dockerfile の解析
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Instruction:
    """Dockerfile の1命令（行継続 `\\` は畳んだ状態）。"""

    lineno: int
    op: str
    args: str


def parse_dockerfile(text: str) -> list[Instruction]:
    """Dockerfile を命令の並びに分解する。コメントと空行は捨てる。"""
    out: list[Instruction] = []
    buf: list[str] = []
    start = 0
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not buf:
            if not line or line.startswith("#"):
                continue
            start = lineno
        elif line.startswith("#"):
            continue  # 継続行の途中のコメントは読み飛ばす
        if line.endswith("\\"):
            buf.append(line[:-1].strip())
            continue
        buf.append(line)
        joined = " ".join(part for part in buf if part)
        buf = []
        op, _, args = joined.partition(" ")
        out.append(Instruction(start, op.upper(), args.strip()))
    if buf:
        joined = " ".join(part for part in buf if part)
        op, _, args = joined.partition(" ")
        out.append(Instruction(start, op.upper(), args.strip()))
    return out


def _copy_parts(args: str) -> list[str]:
    """COPY / ADD の引数を並びに分ける（`--from=` などのフラグは落とす）。"""
    if args.startswith("["):
        items = [p.strip().strip('"').strip("'") for p in args.strip("[]").split(",")]
        return [p for p in items if p]
    return [p for p in args.split() if not p.startswith("--")]


def copy_sources(args: str) -> list[str]:
    """COPY / ADD の転送元（最後の引数は転送先なので除く）。"""
    parts = _copy_parts(args)
    return parts[:-1] if len(parts) >= 2 else parts


def stage_names(instructions: Iterable[Instruction]) -> set[str]:
    """マルチステージビルドのステージ名（`FROM x AS build` の build）。"""
    names: set[str] = set()
    for ins in instructions:
        if ins.op != "FROM":
            continue
        parts = ins.args.split()
        if len(parts) >= 3 and parts[1].upper() == "AS":
            names.add(parts[2])
    return names


DEP_MANIFESTS = ("requirements.txt", "requirements-*.txt", "constraints.txt",
                 "pyproject.toml", "poetry.lock", "uv.lock",
                 "package.json", "package-lock.json")
DEP_INSTALL_MARKERS = ("pip install", "pip3 install", "poetry install",
                       "uv sync", "npm ci", "npm install")
WEIGHT_PATTERNS = ("models", "*.gguf", "*.onnx", "*.safetensors", "*.bin", "*.pt")


def _suffix_paths(path: str) -> list[str]:
    parts = path.split("/")
    return ["/".join(parts[i:]) for i in range(len(parts))]


def _match_path(path: str, pattern: str) -> bool:
    """`.dockerignore` に近い規則でパスとパターンを照合する。

    - `models` はディレクトリ配下すべてに当たる（`models/gguf/x.gguf` も対象）
    - `**/__pycache__` は途中のどの階層でも当たる
    """
    path = path.strip().lstrip("./")
    pattern = pattern.strip().rstrip("/")
    if not pattern:
        return False
    if pattern.startswith("**/"):
        tail = pattern[3:]
        return any(fnmatch(s, tail) or s.startswith(tail + "/")
                   for s in _suffix_paths(path))
    return fnmatch(path, pattern) or path.startswith(pattern + "/")


def is_dep_manifest(src: str) -> bool:
    base = src.rstrip("/").split("/")[-1]
    return any(fnmatch(base, pattern) for pattern in DEP_MANIFESTS)


def is_weights(src: str) -> bool:
    return any(_match_path(src, pattern) for pattern in WEIGHT_PATTERNS)


def is_broad_copy(src: str) -> bool:
    return src.strip() in {".", "./", "*", "/", "./*"}


# ---------------------------------------------------------------------------
# 静的検査
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """検査で見つかった問題。lineno が 0 のものは特定の行に紐づかない。"""

    rule: str
    lineno: int
    message: str

    def __str__(self) -> str:
        where = f"行 {self.lineno}" if self.lineno else "ファイル全体"
        return f"[{self.rule}] {where}: {self.message}"


def check_pinned_base(instructions: list[Instruction]) -> list[Finding]:
    """FROM のタグが固定されているか。`latest` とタグ無しは再現性がない。"""
    stages = stage_names(instructions)
    out: list[Finding] = []
    for ins in instructions:
        if ins.op != "FROM":
            continue
        ref = ins.args.split()[0]
        if ref in stages or "@sha256:" in ref:
            continue  # 前のステージの参照、またはダイジェスト固定
        name, _, tag = ref.rpartition(":")
        if not name or "/" in tag:
            out.append(Finding("unpinned-base", ins.lineno,
                               f"{ref} にタグがありません。同じ Dockerfile が"
                               "別の中身でビルドされます"))
        elif tag == "latest":
            out.append(Finding("unpinned-base", ins.lineno,
                               f"{ref} は latest です。いつビルドしたかで中身が変わります"))
    return out


def check_layer_order(instructions: list[Instruction]) -> list[Finding]:
    """依存のインストールより前にコードを COPY していないか（レイヤキャッシュ）。"""
    install_line = 0
    for ins in instructions:
        if ins.op == "RUN" and any(m in ins.args for m in DEP_INSTALL_MARKERS):
            install_line = ins.lineno
            break
    if not install_line:
        return []
    out: list[Finding] = []
    for ins in instructions:
        if ins.lineno >= install_line or ins.op not in {"COPY", "ADD"}:
            continue
        for src in copy_sources(ins.args):
            if is_broad_copy(src) or not is_dep_manifest(src):
                out.append(Finding("cache-order", ins.lineno,
                                   f"依存のインストール（行 {install_line}）より前に "
                                   f"{src} を COPY しています。コードを1文字直すたびに"
                                   "依存の再インストールが走ります"))
                break
    return out


def check_weights_in_image(instructions: list[Instruction]) -> list[Finding]:
    """重みをイメージに入れているか（方式①では意図的なので呼び出し側で許可する）。"""
    out: list[Finding] = []
    for ins in instructions:
        if ins.op not in {"COPY", "ADD"}:
            continue
        for src in copy_sources(ins.args):
            if is_weights(src):
                out.append(Finding("weights-in-image", ins.lineno,
                                   f"{src} をイメージに入れています。イメージが重みのぶん"
                                   "大きくなり、pull が起動時間に乗ります"))
                break
    return out


def check_remote_add(instructions: list[Instruction]) -> list[Finding]:
    """`ADD https://...` は取得の失敗もチェックサムも扱えない。"""
    out: list[Finding] = []
    for ins in instructions:
        if ins.op != "ADD":
            continue
        for src in copy_sources(ins.args):
            if src.startswith(("http://", "https://")):
                out.append(Finding("add-remote", ins.lineno,
                                   f"{src} を ADD で取得しています。リトライも"
                                   "チェックサム検証もできません"))
                break
    return out


def check_apt_cache(instructions: list[Instruction]) -> list[Finding]:
    out: list[Finding] = []
    for ins in instructions:
        if ins.op == "RUN" and "apt-get install" in ins.args \
                and "/var/lib/apt/lists" not in ins.args:
            out.append(Finding("apt-cache", ins.lineno,
                               "apt のインデックスを同じ RUN で消していません。"
                               "消さないぶんがそのまま層に残ります"))
    return out


def check_pip_cache(instructions: list[Instruction]) -> list[Finding]:
    out: list[Finding] = []
    for ins in instructions:
        if ins.op == "RUN" and "pip install" in ins.args \
                and "--no-cache-dir" not in ins.args:
            out.append(Finding("pip-cache", ins.lineno,
                               "pip install に --no-cache-dir がありません。"
                               "wheel のキャッシュがイメージに残ります"))
    return out


def check_run_as_root(instructions: list[Instruction]) -> list[Finding]:
    users = [ins.args.split()[0] for ins in instructions if ins.op == "USER" and ins.args]
    if not users:
        return [Finding("root-user", 0, "USER 命令がありません。root で動きます")]
    if users[-1] in {"root", "0"}:
        return [Finding("root-user", 0, f"最後の USER が {users[-1]} です")]
    return []


def lint_dockerfile(text: str, *, allow_weights: bool = False) -> list[Finding]:
    """Dockerfile を静的に検査する。allow_weights=True で方式①（焼く）を許可する。"""
    ins = parse_dockerfile(text)
    findings = (check_pinned_base(ins) + check_layer_order(ins)
                + check_remote_add(ins) + check_apt_cache(ins)
                + check_pip_cache(ins) + check_run_as_root(ins))
    if not allow_weights:
        findings += check_weights_in_image(ins)
    return sorted(findings, key=lambda f: (f.lineno, f.rule))


# ---------------------------------------------------------------------------
# ビルドコンテキストと `.dockerignore`
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BuildContext:
    sent: dict[str, float]
    excluded: dict[str, float]

    @property
    def sent_mb(self) -> float:
        return sum(self.sent.values())

    @property
    def excluded_mb(self) -> float:
        return sum(self.excluded.values())

    @property
    def total_mb(self) -> float:
        return self.sent_mb + self.excluded_mb


def build_context(files: dict[str, float], patterns: Iterable[str]) -> BuildContext:
    """`.dockerignore` を適用した結果、ビルドコンテキストに送られるものを返す。

    `!` から始まるパターンは除外の取り消し（後に書いたものが勝つ）。
    """
    pats = [p.strip() for p in patterns
            if p.strip() and not p.strip().startswith("#")]
    sent: dict[str, float] = {}
    excluded: dict[str, float] = {}
    for path, mb in files.items():
        drop = False
        for pattern in pats:
            if pattern.startswith("!"):
                if _match_path(path, pattern[1:]):
                    drop = False
            elif _match_path(path, pattern):
                drop = True
        (excluded if drop else sent)[path] = mb
    return BuildContext(sent, excluded)


def read_patterns(text: str) -> list[str]:
    """`.dockerignore` の中身を行の並びにする。"""
    return [line.strip() for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")]


# ---------------------------------------------------------------------------
# イメージサイズと起動時間の見積り
# ---------------------------------------------------------------------------

BAKED, VOLUME, FETCH = "baked", "volume", "fetch"
METHOD_ORDER = (BAKED, VOLUME, FETCH)
METHOD_NAMES = {BAKED: "イメージに焼く", VOLUME: "ボリューム", FETCH: "起動時に取得"}


@dataclass(frozen=True)
class ImagePlan:
    """イメージを層の集まりとして見た見積り。層の分け方は読者が決める。"""

    label: str
    layers: dict[str, float] = field(default_factory=dict)

    @property
    def total_mb(self) -> float:
        return sum(self.layers.values())

    def with_weights(self, weights_mb: float) -> ImagePlan:
        layers = dict(self.layers)
        layers["weights"] = weights_mb
        return ImagePlan(f"{self.label}+weights", layers)


def app_plan(app_mb: float = APP_IMAGE_MB) -> ImagePlan:
    return ImagePlan("app", {"app": app_mb})


def image_mb(method: str, weights_mb: float, app_mb: float = APP_IMAGE_MB) -> float:
    """その方式で配るイメージのサイズ。焼く場合だけ重みが乗る。"""
    return app_mb + (weights_mb if method == BAKED else 0.0)


@dataclass(frozen=True)
class Assumptions:
    """起動時間の見積りに使う入力。

    **ここに並ぶ値はすべて仮定であり、本書の実測値ではない。** 自分の環境で
    測った値に置き換えて使うこと。既定値の出どころは次のとおり。

    - registry_mbps / object_store_mbps : ネットワークの実効転送レート（要測定）
    - disk_read_mbps : 本書の実測（f16 変換で 988MB を約3.5秒 = 284MB/s 書き出し）
      を出発点として置いただけの値。読み出しは環境で違うので必ず測り直す
    - process_start_ms / warmup_ms : 仮の値。自分のサーバで測って置き換える
    """

    registry_mbps: float = 100.0
    object_store_mbps: float = 100.0
    disk_read_mbps: float = 284.0
    process_start_ms: float = 300.0
    warmup_ms: float = 500.0


@dataclass(frozen=True)
class StartupCost:
    """コールドスタートの内訳（すべてミリ秒）。"""

    method: str
    weights_mb: float
    image_cached: bool
    pull_ms: float
    start_ms: float
    fetch_ms: float
    load_ms: float
    warmup_ms: float

    @property
    def total_ms(self) -> float:
        return (self.pull_ms + self.start_ms + self.fetch_ms
                + self.load_ms + self.warmup_ms)

    @property
    def name(self) -> str:
        return METHOD_NAMES[self.method]


def startup_cost(method: str, weights_mb: float,
                 assumptions: Assumptions | None = None, *,
                 image_cached: bool = False,
                 app_mb: float = APP_IMAGE_MB) -> StartupCost:
    """起動時間を4つ（+ ウォームアップ）に分けて見積もる。

    `image_cached=True` はノードに同じイメージが既にある状態（pull が消える）。
    `VOLUME` は重みがすでにノードか共有ストレージにある前提の値である。
    新しいノードにボリュームを用意するコストはこの見積りの外側にある。
    """
    a = assumptions or Assumptions()
    if method not in METHOD_NAMES:
        raise ValueError(f"未知の方式です: {method}")
    size = image_mb(method, weights_mb, app_mb)
    pull = 0.0 if image_cached else size / a.registry_mbps * 1000.0
    fetch = weights_mb / a.object_store_mbps * 1000.0 if method == FETCH else 0.0
    load = weights_mb / a.disk_read_mbps * 1000.0
    return StartupCost(method, weights_mb, image_cached, pull,
                       a.process_start_ms, fetch, load, a.warmup_ms)


def rollout_traffic_mb(method: str, *, replicas: int, changed: str,
                       weights_mb: float, app_mb: float = APP_IMAGE_MB) -> float:
    """1回のロールアウトでネットワークを流れる量（MB）。

    changed は "code"（コードだけ直した）／"weights"（モデルだけ差し替えた）／
    "both"。イメージを2層（app / weights）に単純化して、変わった層だけが
    レプリカ数ぶん転送されるものとして数える。
    """
    if changed not in {"code", "weights", "both"}:
        raise ValueError(f"changed は code / weights / both のいずれかです: {changed}")
    total = 0.0
    if changed in {"code", "both"}:
        total += app_mb * replicas
    if changed in {"weights", "both"}:
        if method == VOLUME:
            total += 0.0          # ボリュームを差し替えるだけ。ネットワークに流れない
        else:
            total += weights_mb * replicas
    return total


def registry_stored_mb(method: str, *, platforms: int, weights_mb: float,
                       app_mb: float = APP_IMAGE_MB) -> float:
    """マルチアーキのイメージがレジストリに占めるサイズ。

    アーキ依存の層（wheel を含む app 層）は platform ごとに別の層になる。
    重みはアーキ非依存なので、同じ内容の層は内容アドレスで1つだけ保存される
    （バイト単位で同一の層になるように COPY していることが前提）。
    """
    stored = app_mb * platforms
    if method == BAKED:
        stored += weights_mb
    return stored


# ---------------------------------------------------------------------------
# 3方式の比較と選択
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Delivery:
    key: str
    name: str
    image_size: str
    cold_start: str
    updatability: str
    registry_traffic: str
    reproducibility: str
    when: tuple[str, ...]


DELIVERIES: dict[str, Delivery] = {
    BAKED: Delivery(
        BAKED, "イメージに焼く",
        image_size="app + 重み（本書の例なら 572.0 + 379.4 MB）",
        cold_start="初回は pull に重みぶん乗る。ノードにキャッシュされれば最短",
        updatability="モデルを変えるたびにイメージを作り直して配り直す",
        registry_traffic="ロールアウトのたびにレプリカ数 × 重みが流れる",
        reproducibility="最も高い。イメージのダイジェストが重みまで含めて一意に決まる",
        when=("オフラインの環境に配る（ネットワークが無い）",
              "重みが小さく、更新もめったにない",
              "監査で「動いたものと同じ中身」を再現する必要がある"),
    ),
    VOLUME: Delivery(
        VOLUME, "ボリューム",
        image_size="app だけ（本書の例なら 572.0 MB）",
        cold_start="重みがすでにある前提なら最短。用意するコストは別に払う",
        updatability="ボリューム上のファイルを差し替えるだけ",
        registry_traffic="モデル更新では 0（レジストリを通らない）",
        reproducibility="低い。ボリュームの中身は外から書き換えられる",
        when=("同じノード（か共有ストレージ）に複数のレプリカが載る",
              "モデルを頻繁に差し替える",
              "帯域が細く、同じ重みを何度も運びたくない"),
    ),
    FETCH: Delivery(
        FETCH, "起動時に取得",
        image_size="app だけ（本書の例なら 572.0 MB）",
        cold_start="起動のたびに重みの取得が乗る",
        updatability="取得先のバージョンを変えるだけ",
        registry_traffic="レジストリは app だけ。重みはオブジェクトストレージ側",
        reproducibility="取得先のバージョンとチェックサムを固定すれば確保できる",
        when=("ノードが増減する（スケールアウトが日常）",
              "モデルの種類が多く、イメージを掛け算で増やしたくない",
              "共有ストレージが使えない"),
    ),
}

_AXES: tuple[tuple[str, str], ...] = (
    ("イメージサイズ", "image_size"),
    ("起動時間", "cold_start"),
    ("更新のしやすさ", "updatability"),
    ("レジストリ帯域", "registry_traffic"),
    ("再現性", "reproducibility"),
)


def delivery_table() -> str:
    """3方式 × 5軸の比較表（Markdown）。"""
    header = "| 軸 | " + " | ".join(DELIVERIES[m].name for m in METHOD_ORDER) + " |"
    sep = "| :--- | :--- | :--- | :--- |"
    rows = [f"| {label} | "
            + " | ".join(getattr(DELIVERIES[m], attr) for m in METHOD_ORDER) + " |"
            for label, attr in _AXES]
    return "\n".join([header, sep, *rows])


@dataclass(frozen=True)
class Constraints:
    """方式を選ぶための制約。"""

    offline: bool = False
    shared_storage: bool = False
    model_updates_per_week: float = 0.0
    replicas: int = 1
    weights_mb: float = GGUF_MB["q4_k_m"]
    reproducibility_first: bool = False


@dataclass(frozen=True)
class Recommendation:
    method: str
    reason: str

    @property
    def name(self) -> str:
        return METHOD_NAMES[self.method]


BAKE_SIZE_LIMIT_MB = 600.0
"""これより大きい重みを焼くのは、再現性が最優先でも勧めない目安。"""


def recommend(c: Constraints) -> Recommendation:
    """制約から方式を1つ選ぶ。判断の順番そのものが本章の結論である。"""
    if c.offline:
        return Recommendation(BAKED, "ネットワークが無い環境では、重みを運ぶ手段が"
                                     "イメージしかありません")
    if c.model_updates_per_week >= 1.0:
        if c.shared_storage:
            return Recommendation(VOLUME, "更新が週1回以上あり共有ストレージが"
                                          "使えるので、ファイルの差し替えで済みます")
        return Recommendation(FETCH, "更新が週1回以上あるので、イメージを作り直さずに"
                                     "取得先のバージョンを変えられる方式を選びます")
    if c.reproducibility_first and c.weights_mb <= BAKE_SIZE_LIMIT_MB:
        return Recommendation(BAKED, f"再現性が最優先で、重みが "
                                     f"{c.weights_mb:.1f}MB と "
                                     f"{BAKE_SIZE_LIMIT_MB:.0f}MB 以内に収まります")
    if c.shared_storage:
        return Recommendation(VOLUME, "共有ストレージがあるので、同じ重みを"
                                      "何度も運ばずに済みます")
    return Recommendation(FETCH, "重みが大きいか置き場所が共有できないので、"
                                 "イメージから外して起動時に取得します")


# ---------------------------------------------------------------------------
# マルチアーキ
# ---------------------------------------------------------------------------

ARCH_DEPENDENT_SUFFIXES = (".whl", ".so", ".a", ".dylib", ".exe")
DEFAULT_PLATFORMS = ("linux/amd64", "linux/arm64")


def is_arch_dependent(name: str) -> bool:
    """そのファイルが CPU アーキテクチャに依存するか。

    重み（`.gguf` / `.onnx` / `.safetensors`）はアーキ非依存で、
    wheel や共有ライブラリはアーキ依存である。**この非対称が
    「重みをイメージから外すとマルチアーキが楽になる」理由**である。
    """
    lowered = name.lower()
    return lowered.endswith(ARCH_DEPENDENT_SUFFIXES)


def missing_platforms(built: Iterable[str], required: Iterable[str]) -> list[str]:
    """必要なのに作っていない platform。"""
    have = set(built)
    return [p for p in required if p not in have]


# ---------------------------------------------------------------------------
# レポート
# ---------------------------------------------------------------------------


def startup_table(costs: list[StartupCost]) -> str:
    header = ("| 方式 | イメージ取得 | プロセス起動 | 重み取得 | モデルロード "
              "| ウォームアップ | 合計 |")
    sep = "| :--- | --: | --: | --: | --: | --: | --: |"
    rows = [f"| {c.name} | {c.pull_ms:.1f} | {c.start_ms:.1f} | {c.fetch_ms:.1f} "
            f"| {c.load_ms:.1f} | {c.warmup_ms:.1f} | {c.total_ms:.1f} |"
            for c in costs]
    return "\n".join([header, sep, *rows])


def summary_report(*, quant: str = "q4_k_m", assumptions: Assumptions | None = None,
                   replicas: int = 10, app_mb: float = APP_IMAGE_MB) -> str:
    """引き継げる形の計画レポート（Markdown）。"""
    a = assumptions or Assumptions()
    weights = GGUF_MB[quant]
    cold = [startup_cost(m, weights, a, app_mb=app_mb) for m in METHOD_ORDER]
    warm = [startup_cost(m, weights, a, image_cached=True, app_mb=app_mb)
            for m in METHOD_ORDER]

    lines = [
        "# モデル配布の計画（セッション7）",
        "",
        f"- モデル: qwen05b-{quant}.gguf（{weights:.1f} MB・2026-08-15 実測）",
        f"- app イメージ: {app_mb:.1f} MB（2026-08-15 実測）",
        f"- 前提（すべて仮定。自分の環境の値に置き換える）: "
        f"レジストリ {a.registry_mbps:.1f} MB/s / "
        f"オブジェクトストレージ {a.object_store_mbps:.1f} MB/s / "
        f"ディスク読み出し {a.disk_read_mbps:.1f} MB/s / "
        f"プロセス起動 {a.process_start_ms:.1f} ms / "
        f"ウォームアップ {a.warmup_ms:.1f} ms",
        "",
        "## 3方式の比較",
        "",
        f"| 方式 | イメージ | cold 合計 | warm 合計 | 重み更新の転送（{replicas}レプリカ） |",
        "| :--- | --: | --: | --: | --: |",
    ]
    for method, c, w in zip(METHOD_ORDER, cold, warm):
        traffic = rollout_traffic_mb(method, replicas=replicas, changed="weights",
                                     weights_mb=weights, app_mb=app_mb)
        lines.append(f"| {METHOD_NAMES[method]} | "
                     f"{image_mb(method, weights, app_mb):.1f} MB | "
                     f"{c.total_ms:.1f} ms | {w.total_ms:.1f} ms | {traffic:.1f} MB |")

    lines += ["", "## 起動時間の内訳（cold・ミリ秒）", "", startup_table(cold), ""]
    lines += ["## 量子化と起動時間（イメージに焼く場合・cold）", "",
              "| 形式 | 重み | イメージ | cold 合計 |", "| :--- | --: | --: | --: |"]
    for name, mb in GGUF_MB.items():
        cost = startup_cost(BAKED, mb, a, app_mb=app_mb)
        lines.append(f"| {name} | {mb:.1f} MB | "
                     f"{image_mb(BAKED, mb, app_mb):.1f} MB | {cost.total_ms:.1f} ms |")

    lines += [
        "",
        "## 読み取れる関係",
        "",
        "- cold の合計は「焼く」と「起動時に取得」で変わらない（同じ重みを1回"
        "ネットワークで運ぶため）。差が出るのは、レジストリとオブジェクト"
        "ストレージの帯域が違うときだけである。",
        "- warm（ノードにイメージがある状態）では「焼く」が最短になる。"
        "焼く方式の利点はここにしか出ない。",
        "- 重みを更新するときの転送量は、ボリュームだけが 0 になる。",
        "- 量子化を強めると重みが小さくなり、取得もロードも短くなる。",
        "- ボリュームの cold は「重みがすでにノード（か共有ストレージ）にある」"
        "前提の値である。新しいノードにボリュームを用意するコストはこの表の外にある。",
        "",
        "## 3方式 × 5軸",
        "",
        delivery_table(),
        "",
    ]
    return "\n".join(lines)


def image_pull_waves(replicas: int, max_parallel: int) -> int:
    """同時に pull できる数に制限があるとき、何波に分かれるか。"""
    if replicas <= 0 or max_parallel <= 0:
        raise ValueError("replicas と max_parallel は 1 以上を指定してください")
    return math.ceil(replicas / max_parallel)
