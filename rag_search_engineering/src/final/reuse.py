"""最終プロジェクト：既存セッションの実装を1か所で読み込む。

最終プロジェクトは章をまたいで部品を集める。ところが `src/session13/common.py` と
`src/session16/common.py` のように**同じファイル名のモジュール**が複数あるため、
`sys.path` に足す方式だと「先に見つかった方」が読み込まれてしまう。

そこでここでは **ファイルパスを指定して別名で読み込む**（importlib）。
新しい実装は1行も書かない。最終プロジェクトで新しく作るのは、
部品の**重ね方**と**判断の記録**だけである。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]  # sandbox/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 別名 -> (ファイル, 何を借りるか)。verify.py がこの表をそのまま検査する
SOURCES: dict[str, tuple[str, str]] = {
    "access": ("src/session13/common.py", "S13 権限フィルタ・混入検査・キャッシュ"),
    "lab": ("src/review01/review_lab.py", "Review01 クエリ側の同義語展開"),
    "bench": ("src/session12/eval_lab.py", "S12 評価ハーネス（Bench・judge・classify_case）"),
    "post": ("src/mid02/pipeline.py", "mid02 回答パイプラインと6判定"),
    "plan": ("src/mid02/priority.py", "mid02 レイテンシ予算からの逆算"),
    "ops": ("src/session16/common.py", "S16 冪等な同期・孤児の掃除・エイリアス"),
    "cost": ("src/session16/cost_model.py", "S16 コスト試算"),
    "obs": ("src/session17/metrics.py", "S17 運用指標"),
    "drift": ("src/session17/drift.py", "S17 ドリフト検知・検知できる最小の悪化幅"),
    "mask": ("src/session17/masking.py", "S17 ログのマスキング"),
    "sess": ("src/session17/sessions.py", "S17 セッション分割・言い換え率"),
    "synth": ("tools/make_fixtures.py", "合成応答の作り方（カセットの再生成に使う）"),
}


def load(alias: str, relpath: str, module_name: str | None = None):
    """パスを指定してモジュールを読み込む（同名ファイルの取り違えを防ぐ）。"""
    name = module_name or f"final_{alias}"
    if name in sys.modules:
        return sys.modules[name]
    path = ROOT / relpath
    if not path.exists():
        raise FileNotFoundError(f"{path} がありません（sandbox の配置を確認してください）")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # 実務ではまず起きないが、黙って進めない
        raise ImportError(f"{path} を読み込めません")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


access = load("access", SOURCES["access"][0])
lab = load("lab", SOURCES["lab"][0])
bench = load("bench", SOURCES["bench"][0])
post = load("post", SOURCES["post"][0])

# mid02 の triage_report は `import make_cassette` を行う。最終プロジェクト側にも
# 同名のファイルがあると取り違えるので、**先に mid02 側を正しい名前で登録**しておく。
# （最終プロジェクトのカセット生成器は `final_cassette.py` という別名にしてある）
load("mid02_cassette", "src/mid02/make_cassette.py", module_name="make_cassette")
plan = load("plan", SOURCES["plan"][0])
ops = load("ops", SOURCES["ops"][0])
cost = load("cost", SOURCES["cost"][0])
obs = load("obs", SOURCES["obs"][0])
drift = load("drift", SOURCES["drift"][0])
mask = load("mask", SOURCES["mask"][0])
sess = load("sess", SOURCES["sess"][0])
synth = load("synth", SOURCES["synth"][0])


def inventory() -> list[tuple[str, str, str]]:
    """借りている部品の一覧（成果物①の「再利用した資産」に貼る）。"""
    return [(alias, path, why) for alias, (path, why) in SOURCES.items()]


if __name__ == "__main__":
    print("最終プロジェクトが再利用する部品（新規実装ではない）")
    for alias, path, why in inventory():
        print(f"  {alias:<8} {path:<32} {why}")
